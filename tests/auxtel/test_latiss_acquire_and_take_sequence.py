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

__all__ = ["LatissAcquireAndTakeSequence"]

import random
import unittest
import asynctest
import logging

from lsst.ts import salobj
from lsst.ts import standardscripts
from lsst.ts import externalscripts
from lsst.ts.externalscripts.auxtel import LatissAcquireAndTakeSequence


random.seed(47)  # for set_random_lsst_dds_domain

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
logger.propagate = True
logger.level = logging.DEBUG


class TestLatissAcquireAndTakeSequence(
    standardscripts.BaseScriptTestCase, asynctest.TestCase
):
    async def basic_make_script(self, index):
        self.script = LatissAcquireAndTakeSequence(index=index)

        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            do_acquire = False
            do_take_sequence = True

            object_name = "HR8799"
            acq_filter = "acqfilter"
            acq_grating = "acqgrating"
            acq_exposure_time = 1
            max_acq_iter = 3
            target_pointing_tolerance = 5
            filter_sequence = "filter"
            grating_sequence = "grating"
            exposure_time_sequence = [1.0]
            #            dataPath = "/project/shared/auxTel/"
            dataPath = "/home/saluser/develop/ts_externalscripts/tests/data/auxtel/"

            await self.configure_script(
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                object_name=object_name,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                acq_exposure_time=acq_exposure_time,
                max_acq_iter=max_acq_iter,
                target_pointing_tolerance=target_pointing_tolerance,
                filter_sequence=filter_sequence,
                grating_sequence=grating_sequence,
                exposure_time_sequence=exposure_time_sequence,
                dataPath=dataPath,
            )
            # self.assertEqual(self.script.config.exp_times, [exp_times])
            # self.assertEqual(self.script.config.image_type, image_type)
            # self.assertIsNone(self.script.config.filter)

    # async def test_take_images(self):
    #     async with self.make_script():
    #         self.script.camera.take_imgtype = asynctest.CoroutineMock()
    #
    #         nimages = 5
    #
    #         await self.configure_script(
    #             nimages=nimages, exp_times=1.0, image_type="OBJECT", filter=1,
    #         )
    #
    #         await self.run_script()
    #
    #         self.assertEqual(nimages, self.script.camera.take_imgtype.await_count)

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_acquire_and_take_sequence.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
