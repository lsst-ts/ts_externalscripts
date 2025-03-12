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

from lsst.ts import externalscripts, salobj, standardscripts, utils
from lsst.ts.externalscripts.maintel.park_calibration_projector import (
    ParkCalibrationProjector,
)
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys
from lsst.ts.xml.enums import Script

index_gen = utils.index_generator()


class TestSetupWhiteFlats(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    @property
    def remote_group(self) -> MTCalsys:
        """The remote_group property."""
        return self.mtcalsys

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make script")
        self.script = ParkCalibrationProjector(index=index)

        self.log.debug("Finished initializing from basic_make_script")
        return (self.script,)

    async def mock_calsys(self):
        """Mock Calsys CSCs"""

        self.script.linearstage_led_focus = unittest.mock.AsyncMock()
        self.script.linearstage_led_focus.evt_summaryState.aget = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.linearstage_led_focus.evt_summaryState.summaryState = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.linearstage_led_select = unittest.mock.AsyncMock()
        self.script.linearstage_led_select.evt_summaryState.aget = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.linearstage_led_select.evt_summaryState.summaryState = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.linearstage_projector_select = unittest.mock.AsyncMock()
        self.script.linearstage_projector_select.evt_summaryState.aget = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.linearstage_projector_select.evt_summaryState.summaryState = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.led_projector = unittest.mock.AsyncMock()
        self.script.led_projector.evt_summaryState.aget = unittest.mock.AsyncMock(
            return_value=salobj.State.ENABLED
        )
        self.script.led_projector.evt_summaryState.summaryState = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.mtcalsys.tunablelaser = unittest.mock.AsyncMock()
        self.script.mtcalsys.tunablelaser.evt_summaryState.aget = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )
        self.script.mtcalsys.tunablelaser.evt_summaryState.summaryState = (
            unittest.mock.AsyncMock(return_value=salobj.State.ENABLED)
        )

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script()
            assert self.script.state.state == Script.ScriptState.CONFIGURED

    async def test_run_without_failures(self):
        async with self.make_script():
            await self.configure_script()
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            self.log.debug("Starting Mtcalsys mocks")
            await self.mock_mtcalsys()
            await self.mock_calsys()

            self.log.debug("Enable all CSCs")

            # Run the script
            self.log.debug("Running the script")
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "park_calibration_projector.py"
        )
        await self.check_executable(script_path)

    if __name__ == "__main__":
        unittest.main()
