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
import asyncio
import tempfile
import os

import pytest

from lsst.ts import salobj

# from lsst.ts.utils import make_done_future
from lsst.ts import standardscripts
from lsst.ts import externalscripts
from lsst.ts.externalscripts.auxtel import LatissAcquireAndTakeSequence
import lsst.daf.butler as dafButler
from lsst.utils import getPackageDir

import logging

# Make matplotlib less chatty
logging.getLogger("matplotlib").setLevel(logging.WARNING)

random.seed(47)  # for set_random_lsst_dds_partition_prefix


logger = logging.getLogger(__name__)
logger.propagate = True

# Check to see if the test data is accessible for testing
# Depending upon how we load test data this will change
# for now just checking if butler is instantiated with
# the default path used on the summit and on the NTS.

# DATAPATH set to NTS repo
# DATAPATH = "/readonly/repo/main" # obselete
DATAPATH = "/repo/LATISS"  # summit (careful!)

try:
    butler = dafButler.Butler(
        DATAPATH, instrument="LATISS", collections="LATISS/raw/all"
    )
    DATA_AVAILABLE = True
except FileNotFoundError:
    logger.warning("Data unavailable, certain tests will be skipped")
    DATA_AVAILABLE = False

    DATAPATH = (tempfile.TemporaryDirectory(prefix="butler-repo")).name
    butler_config_path = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
        "butler_seed.yaml",
    )
    dafButler.Butler(
        dafButler.Butler.makeRepo(DATAPATH, config=butler_config_path), writeable=True
    )

except PermissionError:
    logger.warning(
        "Data unavailable due to permissions (at a minimum),"
        " certain tests will be skipped"
    )
    DATA_AVAILABLE = False
    DATAPATH = (tempfile.TemporaryDirectory(prefix="butler-repo")).name
    butler_config_path = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
        "butler_seed.yaml",
    )
    dafButler.Butler(
        dafButler.Butler.makeRepo(DATAPATH, config=butler_config_path), writeable=True
    )


