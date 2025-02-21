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
import random
import types
import unittest
import warnings

from lsst.ts import salobj, standardscripts, utils
from lsst.ts.externalscripts.maintel.setup_whitelight_flats import SetupWhiteFlats


class TestSetupWhiteFlats(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = SetupWhiteFlats(index=index)

        self.mock_mtcalsys()

        return [
            self.script,
        ]

    async def mock_mtcalsys(self):
        """Mock MTCalsys instance"""
        self.script.mtcalsys = unittest.mock.MagicMock()
        self.script.mtcalsys.assert_liveliness = mock.AsyncMock()
        self.script.mtcalsys.assert_all_enabled = mock.AsyncMock()

        self.script.mtcalsys.start_task = utils.make_done_future()
        self.script.mtcalsys.load_calibration_config_file = unittest.mock.MagicMock()
        self.script.mtcalsys.assert_valid_configuration_option = (
            unittest.mock.MagicMock()
        )

    async def test_configure(self):
        async with self.make_script():

            await self.configure_script()

    async def test_run_without_failures(self):
        async with self.make_script():
            await self.configure_script()

            await self.run_script()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "setup_whitelight_flats.py"
        )
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
