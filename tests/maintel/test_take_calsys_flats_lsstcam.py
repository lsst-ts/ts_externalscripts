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
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts, utils
from lsst.ts.externalscripts.maintel.take_calsys_flats_lsstcam import (
    TakeCalsysFlatsLSSTCam,
)


class TestTakeCalsysFlatsLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.script = TakeCalsysFlatsLSSTCam(index=index)

        self.script.mtcs = mock.AsyncMock()
        self.script.mtcs.long_timeout = 30.0
        self.script.mtcs.rem = mock.MagicMock()
        self.script.mtcs.rem.mtdometrajectory = mock.MagicMock()
        self.script.mtcs.rem.mtdome = mock.MagicMock()

        self.mock_mtcalsys()
        self.mock_camera()

        return (self.script,)

    def mock_mtcalsys(self):
        """Mock MTCalsys instance"""
        self.script.mtcalsys = unittest.mock.AsyncMock()
        self.script.mtcalsys.start_task = utils.make_done_future()
        self.script.mtcalsys.load_calibration_config_file = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_valid_configuration_option = (
            unittest.mock.AsyncMock()
        )
        self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
            return_value={
                "mtcamera_filter": "r_57",
                "exposure_times": [15.0],
                "calib_type": "WhiteLight",
                "n_flat": 20,
            }
        )
        self.script.mtcalsys.run_calibration_sequence = unittest.mock.AsyncMock(
            side_effect=[
                {"sequence_id": 1, "duration": 10},
                {"sequence_id": 2, "duration": 12},
            ]
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()

    async def _inject_mtcs_check_mocks(self):
        """Mock the .check attribute of mtcs for ignore functionality"""
        self.script.mtcs.check = mock.MagicMock()
        self.script.mtcs.check.mtdometrajectory = True
        self.script.mtcs.check.mtdome = True

    async def _set_summary_states(self, trajectory_state, dome_state):
        """Set up mock summary states for dome components"""
        self.script.mtcs.rem.mtdometrajectory.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": trajectory_state})()
        )
        self.script.mtcs.rem.mtdome.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": dome_state})()
        )

    async def test_configure(self):
        config = {
            "sequence_names": ["whitelight_r_57_dark"],
            "use_camera": True,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.sequence_names == ["whitelight_r_57_dark"]
            assert self.script.use_camera

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "filter": "whitelight_led",
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_take_whitelight_flats(self):
        config = {
            "sequence_names": ["whitelight_z_20_dark"],
            "config_tcs": False,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

    async def test_take_whitelight_flats_with_tcs(self):
        """Test whitelight flats with TCS configured and feasibility
        checks enabled"""
        config = {
            "sequence_names": ["whitelight_z_20_dark"],
            "config_tcs": True,
        }

        async with self.make_script():
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.DISABLED)
            await self.configure_script(**config)
            await self.run_script()

    async def test_take_whitelight_source(self):
        config = {
            "sequence_names": ["whitelight_r_source"],
            "use_camera": False,
            "config_tcs": False,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            assert not self.script.use_camera

    async def test_update_ptc_random_seed(self):
        config = {
            "sequence_names": ["ptc_daily_test"],
            "use_camera": False,
            "config_tcs": False,
            "random_seed": 9999,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            assert not self.script.use_camera

    async def test_update_ptc_start_idx(self):
        config = {
            "sequence_names": ["ptc_daily_test"],
            "use_camera": False,
            "config_tcs": False,
            "exp_list_start_idx": 100,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            assert not self.script.use_camera

    async def test_make_daily_cals(self):
        config = {
            "sequence_names": ["daily"],
        }

        async with self.make_script():
            self.script.lsstcam.get_available_filters = unittest.mock.AsyncMock(
                return_value=["u_24,g_6,r_57,i_39,z_20"]
            )
            await self.configure_script(**config)

            assert self.script.sequence_names == [
                "whitelight_u_24_daily",
                "whitelight_g_6_daily",
                "whitelight_r_57_daily",
                "whitelight_i_39_daily",
                "whitelight_z_20_daily",
            ]

    async def test_assert_feasibility_ok(self):
        """Test that feasibility check passes when dome components are in
        correct states"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=True
            )
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.DISABLED)
            await self.script.assert_feasibility()

    async def test_assert_feasibility_bad_trajectory(self):
        """Test that feasibility check fails when MTDomeTrajectory is not
        ENABLED"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=True
            )
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.ENABLED)
            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_bad_dome(self):
        """Test that feasibility check fails when MTDome is in invalid
        state"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=True
            )
            await self._inject_mtcs_check_mocks()
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_trajectory_and_dome_ignored(self):
        """Test that feasibility check passes when both dome components
        are ignored"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"],
                config_tcs=True,
                ignore=["mtdometrajectory", "mtdome"],
            )
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = False
            self.script.mtcs.check.mtdome = False
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.OFFLINE)
            await self.script.assert_feasibility()

    async def test_assert_feasibility_trajectory_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDomeTrajectory is
        not ignored but in bad state"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=True
            )
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = True
            self.script.mtcs.check.mtdome = False
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_dome_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDome is not ignored
        but in bad state"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=True
            )
            await self._inject_mtcs_check_mocks()
            self.script.mtcs.check.mtdometrajectory = False
            self.script.mtcs.check.mtdome = True
            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)
            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility()

    async def test_assert_feasibility_no_tcs(self):
        """Test that feasibility check does nothing when config_tcs is False"""
        async with self.make_script():
            await self.configure_script(
                sequence_names=["whitelight_r_57_dark"], config_tcs=False
            )
            await self.script.assert_feasibility()

    async def test_configure_ignore(self):
        """Test that ignore functionality works correctly in configure"""
        async with self.make_script():
            self.script.mtcs.disable_checks_for_components = mock.MagicMock()

            config = type(
                "Config",
                (),
                {
                    "sequence_names": ["whitelight_r_57_dark"],
                    "use_camera": True,
                    "config_tcs": True,
                    "random_seed": None,
                    "exp_list_start_idx": None,
                    "ignore": ["mtmount", "mtptg"],
                },
            )()
            await self.script.configure(config)

            self.script.mtcs.disable_checks_for_components.assert_any_call(
                components=["mtmount", "mtptg"]
            )

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "take_calsys_flats_lsstcam.py"
        )
        await self.check_executable(script_path)
