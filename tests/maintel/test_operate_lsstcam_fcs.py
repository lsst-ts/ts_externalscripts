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
from lsst.ts.externalscripts.maintel import OperateLSSTCamFCS

logger = logging.getLogger(__name__)
logger.propagate = True


class TestOperateLSSTCamFCS(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = OperateLSSTCamFCS(index=index)

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    @unittest.mock.patch(
        "lsst.ts.standardscripts.BaseBlockScript.obs_id", "202306060001"
    )
    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            filter_list = ["ef_43", "ph_5"]
            n_changes = 6
            pause = 1
            seed = 35
            program = "BLOCK-123"
            reason = "SITCOM-321"

            self.script.get_obs_id = unittest.mock.AsyncMock(
                side_effect=["202306060001"]
            )

            await self.configure_script(
                filter_list = filter_list,
                n_changes = n_changes,
                pause = pause,
                seed = seed,
                program=program,
                reason=reason,
            )

            assert self.script.config.filter_list == filter_list
            assert self.script.config.n_changes == n_changes
            assert self.script.config.pause == pause
            assert self.script.config.seed == seed
            assert self.script.program == program
            assert self.script.reason == reason
            assert (
                self.script.checkpoint_message
                == "OperateLSSTCamFCS BLOCK-123 202306060001 SITCOM-321"
            )

    async def test_configure_invalid_program_name(self):
        async with self.make_script():
            filter_list = ["ef_43", "ph_5"]
            n_changes = 6
            pause = 1
            seed = 35
            program = "BLOCK_123"
            reason = "SITCOM-321"

            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(
                    filter_list = filter_list,
                    n_changes = n_changes,
                    pause = pause,
                    seed = seed,
                    program=program,
                    reason=reason,
                )

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "operate_lsstcam_fcs.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
