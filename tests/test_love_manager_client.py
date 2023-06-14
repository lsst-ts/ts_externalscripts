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


import aiohttp
import asyncio
import logging
import os
import unittest

from love_manager_client import LoveManagerClient

logger = logging.getLogger(__name__)
logger.propagate = True


class TestLoveManagerClient(unittest.IsolatedAsyncioTestCase):

    def setUp(self) -> None:
        self.location = "foo.bar"
        self.token = "test"

    async def json_mock(self):
        return {"token": self.token}

    async def test_create_love_manager_client(self):
        # Arrage
        username = "admin"
        password = "test"
        event_streams = {
            ("Test", 0): ["heartbeat", "logLevel", "summaryState"],
        }
        telemetry_streams = {}

        client_session_post_mock = unittest.mock.patch("aiohttp.ClientSession.post")
        client_session_post_mock_client = client_session_post_mock.start()

        post_response = unittest.mock.MagicMock()
        post_response.__aenter__.return_value.json = self.json_mock
        client_session_post_mock_client.return_value = post_response

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
        expected_websocket_url = f"ws://{self.location}/manager/ws/subscription?token={self.token}"
        self.assertEqual(love_manager_client.websocket_url, expected_websocket_url)

        await love_manager_client.close()
        client_session_post_mock.stop()
