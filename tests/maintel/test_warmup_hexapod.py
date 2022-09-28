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

import logging

# import random
import unittest
import numpy as np

from lsst.ts import utils
from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel import WarmUpHexapod
from lsst.ts.idl.enums import Script
from lsst.ts.idl.enums.MTHexapod import SalIndex

np.random.seed(42)

index_gen = utils.index_generator()


class TestCameraHexapodWarmUp(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make_script")
        self.script = WarmUpHexapod(index=index)

        self.log.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def test_configure(self):
        async with self.make_script():

            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            hexapod = "camera"
            axis = "z"
            step_size = 250
            sleep_time = 2.0
            max_position = 13000

            await self.configure_script(
                hexapod=hexapod,
                axis=axis,
                step_size=step_size,
                sleep_time=sleep_time,
                max_position=max_position,
            )

            assert self.script.config.hexapod == hexapod
            assert self.script.config.axis == axis
            assert self.script.config.step_size == [
                step_size
            ]  # int/float are converted to lists
            assert self.script.config.sleep_time == [
                sleep_time
            ]  # int/float are converted to lists
            assert self.script.config.max_position == max_position

            assert self.script.hexapod_name == f"{hexapod}_hexapod"
            assert self.script.hexapod_sal_index == getattr(
                SalIndex, f"{hexapod}_hexapod".upper()
            )

    async def test_run(self):

        # Start the test itself
        async with self.make_script():

            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            hexapod = "camera"
            axis = "z"
            step_size = 2000
            sleep_time = 0.1
            max_position = 13000

            # Configure the script
            await self.configure_script(
                hexapod=hexapod,
                axis=axis,
                step_size=step_size,
                sleep_time=sleep_time,
                max_position=max_position,
            )
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Add some mocks
            class MockPosition:
                position = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

            self.script.move_hexapod = unittest.mock.AsyncMock()
            self.script.hexapod.tel_application.aget = unittest.mock.AsyncMock(
                return_value=(MockPosition)
            )

            # Run the script
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "warmup_hexapod.py"
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
