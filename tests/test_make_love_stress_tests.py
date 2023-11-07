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


import logging
import os
import unittest

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts import StressLOVE

logger = logging.getLogger(__name__)
logger.propagate = True


class TestStressLOVE(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = StressLOVE(index=index)

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def test_configure(self):
        os.environ["USER_USERNAME"] = "TEST"
        os.environ["USER_USER_PASS"] = "TEST"
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            location = "http://love.tu.lsst.org"
            number_of_clients = 50
            number_of_messages = 5000
            data = [
                "ATAOS:0",
                "MTAirCompressor:1",
                "MTAirCompressor:2",
            ]

            await self.configure_script(
                location=location,
                number_of_clients=number_of_clients,
                number_of_messages=number_of_messages,
                data=data,
            )

            assert self.script.config.location == location
            assert self.script.config.number_of_clients == number_of_clients
            assert self.script.config.number_of_messages == number_of_messages
            assert self.script.config.data == data

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "make_love_stress_tests.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
