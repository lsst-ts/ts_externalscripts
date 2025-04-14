# This file is part of ts_maintel_standardscripts
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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import random
import unittest

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.focus_telescope import FocusTelescope
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

random.seed(47)  # for set_random_lsst_dds_partition_prefix


class TestFocusTelescope(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = FocusTelescope(index=index)

        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )

        self.script._camera = LSSTCam(
            domain=self.script.domain,
            intended_usage=LSSTCamUsages.DryTest,
            log=self.script.log,
        )

        self.script.butler = unittest.mock.AsyncMock()

        # MTCS mocks
        self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.mtcs.offset_camera_hexapod = unittest.mock.AsyncMock()
        self.script.mtcs.disable_checks_for_components = unittest.mock.Mock()

        # MTAOS mocks
        self.script.mtcs.rem.mtaos = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtaos.configure_mock(
            **{
                "cmd_runWEP.set_start": unittest.mock.AsyncMock(),
                "evt_wavefrontError.flush": unittest.mock.AsyncMock(),
            }
        )
        self.script.compute_z_offset = self.compute_offset
        self.script.configure_butler = unittest.mock.AsyncMock()

        # Camera mocks
        self.script.camera.assert_all_enabled = unittest.mock.AsyncMock()
        self.script.camera.take_acq = self.take_image

        self.script.assert_mode_compatibility = unittest.mock.AsyncMock()

        return (self.script,)

    async def take_image(self, *args, **kwargs):
        return 1000

    async def compute_offset(self, *args, **kwargs):
        return 500.0

    async def test_configure(self):
        # Try configure with minimum set of parameters declared
        async with self.make_script():
            max_iter = 10
            exposure_time = 30.0
            filter = "r_57"
            threshold = 60.0

            await self.configure_script(
                max_iter=max_iter,
                exposure_time=exposure_time,
                filter=filter,
                threshold=threshold,
            )

            assert self.script.max_iter == max_iter
            assert self.script.exposure_time == exposure_time
            assert self.script.filter == filter
            assert self.script.threshold == threshold

    async def test_configure_ignore(self):
        async with self.make_script():
            ignore = ["mtdometrajectory", "no_comp"]

            await self.configure_script(filter="r", ignore=ignore)

            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=ignore
            )

    async def test_run(self):
        # Start the test itself
        async with self.make_script():
            await self.configure_script(
                max_iter=1,
                filter="r",
            )

            # Run the script
            await self.run_script()

            self.script.mtcs.offset_camera_hexapod.assert_awaited_once()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "focus_telescope.py"
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
