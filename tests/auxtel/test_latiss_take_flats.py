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

__all__ = ["LatissTakeFlats"]

import asyncio
import logging
import os
import random
import tempfile
import unittest

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel import LatissTakeFlats
from lsst.utils import getPackageDir

random.seed(47)  # for set_random_lsst_dds_partition_prefix

logger = logging.getLogger(__name__)
logger.propagate = True


class TestLatissTakeFlats(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def tearDown(self) -> None:
        file_path = "/tmp/LatissTakeFlats/"
        if os.path.isdir(file_path):
            shutil.rmtree(file_path)

    def setUp(self) -> None:
        os.environ["LSST_SITE"] = "test"
        self.log = logging.getLogger(type(self).__name__)
        return super().setUp()

    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = LatissTakeFlats(index=index)

        # Mock the latiss instrument setups
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock(
            wraps=self.cmd_setup_atspec_callback
        )

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour
        self.atcamera = salobj.Controller(name="ATCamera")
        self.atcamera.cmd_takeImages.callback = unittest.mock.AsyncMock(
            wraps=self.cmd_take_flats_callback
        )

        self.atheaderservice = salobj.Controller(name="ATHeaderService")
        self.atoods = salobj.Controller(name="ATOODS")

        self.atspectrograph = salobj.Controller(name="ATSpectrograph")
        self.fiberspectrograph = salobj.Controller(name="FiberSpectrograph")
        self.atmonochromator = salobj.Controller(name="ATMonochromator")
        self.electrometer = salobj.Controller(name="Electrometer")

        # Mock electrometer functionality
        self.electrometer.cmd_performZeroCalib.callback = unittest.mock.AsyncMock()
        self.electrometer.cmd_setDigitalFilter.callback = unittest.mock.AsyncMock()

        # Mock atmonochromator functionality
        self.atmonochromator.cmd_selectGrating.callback = unittest.mock.AsyncMock()
        self.atmonochromator.cmd_changeWavelength.callback = unittest.mock.AsyncMock()
        self.atmonochromator.cmd_changeSlitWidth.callback = unittest.mock.AsyncMock()

        self.end_image_tasks = []

        # things to track
        self.nimages = 0
        self.date = None  # Used to fake dataId output from takeImages
        self.seq_num_start = None  # Used to fake proper dataId from takeImages

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def cmd_setup_atspec_callback(
        self, grating=None, filter=None, linear_stage=None
    ):

        list_to_be_returned = []
        if filter:
            list_to_be_returned.append(filter)
            await self.atspectrograph.evt_reportedFilterPosition.set_write(name=filter)
            self.atspectrograph.evt_filterInPosition.set()
            await self.ataos.evt_atspectrographCorrectionStarted.write()
            await asyncio.sleep(0.2)

        if grating:
            list_to_be_returned.append(filter)
            await self.atspectrograph.evt_reportedDisperserPosition.set_write(
                name=grating
            )
            self.atspectrograph.evt_disperserInPosition.set()
            await self.ataos.evt_atspectrographCorrectionStarted.write()
            await asyncio.sleep(0.2)

    async def cmd_setup_monochoromator_axes(
        self, grating=None, filter=None, linear_stage=None
    ):

        list_to_be_returned = []
        if filter:
            list_to_be_returned.append(filter)
            await self.atspectrograph.evt_reportedFilterPosition.set_write(name=filter)
            self.atspectrograph.evt_filterInPosition.set()
            await self.ataos.evt_atspectrographCorrectionStarted.write()
            await asyncio.sleep(0.2)

        if grating:
            list_to_be_returned.append(filter)
            await self.atspectrograph.evt_reportedDisperserPosition.set_write(
                name=grating
            )
            self.atspectrograph.evt_disperserInPosition.set()
            await self.ataos.evt_atspectrographCorrectionStarted.write()
            await asyncio.sleep(0.2)

        # need to return a list with how many parameters were provided

        return list_to_be_returned

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        logger.debug("Closing end_image_tasks")
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        logger.debug("Closing remotes")
        await asyncio.gather(
            self.atoods.close(),
            self.atcamera.close(),
            self.atspectrograph.close(),
            self.atmonochromator.close(),
            self.fiberspectrograph.close(),
            self.atheaderservice.close(),
        )
        logger.debug("Remotes closed")

    async def cmd_take_flats_callback(self, data):

        logger.debug(f"cmd_take_images callback came with data of {data}")
        one_exp_time = (
            data.expTime
            + self.script.latiss.read_out_time
            + self.script.latiss.shutter_time
        )
        logger.debug(
            f"Exposing for {one_exp_time} seconds for each exposure, total exposures is {data.numImages}"
        )
        await asyncio.sleep(one_exp_time * data.numImages)
        self.nimages += 1
        logger.debug("Scheduling finish_take_images before returning from take_images")
        self.end_image_tasks.append(asyncio.create_task(self.finish_take_images()))

    async def finish_take_images(self):

        # Give result that the telescope is ready
        await asyncio.sleep(0.5)
        imgNum = self.atcamera.cmd_takeImages.callback.await_count - 1
        image_name = f"AT_O_{self.date}_{(imgNum + self.seq_num_start):06d}"
        await self.atcamera.evt_endReadout.set_write(imageName=image_name)
        await asyncio.sleep(0.5)
        await self.atheaderservice.evt_largeFileObjectAvailable.write()
        await asyncio.sleep(1.0)
        await self.atoods.evt_imageInOODS.set_write(obsid=image_name)

    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            latiss_filter = "SDSSr_65mm"
            latiss_grating = "empty_1"
            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
            )

    async def test_invalid_sequence(self):
        # invalid filters, script should configure but die

        async with self.make_script():
            # Try configure with invalid sequence data. This should fail
            latiss_filter = "filter1"
            latiss_grating = "grating1"

            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
            )

            with pytest.raises(salobj.ExpectedError):
                await self.script.arun()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_take_flats.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
