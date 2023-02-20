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
import os

import aiohttp
import yaml
from lsst.ts import salobj, utils


class ManagerClient:
    """Connect to a LOVE-manager instance.

    Parameters
    ----------
    location : `str`
        Host of the running LOVE-manager instance
    username: `str`
        LOVE username to use as authenticator
    password: `str`
        Password of the choosen LOVE user
    event_streams: `dict`
        Dictionary whith each item as <CSC:salindex>: <events_names_tuple>
        e.g. {"ATDome:0": ('allAxesInPosition', 'authList',
        'azimuthCommandedState', 'azimuthInPosition', ...)
    telemetry_streams: `dict`
        Dictionary whith each item as <CSC:salindex>: <telemetries_names_tuple>
        e.g. {"ATDome:0": ('position', ...)

    Notes
    -----
    **Details**

    * Generate websocket connections using provided credentials
    by token authentication and subscribe to every
    event and telemetry specified.
    """

    def __init__(self, location, username, password, event_streams, telemetry_streams):
        self.username = username
        self.event_streams = event_streams
        self.telemetry_streams = telemetry_streams

        self.websocket_url = None
        self.num_received_messages = 0
        self.msg_traces = []

        self.__location = location
        self.__password = password
        self.__websocket = None

        self.start_task = utils.make_done_future()

    async def __request_token(self):
        """Authenticate on the LOVE-manager instance
        to get an authorization token and set the
        corresponding websocket_url.

        Raises
        ------
        RuntimeError
             If the token cannot be retrieved.
        """

        url = f"http://{self.__location}/manager/api/get-token/"
        data = {
            "username": self.username,
            "password": self.__password,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, data=data) as resp:
                    json_data = await resp.json()
                    token = json_data["token"]
                    self.websocket_url = (
                        f"ws://{self.__location}/manager/ws/subscription?token={token}"
                    )
            except Exception as e:
                raise RuntimeError("Authentication failed.") from e

    async def __handle_message_reception(self):
        """Handles the reception of messages."""

        if self.__websocket:
            async for message in self.__websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    msg = json.loads(message.data)
                    if "category" not in msg or (
                        "option" in msg and msg["option"] == "subscribe"
                    ):
                        continue
                    self.num_received_messages = self.num_received_messages + 1
                    tracing = msg["tracing"]
                    tracing["client_rcv"] = utils.current_tai()
                    self.msg_traces.append(tracing)

    async def __subscribe_to(self, csc, salindex, topic, topic_type):
        """Subscribes to the specified CSC stream in order to
        receive LOVE-producer(s) data

        Parameters
        ----------
        csc : `str`
            Name of the CSC stream
        salindex: `int`
            Salindex of the CSC stream
        topic: `str`
            Topic of the CSC stream
        topic_type: `str`
            Type of topic: `event` or `telemetry`
        """

        subscribe_msg = {
            "option": "subscribe",
            "category": topic_type,
            "csc": csc,
            "salindex": salindex,
            "stream": topic,
        }
        await self.__websocket.send_str(json.dumps(subscribe_msg))

    async def start_ws_client(self):
        """Start client websocket connection"""

        try:
            await self.__request_token()
            if self.websocket_url is not None:
                async with aiohttp.ClientSession() as session:
                    self.__websocket = await session.ws_connect(self.websocket_url)
                    for name in self.event_streams:
                        csc, salindex = salobj.name_to_name_index(name)
                        for stream in self.event_streams[name]:
                            await self.__subscribe_to(csc, salindex, stream, "event")
                    for name in self.telemetry_streams:
                        csc, salindex = salobj.name_to_name_index(name)
                        for stream in self.telemetry_streams[name]:
                            await self.__subscribe_to(
                                csc, salindex, stream, "telemetry"
                            )
                    await self.__handle_message_reception()
        except Exception as e:
            raise RuntimeError("Manager Client connection failed.") from e

    def create_start_task(self):
        self.start_task = asyncio.create_task(self.start_ws_client())

    async def close(self):
        if self.__websocket:
            await self.__websocket.close()


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
                description: Host of the running LOVE instance (web server) to stress
                type: string
              number_of_clients:
                description: The number of clients to create
                type: number
              number_of_messages:
                description: The number of messages to store before calculating the mean latency
                type: number
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
            + self.number_of_clients * self.loop_time_client_connection
        )

    async def configure(self, config):
        """Configure the script.

        Specify the Stress test configurations:
        - LOVE host location
        - Number of clients
        - Number of messages to store
        - CSCs

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration with several attributes, defined in `get_schema`

        Notes
        -----
        Saves the results on several attributes:

        * config    : `types.SimpleNamespace`, same as config param
        * remotes   : a dict, with each item as
            CSC_name[:index]: `lsst.ts.salobj.Remote`

        Constructing a `salobj.Remote` is slow (DM-17904), so configuration
        may take a 10s or 100s of seconds per CSC.
        """
        self.log.info("Configure started")

        # set configurations
        self.config = config

        # get credentials
        self.username = os.environ.get("USER_USERNAME")
        self.password = os.environ.get("USER_USER_PASS")
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

        # Enable all CSCs
        for remote in self.remotes.values():
            await salobj.set_summary_state(remote=remote, state=salobj.State.ENABLED)

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
            client = ManagerClient(
                self.config.location,
                self.username,
                self.password,
                event_streams,
                telemetry_streams,
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
            await client.close()

        # Send all CSCs to Standby
        for remote in self.remotes.values():
            await salobj.set_summary_state(remote=remote, state=salobj.State.STANDBY)

    def get_mean_latency(self):
        """Calculate the mean latency of all received messages."""

        traces = [trace for client in self.clients for trace in client.msg_traces]
        latency_vals = [trace["client_rcv"] - trace["producer_snd"] for trace in traces]
        return sum(latency_vals) / len(latency_vals)