class TestLatissAcquireAndTakeSequence(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = LatissAcquireAndTakeSequence(index=index)

        # Mock the telescope slews and offsets
        self.script.atcs.slew_object = unittest.mock.AsyncMock()
        self.script.atcs.slew_icrs = unittest.mock.AsyncMock()
        self.script.atcs.offset_xy = unittest.mock.AsyncMock()
        self.script.atcs.add_point_data = unittest.mock.AsyncMock()
        self.script.latiss.ready_to_take_data = None  # make_done_future()

        # Mock the latiss instrument setups
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock(
            wraps=self.cmd_setup_atspec_callback
        )

        # Mock method that returns the BestEffortIsr class if it is
        # not available for import
        if not DATA_AVAILABLE:
            self.script.get_best_effort_isr = unittest.mock.Mock()

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour
        self.atcamera = salobj.Controller(name="ATCamera")
        self.atcamera.cmd_takeImages.callback = unittest.mock.AsyncMock(
            wraps=self.cmd_take_images_callback
        )

        self.atheaderservice = salobj.Controller(name="ATHeaderService")
        self.atarchiver = salobj.Controller(name="ATArchiver")
        # Need ataos as the script waits for corrections to be applied on
        # grating/filter changes
        self.ataos = salobj.Controller(name="ATAOS")

        self.atspectrograph = salobj.Controller(name="ATSpectrograph")

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
            self.atspectrograph.evt_reportedFilterPosition.set_put(name=filter)
            self.atspectrograph.evt_filterInPosition.set()
            self.ataos.evt_atspectrographCorrectionStarted.put()
            await asyncio.sleep(0.2)
            self.ataos.evt_atspectrographCorrectionCompleted.put()
            # Publish AOS correction events
            self.ataos.evt_atspectrographCorrectionStarted.put()
            await asyncio.sleep(0.2)
            self.ataos.evt_atspectrographCorrectionCompleted.put()
            await asyncio.sleep(0.2)

        if grating:
            list_to_be_returned.append(filter)
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name=grating)
            self.atspectrograph.evt_disperserInPosition.set()
            self.ataos.evt_atspectrographCorrectionStarted.put()
            await asyncio.sleep(0.5)
            self.ataos.evt_atspectrographCorrectionCompleted.put()
            # Publish AOS correction events
            self.ataos.evt_atspectrographCorrectionStarted.put()
            await asyncio.sleep(0.2)
            self.ataos.evt_atspectrographCorrectionCompleted.put()
            await asyncio.sleep(0.2)

        # need to return a list with how many parameters were provided

        return list_to_be_returned

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        logger.debug("Closing end_image_tasks")
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        logger.debug("Closing remotes")
        await asyncio.gather(
            self.atarchiver.close(),
            self.atcamera.close(),
            self.atspectrograph.close(),
            self.ataos.close(),
            self.atheaderservice.close(),
        )
        logger.debug("Remotes closed")

    async def cmd_take_images_callback(self, data):

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
        self.atcamera.evt_endReadout.set_put(imageName=image_name)
        await asyncio.sleep(0.5)
        self.atheaderservice.evt_largeFileObjectAvailable.put()
        await asyncio.sleep(1.0)
        self.atarchiver.evt_imageInOODS.set_put(obsid=image_name)

    async def test_configure(self):
        async with self.make_script():

            # Try configure with minimum set of parameters declared
            # Also skip acquisition
            # Note that all are scalars and should be converted to arrays
            object_name = "HR8799"
            grating_sequence = "test_disp1"
            filter_sequence = "test_filt1"
            reason = "test"
            program = "test_program"
            exposure_time_sequence = 1.0
            do_acquire = False
            do_take_sequence = True
            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            assert self.script.object_name == object_name
            for i, v in enumerate(self.script.visit_configs):
                assert self.script.visit_configs[i] == (
                    filter_sequence,
                    exposure_time_sequence,
                    grating_sequence,
                )
            assert self.script.do_take_sequence is True
            assert self.script.do_acquire == do_acquire

            # Try configure with minimum set and multiple exposures
            exposure_time_sequence = [1.0, 2.0]

            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            assert self.script.object_name == object_name
            for i, v in enumerate(self.script.visit_configs):
                assert self.script.visit_configs[i] == (
                    filter_sequence,
                    exposure_time_sequence[i],
                    grating_sequence,
                )
            # Verify defaults
            assert self.script.do_take_sequence is True
            assert self.script.do_acquire is False

            # Try configure mis-matched array sizes. This should fail
            object_name = "HR8799"
            grating_sequence = ["test_disp1", "test_disp2"]
            exposure_time_sequence = [1.0, 2.0, 3.0]
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(
                    object_name=object_name,
                    grating_sequence=grating_sequence,
                    exposure_time_sequence=exposure_time_sequence,
                    do_acquire=do_acquire,
                    do_take_sequence=do_take_sequence,
                    datapath=DATAPATH,
                    reason=reason,
                    program=program,
                )

            acq_filter = "acqfilter"
            acq_grating = "acqgrating"
            acq_exposure_time = 10
            max_acq_iter = 3
            target_pointing_tolerance = 3
            filter_sequence = ["test_filt1", "test_filt2"]
            grating_sequence = "test_disp1"
            exposure_time_sequence = [20.0, 60.0]

            # Try configure will all parameters declared
            await self.configure_script(
                do_acquire=True,
                do_take_sequence=True,
                object_name=object_name,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                acq_exposure_time=acq_exposure_time,
                max_acq_iter=max_acq_iter,
                target_pointing_tolerance=target_pointing_tolerance,
                filter_sequence=filter_sequence,
                grating_sequence=grating_sequence,
                exposure_time_sequence=exposure_time_sequence,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )
            assert self.script.object_name == object_name
            for i, v in enumerate(self.script.visit_configs):
                assert self.script.visit_configs[i] == (
                    filter_sequence[i],
                    exposure_time_sequence[i],
                    grating_sequence,
                )
            # Verify inputs
            assert self.script.do_take_sequence is True
            assert self.script.do_acquire is True
            assert self.script.time_on_target >= acq_exposure_time + sum(
                exposure_time_sequence
            )

    @unittest.skipIf(
        DATA_AVAILABLE is False,
        f"Data availability is {DATA_AVAILABLE}. Skipping test_take_sequence.",
    )
    async def test_take_sequence(self):
        async with self.make_script():
            logger.info("Starting test_take_sequence")
            # Date for file to be produced
            self.date = "20200315"
            # sequence number start
            self.seq_num_start = 120
            object_name = "HR8799"
            grating_sequence = ["test_disp1", "test_disp2"]
            filter_sequence = ["test_filt1", "test_filt2"]
            reason = "test"
            program = "test_program"
            exposure_time_sequence = [0.3, 0.8]
            do_acquire = False
            do_take_sequence = True
            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            assert self.atcamera.cmd_takeImages.callback.await_count == len(
                exposure_time_sequence
            )
            # Check that appropriate filters/gratings were used
            for i, e in enumerate(exposure_time_sequence):
                # Inspection into the calls is cryptic. So leaving this as
                # multiple lines as it's easier to debug/understand
                called_filter = self.script.latiss.setup_atspec.call_args_list[i][1][
                    "filter"
                ]
                called_grating = self.script.latiss.setup_atspec.call_args_list[i][1][
                    "grating"
                ]
                assert filter_sequence[i] == called_filter
                assert grating_sequence[i] == called_grating

    @unittest.skipIf(
        DATA_AVAILABLE is False,
        f"Data availability is {DATA_AVAILABLE}."
        f"Skipping test_take_acquisition_pointing.",
    )
    async def test_take_acquisition_pointing(self):
        async with self.make_script():
            # Date for file to be produced
            self.date = "20200314"
            # sequence number start
            self.seq_num_start = 188

            object_name = "HD145600"
            object_ra = "16 14 33.9"
            object_dec = "-53 33 35.2"
            acq_filter = "test_filt1"
            acq_grating = "empty_1"
            target_pointing_tolerance = 4
            max_acq_iter = 4
            do_acquire = True
            do_take_sequence = False
            do_pointing_model = True
            reason = "test"
            program = "test_program"
            await self.configure_script(
                object_name=object_name,
                object_ra=object_ra,
                object_dec=object_dec,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                target_pointing_tolerance=target_pointing_tolerance,
                max_acq_iter=max_acq_iter,
                do_pointing_model=do_pointing_model,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            # img 188 centroid at 1572, 1580
            # img 189 centroid at 2080, 1997
            # img 190 centroid at 2041, 2019
            # img 191 and 192 centroid at 2040, 1995

            # Should take two iterations? FIXME
            assert self.atcamera.cmd_takeImages.callback.await_count == 3
            # should offset only once
            assert self.script.atcs.offset_xy.call_count == 1

    @unittest.skipIf(
        DATA_AVAILABLE is False,
        f"Data availibility is {DATA_AVAILABLE}."
        f"Skipping test_take_acquisition_with_verification.",
    )
    async def test_take_acquisition_with_verification(self):
        async with self.make_script():
            # Date for file to be produced
            self.date = "20210217"
            # sequence number start
            self.seq_num_start = 325

            object_name = "HD 60753"
            acq_filter = "test_filt1"
            acq_grating = "empty_1"
            target_pointing_tolerance = 6
            max_acq_iter = 3
            do_acquire = True
            do_take_sequence = False
            do_pointing_model = False
            acq_exposure_time = 0.4
            target_pointing_verification = False
            reason = "test"
            program = "test_program"
            await self.configure_script(
                object_name=object_name,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                target_pointing_tolerance=target_pointing_tolerance,
                max_acq_iter=max_acq_iter,
                do_pointing_model=do_pointing_model,
                acq_exposure_time=acq_exposure_time,
                target_pointing_verification=target_pointing_verification,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            # img 268 1636,1865
            # img 291 centroid at 972,1671 (good)

            # Should take two iterations and 3 images
            assert self.atcamera.cmd_takeImages.callback.await_count == 3
            # should offset only once
            assert self.script.atcs.offset_xy.call_count == 2

    @unittest.skipIf(
        DATA_AVAILABLE is False,
        f"Data availibility is {DATA_AVAILABLE}."
        f"Skipping test_take_acquisition_nominal.",
    )
    async def test_take_acquisition_nominal(self):
        # nominal case where no verification is taken, no pointing is done
        async with self.make_script():
            # Date for file to be produced
            self.date = "20210121"
            # sequence number start
            self.seq_num_start = 739

            object_name = "HD 185975"
            acq_filter = "test_filt1"
            acq_grating = "empty_1"
            target_pointing_tolerance = 5
            max_acq_iter = 4
            do_acquire = True
            do_take_sequence = False
            target_pointing_verification = False
            reason = "test"
            program = "test_program"
            await self.configure_script(
                object_name=object_name,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                target_pointing_tolerance=target_pointing_tolerance,
                max_acq_iter=max_acq_iter,
                target_pointing_verification=target_pointing_verification,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            # img 188 centroid at 1572, 1580
            # img 189 centroid at 2080, 1997
            # img 190 centroid at 2041, 2019
            # img 191 and 192 centroid at 2040, 1995

            # Should take two iterations
            assert self.atcamera.cmd_takeImages.callback.await_count == 2
            # should offset only once
            assert self.script.atcs.offset_xy.call_count == 1

    @unittest.skipIf(
        DATA_AVAILABLE is False,
        f"Data availibility is {DATA_AVAILABLE}. Skipping test_full_sequence.",
    )
    async def test_full_sequence(self):
        """This tests a combined acquisition and data taking sequence.
        It uses a single acquisition image without re-verification."""

        async with self.make_script():
            # Date for file to be produced
            self.date = "20210121"
            # sequence number start
            self.seq_num_start = 739

            object_name = "HD145600"
            acq_filter = "test_filt1"
            acq_grating = "ronchi90lpmm"
            grating_sequence = ["ronchi90lpmm", "empty_1"]
            filter_sequence = "test_filt2"
            exposure_time_sequence = [0.3, 0.8]
            target_pointing_tolerance = 5
            target_pointing_verification = False
            do_acquire = True
            do_take_sequence = True
            reason = "test"
            program = "test_program"
            await self.configure_script(
                object_name=object_name,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                filter_sequence=filter_sequence,
                grating_sequence=grating_sequence,
                target_pointing_tolerance=target_pointing_tolerance,
                exposure_time_sequence=exposure_time_sequence,
                target_pointing_verification=target_pointing_verification,
                datapath=DATAPATH,
                reason=reason,
                program=program,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            # Should take two images for acquisition then two images
            assert self.atcamera.cmd_takeImages.callback.await_count == 2 + 2
            # Make sure offset was applied to telescope
            self.script.atcs.offset_xy.assert_called()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_acquire_and_take_sequence.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
