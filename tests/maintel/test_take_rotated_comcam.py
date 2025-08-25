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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import unittest

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel import TakeRotatedComCam
from lsst.ts.observatory.control.maintel.comcam import ComCam, ComCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.base_take_aos_sequence import Mode
from lsst.ts.xml.enums.ATPtg import WrapStrategy
from lsst.ts.xml.enums.Script import ScriptState


class TestTakeRotatedComCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeRotatedComCam(index=index)

        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )

        self.script._camera = ComCam(
            domain=self.script.domain,
            intended_usage=ComCamUsages.DryTest,
            log=self.script.log,
        )

        self.script.mtcs.slew_icrs = unittest.mock.AsyncMock()
        self.script.mtcs.wait_for_inposition = unittest.mock.AsyncMock()
        self.script.mtcs.assert_feasibility = unittest.mock.AsyncMock()
        self.script.mtcs.ready_to_take_data = unittest.mock.AsyncMock()
        self.script.mtcs.offset_camera_hexapod = unittest.mock.AsyncMock()
        self.script._camera.expose = unittest.mock.AsyncMock()
        self.script._camera.setup_instrument = unittest.mock.AsyncMock()
        self.script._camera.ready_to_take_data = unittest.mock.AsyncMock()
        self.script.take_aos_sequence = unittest.mock.AsyncMock()

        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            exposure_time = 15.0
            filter = "g"
            dz = 2000.0
            mode = "INTRA"
            angles = [0.0, 45.0, 90.0]
            target_name = "HD 185975"
            ra = "20:28:18.74"
            dec = "-87:28:19.9"
            slew_timeout = 300.0

            await self.configure_script(
                angles=angles,
                target_name=target_name,
                ra=ra,
                dec=dec,
                slew_timeout=slew_timeout,
                filter=filter,
                exposure_time=exposure_time,
                dz=dz,
                mode=mode,
            )
            assert self.script.exposure_time == exposure_time
            assert self.script.filter == filter
            assert self.script.dz == 2000.0
            assert self.script.mode == Mode.INTRA
            assert self.script.config.angles == angles
            assert self.script.config.target_name == target_name
            assert self.script.config.ra == ra
            assert self.script.config.dec == dec
            assert self.script.slew_timeout == slew_timeout

    async def test_run(self):
        async with self.make_script():
            exposure_time = 15.0
            filter = "g"
            dz = 2000.0
            mode = "TRIPLET"
            angles = [0.0, 45.0, 90.0]
            target_name = "HD 185975"
            ra = "20:28:18.74"
            dec = "-87:28:19.9"
            slew_timeout = 300.0

            await self.configure_script(
                angles=angles,
                target_name=target_name,
                ra=ra,
                dec=dec,
                slew_timeout=slew_timeout,
                filter=filter,
                exposure_time=exposure_time,
                dz=dz,
                mode=mode,
            )

            await self.run_script()

            self.assertEqual(self.script.state.state, ScriptState.DONE)

            expected_slew_calls = len(angles)
            expected_take_sequence_calls = len(angles)

            self.assertEqual(
                self.script.mtcs.slew_icrs.await_count,
                expected_slew_calls,
                f"slew_icrs was called {self.script.mtcs.slew_icrs.await_count} times, "
                f"expected {expected_slew_calls}",
            )

            self.assertEqual(
                self.script.take_aos_sequence.await_count,
                expected_take_sequence_calls,
                f"take_aos_sequence was called {self.script.take_aos_sequence.await_count} times, "
                f"expected {expected_take_sequence_calls}",
            )

            for call_args in self.script.mtcs.slew_icrs.await_args_list:
                called_args, called_kwargs = call_args
                self.assertEqual(called_kwargs["ra"], ra)
                self.assertEqual(called_kwargs["dec"], dec)
                self.assertEqual(called_kwargs["rot_type"], RotType.Physical)
                self.assertEqual(called_kwargs["target_name"], target_name)
                self.assertIn(called_kwargs["rot"], angles)
                self.assertEqual(
                    called_kwargs["az_wrap_strategy"], WrapStrategy.NOUNWRAP
                )

    async def test_executable_comcam_script(self) -> None:
        """Test that the script is executable."""
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_rotated_comcam.py"
        await self.check_executable(script_path)

    async def test_executable_lsstcam_script(self) -> None:
        """Test that the script is executable."""
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_rotated_lsstcam.py"
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
