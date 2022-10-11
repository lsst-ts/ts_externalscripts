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
import json

import aiohttp
import requests
import yaml
from astropy.time import Time
from lsst.ts import salobj


class ClientInstance:
    """Connect to a LOVE-manager instance.

    Notes
    -----
    **Details**

    * Generate websocket connections using provided credentials
    by token authentication and subscribes to every
    event and telemetry specified.
    """

    def __init__(self, location, username, password, event_streams, telemetry_streams):
        self.location = location
        self.username = username
        self.password = password
        self.event_streams = event_streams
        self.telemetry_streams = telemetry_streams

        self.websocket_url = ""
        self.received_messages = 0
        self.msg_traces = []

    def request_token(self):
        """Authenticate on the LOVE-manager instance
        to get an authorization token."""

        url = f"http://{self.location}/manager/api/get-token/"
        data = {
            "username": self.username,
            "password": self.password,
        }
        resp = requests.post(url, data=data)
        try:
            token = resp.json()["token"]
        except Exception:
            raise Exception("Authentication failed")
        self.websocket_url = (
            f"ws://{self.location}/manager/ws/subscription?token={token}"
        )

    async def handle_message_reception(self):
        """Handles the reception of messages."""

        if self.websocket:
            async for message in self.websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    msg = json.loads(message.data)
                    if "category" not in msg or (
                        "option" in msg and msg["option"] == "subscribe"
                    ):
                        continue
                    self.received_messages = self.received_messages + 1
                    tracing = msg["tracing"]
                    tracing["client_rcv"] = Time.now().tai.datetime.timestamp()
                    self.msg_traces.append(tracing)

    async def subscribe_to(self, csc, salindex, stream, topic_type):
        """Subscribes to the specified stream"""

        subscribe_msg = {
            "option": "subscribe",
            "category": topic_type,
            "csc": csc,
            "salindex": salindex,
            "stream": stream,
        }
        await self.websocket.send_str(json.dumps(subscribe_msg))

    async def start_ws_client(self):
        """Start client websocket connection"""

        async with aiohttp.ClientSession() as session:
            self.websocket = await session.ws_connect(self.websocket_url)
            for csc in self.event_streams:
                for stream in self.event_streams[csc]:
                    await self.subscribe_to(
                        csc.split(":")[0], csc.split(":")[1], stream, "event"
                    )
            for csc in self.telemetry_streams:
                for stream in self.telemetry_streams[csc]:
                    await self.subscribe_to(
                        csc.split(":")[0], csc.split(":")[1], stream, "telemetry"
                    )
            await self.handle_message_reception()


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

        # number of clients to simulate on the stress test
        self.number_of_clients = 10

        # list to store clients connections
        self.clients = []

        # commands timeout
        self.cmd_timeout = 10

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
                description: Domain of the running LOVE instance to stress
                type: string
              username:
                description: Username to authenticate connections
                type: string
              password:
                description: Password to authenticate User
                type: string
              data:
                description: List of CSC_name[:index]
                type: array
                minItems: 1
                items:
                    type: string
            required: [location, user, password, data]
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    def set_metadata(self, metadata):
        """Compute estimated duration.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """
        # a crude estimate;
        metadata.duration = len(self.clients) * 5

    async def configure(self, config):
        """Configure the script.

        Specify the Stress test configurations:
        - LOVE domain location
        - User
        - Password
        - CSCs

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration with several attributes:

            * location : a string, with the location of the
                LOVE instance to stress
            * username : a string, with the username
                to authenticate connections
            * password : a string, with the password of the user
            * data : a list, where each element is a string in the form:

                * CSC name and optional index as ``csc_name:index`` (a `str`).

        Notes
        -----
        Saves the results on several attributes:

        * location : a string, with the location of the LOVE instance to stress
        * username : a string, with the username to authenticate connections
        * password : a string, with the password of the user
        * remotes : a dict of (csc_name, index): remote,
            an `lsst.ts.salobj.Remote`

        Constructing a `salobj.Remote` is slow (DM-17904), so configuration
        may take a 10s or 100s of seconds per CSC.
        """
        self.log.info("Configure started")

        # set configurations
        self.location = config.location
        self.username = config.username
        self.password = config.password

        # construct remotes
        remotes = dict()
        for elt in config.data:
            name, index = salobj.name_to_name_index(elt)
            self.log.debug(f"Create remote {name}:{index}")
            if elt not in remotes:
                remote = salobj.Remote(domain=self.domain, name=name, index=index)
                remotes[elt] = remote

        self.remotes = remotes

    async def run(self):
        """Run script."""
        tasks = [
            remote.start_task
            for remote in self.remotes.values()
            if not remote.start_task.done()
        ]
        if tasks:
            self.log.info(f"Waiting for {len(tasks)} remotes to be ready")
            await asyncio.gather(*tasks)

        # Enable all CSCs
        for csc, remote in self.remotes.items():
            evt = await remote.evt_summaryState.aget()
            state = salobj.State(evt.summaryState)

            if state == salobj.State.STANDBY:
                await remote.cmd_start.start(timeout=self.cmd_timeout)
                await remote.cmd_enable.start(timeout=self.cmd_timeout)

        event_streams = dict()
        telemetry_streams = dict()
        for producer in self.remotes.keys():
            event_streams[producer] = salobj.SalInfo(
                self.domain, producer.split(":")[0]
            ).__getattribute__("event_names")
            telemetry_streams[producer] = salobj.SalInfo(
                self.domain, producer.split(":")[0]
            ).__getattribute__("telemetry_names")

        # Create clients and listen to ws messages
        loop = asyncio.get_event_loop()
        for i in range(self.number_of_clients):
            self.clients.append(
                ClientInstance(
                    self.location,
                    self.username,
                    self.password,
                    event_streams,
                    telemetry_streams,
                )
            )

        for client in self.clients:
            client.request_token()
            loop.create_task(client.start_ws_client())

    async def clean(self):
        """Return the system to its default status."""

        for csc, remote in self.remotes.items():
            evt = await remote.evt_summaryState.aget()
            state = salobj.State(evt.summaryState)

            if state == salobj.State.ENABLED:
                await remote.cmd_disable.start(timeout=self.cmd_timeout)
                await remote.cmd_standby.start(timeout=self.cmd_timeout)

    def get_mean_latency(self):
        """Calculate the mean latency of all received messages."""

        traces = [trace for client in self.clients for trace in client.msg_traces]
        latency_vals = [trace["client_rcv"] - trace["producer_snd"] for trace in traces]
        return sum(latency_vals) / len(latency_vals)
