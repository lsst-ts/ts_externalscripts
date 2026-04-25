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
from lsst.ts.externalscripts.maintel.perform_cbp_cal_copointing_dance import (
    PerformCBPCalCopointingDance,
)

index_gen = utils.index_generator()


class TestPerformCBPCalCopointingDance(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.script = PerformCBPCalCopointingDance(index=index)

        self.mock_mtcalsys()

        return (self.script,)

    async def mock_mtcalsys(self):
        """Mock Calsys CSCs"""
        self.script.mtcalsys = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcalsys.get_projector_setup = unittest.mock.AsyncMock(
            return_value=self.projector_setup
        )
        self.script.mtcalsys.led_rest_position = 100.0
        self.script.mtcalsys.linearstage_projector_pos_tolerance = 0.2

    async def test_executable(self):
        self.log.debug("Testing executable")
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "perform_cbp_cal_copointing_dance.py"
        )
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
