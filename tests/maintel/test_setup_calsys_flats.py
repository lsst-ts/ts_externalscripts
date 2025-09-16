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

from lsst.ts import externalscripts, standardscripts, utils
from lsst.ts.externalscripts.maintel.setup_calsys_flats import SetupCalsysFlats
from lsst.ts.xml.enums import Script

index_gen = utils.index_generator()


class TestSetupCalsysFlats(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make script")
        self.script = SetupCalsysFlats(index=index)
        self.log.debug("Starting Mtcalsys mocks")
        await self.mock_mtcalsys()
        self.log.debug("Finished initializing from basic_make_script")
        return (self.script,)

    async def mock_mtcalsys(self):
        """Mock MTCalsys instance"""
        self.script.mtcalsys = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_liveliness = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_all_enabled = unittest.mock.AsyncMock()

        self.script.mtcalsys.start_task = utils.make_done_future()
        self.script.mtcalsys.load_calibration_config_file = unittest.mock.Mock()
        self.script.mtcalsys.assert_valid_configuration_option = unittest.mock.Mock()
        # Return a plain dict so no coroutine is left unawaited
        self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
            return_value={}
        )

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script(ignore=["TunableLaser"])
            assert self.script.state.state == Script.ScriptState.CONFIGURED
            assert self.script.sequence_name == "whitelight_u_source"

    async def test_run_without_failures(self):
        async with self.make_script():
            await self.configure_script(
                sequence_name="whitelight_u_source", ignore=["TunableLaser"]
            )
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Run the script
            self.log.debug("Running the script")
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        self.log.debug("Testing executable")
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(scripts_dir, "maintel", "setup_calsys_flats.py")
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
