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
from lsst.ts.externalscripts import UptimeLOVE

logger = logging.getLogger(__name__)
logger.propagate = True


class TestUptimeLOVE(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = UptimeLOVE(index=index)

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def test_configure(self):
        os.environ["USER_USERNAME"] = "TEST"
        os.environ["USER_USER_PASS"] = "TEST"
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            host = "love.tu.lsst.org"
            cscs = [
                "ATAOS",
                "MTAirCompressor:1",
                "MTAirCompressor:2",
            ]
            max_duration = 10

            await self.configure_script(
                host=host,
                cscs=cscs,
                max_duration=max_duration,
            )

            assert self.script.config.host == host
            assert self.script.config.cscs == cscs
            assert self.script.config.max_duration == max_duration

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "make_love_uptime_tests.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
