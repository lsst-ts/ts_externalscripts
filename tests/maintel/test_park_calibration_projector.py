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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import logging
import os
import unittest

import pytest
from lsst.ts import externalscripts, standardscripts, utils
from lsst.ts.externalscripts.maintel.park_calibration_projector import (
    ParkCalibrationProjector,
)
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys
from lsst.ts.xml.enums import Script

index_gen = utils.index_generator()


class TestParkCalibrationProjector(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True
        self.projector_setup = ("test_led", 100.0, 10.0, 10.0, "On")

    @property
    def remote_group(self) -> MTCalsys:
        """The remote_group property."""
        return self.mtcalsys

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make script")
        self.script = ParkCalibrationProjector(index=index)

        await self.mock_mtcalsys()

        self.log.debug("Finished initializing from basic_make_script")
        return (self.script,)

    async def mock_mtcalsys(self):
        """Mock Calsys CSCs"""
        self.script.mtcalsys = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcalsys.get_projector_setup = unittest.mock.AsyncMock(
            return_value=self.projector_setup
        )
        self.script.mtcalsys.led_rest_position = 100.0

    async def test_configure(self):
        config = {
            "ignore": [
                "TunableLaser",
                "FiberSpectrograph:101",
                "FiberSpectrograph:102",
                "Electrometer:103",
            ]
        }
        async with self.make_script():
            await self.configure_script(**config)
            assert self.script.state.state == Script.ScriptState.CONFIGURED

    async def test_run_without_failures(self):
        config = {
            "ignore": [
                "TunableLaser",
                "FiberSpectrograph:101",
                "FiberSpectrograph:102",
                "Electrometer:103",
            ]
        }
        async with self.make_script():
            await self.configure_script(**config)
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Run the script
            self.log.debug("Running the script")
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_park_failure(self):
        config = {
            "ignore": [
                "TunableLaser",
                "FiberSpectrograph:101",
                "FiberSpectrograph:102",
                "Electrometer:103",
            ]
        }
        self.projector_setup = ("test_fail", 0.0, 0.0, 0.0, "off")
        async with self.make_script():
            await self.configure_script(**config)
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Run the script
            self.log.debug("Running the script")
            with pytest.raises(AssertionError):
                await self.run_script()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "park_calibration_projector.py"
        )
        await self.check_executable(script_path)

    if __name__ == "__main__":
        unittest.main()
