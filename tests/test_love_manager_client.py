# This file is part of ts_standardscripts
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

import asyncio
import json
import unittest

import aiohttp
from lsst.ts import utils
from lsst.ts.externalscripts import LoveManagerClient


class MockAsyncContextManger:
    """Mock a basic context manager for async with statement"""

    def __init__(self):
        pass

    async def __aenter__(self, *args, **kwargs):
        return self

    async def __aexit__(self, *args, **kwargs):
        pass


class MockAsyncIterator:
    """Mock a basic async iterator for async for statement"""

    def __init__(self, messages):
        self.messages = messages
        self.index = 0
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.messages):
            raise StopAsyncIteration
        message = self.messages[self.index]
        self.index += 1
        return message


class MockClientSessionPost(MockAsyncContextManger):
    """Mock for aiohttp.ClientSession.post"""

    def __init__(self, status, json_content):
        self.status = status
        self.json_content = json_content

    async def json(self):
        return self.json_content


class MockClientSessionWsConnect(MockAsyncIterator):
    """Mock for aiohttp.ClientSession.ws_connect"""

    def __init__(self, messages):
        parsed_messages = [
            aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, message, None)
            for message in messages
        ]
        super().__init__(parsed_messages)

    async def send_str(self, message):
        pass

    async def close(self):
        pass


class MockClientSession(MockAsyncContextManger):
    """Mock for aiohttp.ClientSession"""

    def __init__(self, post_response, ws_messages):
        self.ws_messages = ws_messages
        self.post = unittest.mock.MagicMock(
            return_value=MockClientSessionPost(
                post_response["status"], post_response["json_content"]
            )
        )

    async def ws_connect(self, *args, **kwargs):
        return MockClientSessionWsConnect(self.ws_messages)


