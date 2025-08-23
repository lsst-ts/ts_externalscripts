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
import unittest
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel import MakeLSSTCamCalibrations

logger = logging.getLogger(__name__)
logger.propagate = True


class TestMakeLSSTCamCalibrations(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = MakeLSSTCamCalibrations(index=index)
        self.script._lsstcam = unittest.mock.AsyncMock()
        self.script._ocps_group = unittest.mock.AsyncMock()

        self.script.mtcs = mock.MagicMock()
        self.script.mtcs.long_timeout = 30.0

        self.script.mtcs.check = mock.MagicMock()
        self.script.mtcs.check.mtdometrajectory = True
        self.script.mtcs.check.mtdome = True
        self.script.mtcs.check.mtmount = True
        self.script.mtcs.check.mtptg = True
        self.script.mtcs.check.mtaos = True
        self.script.mtcs.check.mtm1m3 = True
        self.script.mtcs.check.mtm2 = True
        self.script.mtcs.check.mthexapod_1 = True
        self.script.mtcs.check.mthexapod_2 = True
        self.script.mtcs.check.mtrotator = True

        # Create a proper MagicMock that can be asserted on
        self.script.mtcs.disable_checks_for_components = mock.MagicMock()

        self.script.mtcs.rem = mock.MagicMock()
        self.script.mtcs.rem.mtdometrajectory = mock.MagicMock()
        self.script.mtcs.rem.mtdome = mock.MagicMock()

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def _set_summary_states(self, dome_trajectory_state, dome_state):
        """Set up mock summary states for dome components"""
        self.script.mtcs.rem.mtdometrajectory.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": dome_trajectory_state})()
        )
        self.script.mtcs.rem.mtdome.evt_summaryState.aget = mock.AsyncMock(
            return_value=type("Evt", (), {"summaryState": dome_state})()
        )

    @unittest.mock.patch(
        "lsst.ts.standardscripts.BaseBlockScript.obs_id", "202306060001"
    )
    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            n_bias = 2
            n_dark = 2
            exp_times_dark = 10
            n_flat = 4
            exp_times_flat = [10, 10, 50, 50]
            detectors = [0, 1, 2, 3, 4, 5, 6, 7, 8]
            n_processes = 4
            program = "BLOCK-123"
            reason = "SITCOM-321"
            wait_between_exposures = 5
            script_mode = "BIAS_DARK_FLAT"

            self.script.get_obs_id = unittest.mock.AsyncMock(
                side_effect=["202306060001"]
            )

            await self.configure_script(
                n_bias=n_bias,
                n_dark=n_dark,
                n_flat=n_flat,
                exp_times_dark=exp_times_dark,
                exp_times_flat=exp_times_flat,
                detectors=detectors,
                n_processes=n_processes,
                program=program,
                reason=reason,
                wait_between_exposures=wait_between_exposures,
                script_mode=script_mode,
            )

            assert self.script.config.n_bias == n_bias
            assert self.script.config.n_dark == n_dark
            assert self.script.config.n_flat == n_flat
            assert self.script.config.exp_times_dark == exp_times_dark
            assert self.script.config.exp_times_flat == exp_times_flat
            assert self.script.config.n_processes == n_processes
            assert self.script.config.detectors == detectors
            assert self.script.program == program
            assert self.script.reason == reason
            assert self.script.config.wait_between_exposures == wait_between_exposures
            assert (
                self.script.checkpoint_message
                == "MakeLSSTCamCalibrations BLOCK-123 202306060001 SITCOM-321"
            )

    async def test_assert_feasibility_flat_ok(self):
        """Test that feasibility check passes when dome components are
        in correct states"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self._set_summary_states(salobj.State.ENABLED, salobj.State.DISABLED)

            await self.script.assert_feasibility("FLAT")

    async def test_assert_feasibility_flat_bad_dome_trajectory(self):
        """Test that feasibility check fails when MTDomeTrajectory is
        not ENABLED"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self._set_summary_states(salobj.State.DISABLED, salobj.State.DISABLED)

            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility("FLAT")

    async def test_assert_feasibility_flat_bad_dome(self):
        """Test that feasibility check fails when MTDome is in invalid state"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)

            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility("FLAT")

    async def test_assert_feasibility_non_flat(self):
        """Test that feasibility check does nothing for non-FLAT image types"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self.script.assert_feasibility("BIAS")

    async def test_configure_ignore(self):
        """Test that ignore functionality works correctly"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
                ignore=["mtmount", "mtptg"],
            )

            assert self.script.config.ignore == ["mtmount", "mtptg"]

    async def test_assert_feasibility_trajectory_and_dome_ignored(self):
        """Test that feasibility check passes when both dome components
        are ignored"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
                ignore=["mtdometrajectory", "mtdome"],
            )

            self.script.mtcs.check.mtdometrajectory = False
            self.script.mtcs.check.mtdome = False
            await self._set_summary_states(salobj.State.DISABLED, salobj.State.OFFLINE)

            await self.script.assert_feasibility("FLAT")

    async def test_assert_feasibility_trajectory_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDomeTrajectory is
        not ignored but in bad state"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self._set_summary_states(salobj.State.DISABLED, salobj.State.ENABLED)

            with pytest.raises(RuntimeError, match="MTDomeTrajectory must be ENABLED"):
                await self.script.assert_feasibility("FLAT")

    async def test_assert_feasibility_dome_not_ignored_bad_state(self):
        """Test that feasibility check fails when MTDome is not ignored
        but in bad state"""
        async with self.make_script():
            await self.configure_script(
                n_bias=1,
                n_dark=1,
                n_flat=1,
                exp_times_flat=1,
                script_mode="BIAS_DARK_FLAT",
            )

            await self._set_summary_states(salobj.State.ENABLED, salobj.State.OFFLINE)

            with pytest.raises(RuntimeError, match="MTDome must be in"):
                await self.script.assert_feasibility("FLAT")

    async def test_configure_invalid_program_name(self):
        async with self.make_script():
            n_bias = 2
            n_dark = 2
            exp_times_dark = 10
            n_flat = 4
            exp_times_flat = [10, 10, 50, 50]
            detectors = [0, 1, 2, 3, 4, 5, 6, 7, 8]
            n_processes = 4
            program = "BLOCK_123"
            reason = "SITCOM-321"

            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(
                    n_bias=n_bias,
                    n_dark=n_dark,
                    n_flat=n_flat,
                    exp_times_dark=exp_times_dark,
                    exp_times_flat=exp_times_flat,
                    detectors=detectors,
                    n_processes=n_processes,
                    program=program,
                    reason=reason,
                )

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "make_lsstcam_calibrations.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
