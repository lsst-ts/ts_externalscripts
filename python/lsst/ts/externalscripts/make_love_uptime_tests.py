# This file is part of ts_externalscripts
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License

__all__ = ["UptimeLOVE"]

import asyncio
import logging
import math
import os
import random
import time

import yaml
from lsst.ts import salobj, utils

from .love_manager_client import LoveManagerClient


class LOVEUptimeMonitor:
    def __init__(self) -> None:
        self.log = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        self.start_time = utils.current_tai()
        self.total_time = 0
        self.uptime_time = 0

    def record_uptime(self) -> None:
        current_time = time.time()
        self.total_time += current_time - self.start_time
        self.uptime_time += current_time - self.start_time
        self.start_time = current_time

    def record_downtime(self) -> None:
        current_time = time.time()
        self.total_time += current_time - self.start_time
        self.start_time = current_time

    def get_uptime_percentage(self) -> float:
        if self.total_time == 0:
            return math.nan
        return (self.uptime_time / self.total_time) * 100


class UptimeLOVE(salobj.BaseScript):
    """Run a uptime test for LOVE.

    Notes
    -----
    **Details**

    * Run a LOVE uptime test by generating several client connections
    that will listen to some events and telemetries of the specified CSCs
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Run a uptime test for LOVE")

        # SimpleNamespace to store stress test configurations
        # params described on `get_schema`
        self.config = None

        # instance of ManagerClient used to read data from LOVE
        self.client = None

        # instance of LOVEUptimeMonitor used to monitor LOVE uptime
        self.uptime_monitor = None

        # dict to store remote connections,
        # with each item in the form of
        # `CSC_name[:index]`: `lsst.ts.salobj.Remote`
        self.remotes = {}

        # commands timeout
        self.cmd_timeout = 10

        # interval to send commands
        self.loop_time_send_commands = 5

        # maxmimum time to execute the script
        self.max_duration = 0

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/StressLOVE.yaml
            title: StressLOVE v1
            description: Configuration for StressLOVE
            type: object
            properties:
              location:
                description: Complete URL of the running LOVE instance (web server) to stress
                    e.g. https://base-lsp.lsst.codes/love or http://love01.ls.lsst.org
                type: string
              cscs:
                description: List of CSC_name[:index]
                    e.g. ["ATDome", "ScriptQueue:2"].
                type: array
                minItems: 1
                items:
                    type: string
              max_duration:
                description: The maximum duration of the script execution (sec). This only applies after
                    initial setup, including reading summary state for each CSC.
                    It is also approximate, because it is only checked every few seconds.
                type: number
                exclusiveMinimum: 0
            required: [location, cscs, max_duration]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def set_metadata(self, metadata):
        """Compute estimated duration.

        Parameters
        ----------
        metadata : `lsst.ts.salobj.BaseMsgType`
            Script ``metadata`` event data.
        """
        # a crude estimate;
        metadata.duration = self.config.max_duration

    async def configure(self, config):
        """Configure the script.

        Look for credentials configured with environment variables:
        - USER_USERNAME
        - USER_USER_PASS
        These should match the credentials used to log into the LOVE instance.

        Also specify the Uptime test configurations:
        - LOVE host location
        - CSCs
        - Maximum duration of the script execution

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration with several attributes, defined in `get_schema`

        Notes
        -----
        Saves the results on several attributes:

        * username  : `str`, LOVE username to use as authenticator
        * password  : `str`, Password of the choosen LOVE user
        * config    : `types.SimpleNamespace`, same as config param
        * remotes   : a dict, with each item as
            CSC_name[:index]: `lsst.ts.salobj.Remote`
        * max_duration : `float`, maximum duration of the
            script execution (approximate)

        Constructing a `salobj.Remote` is slow (DM-17904), so configuration
        may take a 10s or 100s of seconds per CSC.

        Raises
        ------
        RuntimeError
            If environment variables USER_USERNAME or
            USER_USER_PASS are not defined.
        """
        self.log.info("Configure started")

        # set configurations
        self.config = config

        # get credentials
        self.username = os.environ.get("USER_USERNAME")
        self.password = os.environ.get("USER_USER_PASS")
        if self.username is None:
            raise RuntimeError(
                "Configuration failed: environment variable USER_USERNAME not defined"
            )
        if self.password is None:
            raise RuntimeError(
                "Configuration failed: environment variable USER_USER_PASS not defined"
            )

        # construct remotes
        for name_index in config.cscs:
            name, index = salobj.name_to_name_index(name_index)
            self.log.debug(f"Create remote {name}:{index}")
            if (name, index) not in self.remotes:
                remote = salobj.Remote(
                    domain=self.domain,
                    name=name,
                    index=index,
                    include=["heartbeat", "logLevel", "summaryState"],
                )
                self.remotes[name_index] = remote
            else:
                self.log.warning(f"Remote {name}:{index} already exists")

        # get max duration
        self.max_duration = self.config.max_duration

        self.log.info("Configure done...")

    async def run(self):
        """Run script."""

        self.log.info(f"Waiting for {len(self.remotes)} remotes to be ready")
        await asyncio.gather(*[remote.start_task for remote in self.remotes.values()])

        # Checking all CSCs are enabled
        for remote_name, remote in self.remotes.items():
            summary_state_evt = await remote.evt_summaryState.aget(
                timeout=self.cmd_timeout
            )
            log_level_evt = remote.evt_logLevel.get()
            if not log_level_evt:
                raise RuntimeError(f"{remote_name} CSC logLevel event has no data")
            remote_summary_state = salobj.State(summary_state_evt.summaryState)
            if remote_summary_state != salobj.State.ENABLED:
                raise RuntimeError(f"{remote_name} CSC must be enabled")

        # Create dictionaries to store topics to subscribe per CSC
        # Keys are tuples (csc_name, salindex) and values are lists of topics
        event_streams = dict()
        telemetry_streams = dict()
        for remote_name in self.remotes:
            event_streams[remote_name] = ["heartbeat", "logLevel", "summaryState"]
            telemetry_streams[remote_name] = []

        # Create clients and listen to ws messages
        self.log.info("Waiting for the Manager Client to be ready")
        self.client = LoveManagerClient(
            self.config.location,
            self.username,
            self.password,
            event_streams,
            telemetry_streams,
        )
        self.client.create_start_task()

        # Create the UptimeMonitor
        self.log.info("Creating LOVE Uptime monitor")
        self.uptime_monitor = LOVEUptimeMonitor()

        t0 = utils.current_tai()
        while True:
            current_uptime = self.uptime_monitor.get_uptime_percentage()
            self.log.info(f"LOVE uptime is {current_uptime:.2f}%")

            execution_time = utils.current_tai() - t0
            if execution_time > self.max_duration:
                break

            await asyncio.sleep(self.loop_time_send_commands)
            name_index = random.choice(list(self.remotes.keys()))
            name, index = salobj.name_to_name_index(name_index)
            try:
                self.log.debug(f"Sending command to {name}:{index}")
                await self.client.send_sal_command(
                    name, index, "cmd_setLogLevel", {"level": 10}
                )
                self.uptime_monitor.record_uptime()
            except Exception as e:
                self.uptime_monitor.record_downtime()
                self.log.error(f"Error sending command: {e}")

    async def cleanup(self):
        """Return the system to its default status."""
        # Close the ManagerClient
        if self.client is not None:
            await self.client.close()

    async def close(self):

        await asyncio.gather(*[remote.start_task for remote in self.remotes.values()])
        for remote_name, remote in self.remotes.items():
            self.log.debug(f"Closing remote for {remote_name}.")
            await remote.close()

        del self.remotes

        await super().close()
