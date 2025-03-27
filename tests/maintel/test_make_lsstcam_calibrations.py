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

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

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
