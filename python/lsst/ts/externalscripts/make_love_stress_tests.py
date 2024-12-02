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

__all__ = ["StressLOVE"]

import asyncio
import os

import yaml
from lsst.ts import salobj

from .love_manager_client import LoveManagerClient


class StressLOVE(salobj.BaseScript):
    """Run a stress test for one or more CSCs.

    Notes
    -----
    **Details**

    * Run a LOVE stress test by generating several client connections
    that will listen to every event and telemetry of the specified CSCs
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Run a stress test for one or more CSCs")

        # SimpleNamespace to store stress test configurations
        # params described on `get_schema`
        self.config = None

        # list to store clients connections,
        # each one an instance of ManagerClient
        self.clients = []

        # dict to store remote connections,
        # with each item in the form of
        # `CSC_name[:index]`: `lsst.ts.salobj.Remote`
        self.remotes = {}

        # commands timeout
        self.cmd_timeout = 10

        # time to wait for each message collection
        self.loop_time_message_collection = 1

        # time to wait for each Manager client connection
        self.loop_time_client_connection = 1

        # message frequency
        self.expected_message_frequency = 100

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
              number_of_clients:
                description: The number of clients to create
                type: integer
              number_of_messages:
                description: The number of messages to store before calculating the mean latency
                type: integer
              data:
                description: List of CSC_name[:index]
                type: array
                minItems: 1
                items:
                    type: string
            required: [location, number_of_clients, number_of_messages, data]
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
        metadata.duration = (
            self.config.number_of_messages / self.expected_message_frequency
            + self.config.number_of_clients * self.loop_time_client_connection
        )

    async def configure(self, config):
        """Configure the script.

        Look for credentials configured with environment variables:
        - USER_USERNAME
        - USER_USER_PASS
        These should match the credentials used to log into the LOVE instance.

        Specify the Stress test configurations:
        - LOVE host location
        - Number of clients
        - Number of messages
        - CSCs

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
        remotes = dict()
        for name_index in config.data:
            name, index = salobj.name_to_name_index(name_index)
            self.log.debug(f"Create remote {name}:{index}")
            if name_index not in remotes:
                remote = salobj.Remote(domain=self.domain, name=name, index=index)
                remotes[name_index] = remote
        self.remotes = remotes

    async def run(self):
        """Run script."""

        self.log.info(f"Waiting for {len(self.remotes)} remotes to be ready")
        await asyncio.gather(*[remote.start_task for remote in self.remotes.values()])

        # Checking all CSCs are enabled
        for remote_name, remote in self.remotes.items():
            summary_state_evt = await remote.evt_summaryState.aget()
            remote_summary_state = salobj.State(summary_state_evt.summaryState)
            if remote_summary_state != salobj.State.ENABLED:
                raise RuntimeError(f"{remote_name} CSC must be enabled")

        event_streams = dict()
        telemetry_streams = dict()
        for name_index in self.remotes:
            name, index = salobj.name_to_name_index(name_index)
            salinfo = salobj.SalInfo(self.domain, name)
            try:
                event_streams[name_index] = salinfo.event_names
                telemetry_streams[name_index] = salinfo.telemetry_names
            finally:
                await salinfo.close()

        # Create clients and listen to ws messages
        self.log.info(
            f"Waiting for {self.config.number_of_clients} Manager Clients to be ready"
        )
        for i in range(self.config.number_of_clients):
            client = LoveManagerClient(
                self.config.location,
                self.username,
                self.password,
                event_streams,
                telemetry_streams,
                log=self.log,
                msg_tracing=True,
            )
            self.clients.append(client)
            client.create_start_task()
            await asyncio.sleep(self.loop_time_client_connection)

        msg_count = 0
        while msg_count < self.config.number_of_messages:
            await asyncio.sleep(self.loop_time_message_collection)
            for client in self.clients:
                msg_count += len(client.msg_traces)
            self.log.debug(
                f"Received {msg_count}/{self.config.number_of_messages} messages"
            )
        self.log.info(
            "LOVE stress test result: "
            f"mean_latency_ms={self.get_mean_latency():0.2f} num_messages={msg_count}"
        )

    async def cleanup(self):
        """Return the system to its default status."""

        # Close all ManagerClients
        for client in self.clients:
            if client is not None:
                await client.close()

    def get_mean_latency(self):
        """Calculate the mean latency of all received messages."""

        traces = [trace for client in self.clients for trace in client.msg_traces]
        latency_vals = [trace["client_rcv"] - trace["producer_snd"] for trace in traces]
        return sum(latency_vals) / len(latency_vals)