class TestLoveManagerClient(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def make_msg_payload(category, csc, salindex, data, tracing={}):
        """Make a message payload with the format that
        the manager expects to receive as stream data

        Parameters
        ----------
        csc : `str`
            Name of the CSC
        salindex: `int`
            Salindex of the CSC
        topic: `str`
            Topic of the CSC stream
        topic_type: `str`
            Type of topic: `event` or `telemetry`
        data: `dict`
            Data to be sent

        Returns
        -------
        msg_payload: `dict`
            Message payload to be sent to the websocket
        """
        msg_payload = {
            "category": category,
            "data": [
                {
                    "csc": csc,
                    "salindex": salindex,
                    "data": data,
                }
            ],
            "tracing": tracing,
        }
        return msg_payload

    def setUp(self) -> None:
        self.location = "http://foo.bar"
        self.secure_location = "https://foo.bar"
        self.domain = "foo.bar"
        self.token = "T0K3N"

        self.mock_client_session = MockClientSession(
            {
                "status": 200,
                "json_content": {"token": self.token},
            },
            [
                json.dumps(
                    TestLoveManagerClient.make_msg_payload(
                        "event",
                        "Test",
                        0,
                        {"heartbeat": {"heartbeat": {"value": utils.current_tai()}}},
                        {
                            "producer_snd": utils.current_tai(),
                            "manager_rcv_from_producer": utils.current_tai(),
                            "manager_snd_to_group": utils.current_tai(),
                        },
                    )
                ),
                json.dumps(
                    TestLoveManagerClient.make_msg_payload(
                        "event",
                        "Test",
                        0,
                        {"summaryState": {"summaryState": {"value": 2}}},
                        {
                            "producer_snd": utils.current_tai(),
                            "manager_rcv_from_producer": utils.current_tai(),
                            "manager_snd_to_group": utils.current_tai(),
                        },
                    )
                ),
            ],
        )

        self.mock_client_session_for_send_command = MockClientSession(
            {
                "status": 200,
                "json_content": {"cmdAck": True},
            },
            [],
        )

        self.mock_client_session_for_send_command_with_error = MockClientSession(
            {
                "status": 500,
                "json_content": {"cmdAck": False},
            },
            [],
        )

        self.client_session_mock = unittest.mock.patch("aiohttp.ClientSession")

    def tearDown(self) -> None:
        self.client_session_mock.stop()

    async def test_create_love_manager_client(self):
        """Test creating a LoveManagerClient instance"""
        # Arrange
        username = "admin"
        password = "test"
        event_streams = {
            "Test:0": ["heartbeat", "logLevel", "summaryState"],
        }
        telemetry_streams = {}

        client_session_mock_client = self.client_session_mock.start()
        client_session_mock_client.return_value = self.mock_client_session

        # Act
        love_manager_client = LoveManagerClient(
            location=self.location,
            username=username,
            password=password,
            event_streams=event_streams,
            telemetry_streams=telemetry_streams,
        )
        love_manager_client.create_start_task()

        while love_manager_client.websocket_url is None:
            await asyncio.sleep(1)

        # Assert
        expected_websocket_url = (
            f"ws://{self.domain}/manager/ws/subscription?token={self.token}"
        )
        self.assertEqual(love_manager_client.websocket_url, expected_websocket_url)

        self.assertEqual(love_manager_client.num_received_messages, 0)
        self.assertEqual(len(love_manager_client.msg_traces), 0)

        await love_manager_client.close()

    async def test_create_love_manager_client_with_secure_connection(self):
        """Test creating a LoveManagerClient instance with secure connection"""
        # Arrange
        username = "admin"
        password = "test"
        event_streams = {
            "Test:0": ["heartbeat", "logLevel", "summaryState"],
        }
        telemetry_streams = {}

        client_session_mock_client = self.client_session_mock.start()
        client_session_mock_client.return_value = self.mock_client_session

        # Act
        love_manager_client = LoveManagerClient(
            location=self.secure_location,
            username=username,
            password=password,
            event_streams=event_streams,
            telemetry_streams=telemetry_streams,
        )
        love_manager_client.create_start_task()

        while love_manager_client.websocket_url is None:
            await asyncio.sleep(1)

        # Assert
        expected_websocket_url = (
            f"wss://{self.domain}/manager/ws/subscription?token={self.token}"
        )
        self.assertEqual(love_manager_client.websocket_url, expected_websocket_url)

        self.assertEqual(love_manager_client.num_received_messages, 0)
        self.assertEqual(len(love_manager_client.msg_traces), 0)

        await love_manager_client.close()

    async def test_create_love_manager_client_with_msg_tracing(self):
        """Test creating a LoveManagerClient instance with msg_tracing=True"""
        # Arrange
        username = "admin"
        password = "test"
        event_streams = {
            "Test:0": ["heartbeat", "logLevel", "summaryState"],
        }
        telemetry_streams = {}

        client_session_mock_client = self.client_session_mock.start()
        client_session_mock_client.return_value = self.mock_client_session

        # Act
        love_manager_client = LoveManagerClient(
            location=self.location,
            username=username,
            password=password,
            event_streams=event_streams,
            telemetry_streams=telemetry_streams,
            msg_tracing=True,
        )
        love_manager_client.create_start_task()

        while love_manager_client.websocket_url is None:
            await asyncio.sleep(1)

        # Assert
        expected_websocket_url = (
            f"ws://{self.domain}/manager/ws/subscription?token={self.token}"
        )
        self.assertEqual(love_manager_client.websocket_url, expected_websocket_url)

        self.assertEqual(love_manager_client.num_received_messages, 2)
        self.assertEqual(len(love_manager_client.msg_traces), 2)

        await love_manager_client.close()

    async def test_love_manager_client_send_command(self):
        """Test sending a command to the manager"""
        # Arrange
        username = "admin"
        password = "test"
        event_streams = {}
        telemetry_streams = {}

        client_session_mock_client = self.client_session_mock.start()
        client_session_mock_client.return_value = self.mock_client_session

        love_manager_client = LoveManagerClient(
            location=self.location,
            username=username,
            password=password,
            event_streams=event_streams,
            telemetry_streams=telemetry_streams,
        )
        love_manager_client.create_start_task()

        while love_manager_client.websocket_url is None:
            await asyncio.sleep(1)

        # Change client session mock to return a 200 response
        client_session_mock_client.return_value = (
            self.mock_client_session_for_send_command
        )

        # Act
        try:
            await love_manager_client.send_sal_command(
                "Test", 0, "cmd_setLogLevel", {"level": 10}
            )
        except Exception:
            assert False

        # Assert
        await love_manager_client.close()

    async def test_love_manager_client_send_command_error(self):
        """Test sending a command to the manager
        and getting an error response"""
        # Arrange
        username = "admin"
        password = "test"
        event_streams = {}
        telemetry_streams = {}

        client_session_mock_client = self.client_session_mock.start()
        client_session_mock_client.return_value = self.mock_client_session

        love_manager_client = LoveManagerClient(
            location=self.location,
            username=username,
            password=password,
            event_streams=event_streams,
            telemetry_streams=telemetry_streams,
        )
        love_manager_client.create_start_task()

        while love_manager_client.websocket_url is None:
            await asyncio.sleep(1)

        # Change client session mock to return a 500 response
        client_session_mock_client.return_value = (
            self.mock_client_session_for_send_command_with_error
        )

        # Act
        try:
            await love_manager_client.send_sal_command(
                "Test", 0, "cmd_setLogLevel", {"level": 10}
            )
        except Exception:
            assert True

        # Assert
        await love_manager_client.close()
