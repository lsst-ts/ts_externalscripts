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
import asyncio

from lsst.ts import salobj
from lsst.ts import standardscripts
from lsst.ts import externalscripts
from lsst.ts.externalscripts.auxtel import LatissAcquireAndTakeSequence
import lsst.daf.persistence as dafPersist

random.seed(47)  # for set_random_lsst_dds_domain

# Make matplotlib less chatty
logging.getLogger("matplotlib").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
logger.propagate = True

# Check to see if the test data is accessible for testing
# Depending upon how we load test data this will change
# for now just checking if butler is instantiated with
# the default path used on the summit and on the NTS.

DATAPATH = "/project/shared/auxTel/"
try:
    butler = dafPersist.Butler(DATAPATH)
    DATA_AVAILABLE = True
except RuntimeError:
    logger.warning("Data unavailable, certain tests will be skipped")
    DATA_AVAILABLE = False
    DATAPATH = "tests/data/auxtel/"
except PermissionError:
    logger.warning(
        "Data unavailable due to permissions (at a minimum),"
        " certain tests will be skipped"
    )
    DATA_AVAILABLE = False
    DATAPATH = "tests/data/auxtel/"


class TestLatissAcquireAndTakeSequence(
    standardscripts.BaseScriptTestCase, asynctest.TestCase
):
    async def basic_make_script(self, index):
        self.script = LatissAcquireAndTakeSequence(index=index)

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour

        self.atcamera = salobj.Controller(name="ATCamera")
        self.atcamera.cmd_takeImages.callback = asynctest.CoroutineMock(
            wraps=self.cmd_take_images_callback
        )

        # Mock the telescope slews and offsets
        self.script.atcs.slew_object = asynctest.CoroutineMock()
        self.script.atcs.offset_xy = asynctest.CoroutineMock()
        self.script.atcs.add_point_data = asynctest.CoroutineMock()

        # Mock the latiss instrument setups
        self.script.latiss.setup_atspec = asynctest.CoroutineMock(
            wraps=self.cmd_setup_atspec_callback
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
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        await asyncio.gather(
            self.atarchiver.close(),
            self.atcamera.close(),
            self.atspectrograph.close(),
            self.ataos.close(),
        )

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
            exposure_time_sequence = 1.0
            do_acquire = False
            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                do_acquire=do_acquire,
                dataPath=DATAPATH,
            )

            self.assertEqual(self.script.object_name, object_name)
            for i, v in enumerate(self.script.visit_configs):
                self.assertEqual(
                    self.script.visit_configs[i],
                    (filter_sequence, exposure_time_sequence, grating_sequence),
                )
            self.assertEqual(self.script.do_take_sequence, True)
            self.assertEqual(self.script.do_acquire, do_acquire)

            # Try configure with minimum set and multiple exposures
            exposure_time_sequence = [1.0, 2.0]

            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                dataPath=DATAPATH,
            )

            self.assertEqual(self.script.object_name, object_name)
            for i, v in enumerate(self.script.visit_configs):
                self.assertEqual(
                    self.script.visit_configs[i],
                    (filter_sequence, exposure_time_sequence[i], grating_sequence),
                )
            # Verify defaults
            self.assertEqual(self.script.do_take_sequence, True)
            self.assertEqual(self.script.do_acquire, True)

            # Try configure mis-matched array sizes. This should fail
            object_name = "HR8799"
            grating_sequence = ["test_disp1", "test_disp2"]
            exposure_time_sequence = [1.0, 2.0, 3.0]
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(
                    object_name=object_name,
                    grating_sequence=grating_sequence,
                    exposure_time_sequence=exposure_time_sequence,
                    dataPath=DATAPATH,
                )

            acq_filter = "acqfilter"
            acq_grating = "acqgrating"
            acq_exposure_time = 1
            max_acq_iter = 3
            target_pointing_tolerance = 3
            filter_sequence = ["test_filt1", "test_filt2"]
            grating_sequence = "test_disp1"
            exposure_time_sequence = [1.0, 2.0]

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
                dataPath=DATAPATH,
            )
            self.assertEqual(self.script.object_name, object_name)
            for i, v in enumerate(self.script.visit_configs):
                self.assertEqual(
                    self.script.visit_configs[i],
                    (filter_sequence[i], exposure_time_sequence[i], grating_sequence),
                )
            # Verify inputs
            self.assertEqual(self.script.do_take_sequence, True)
            self.assertEqual(self.script.do_acquire, True)

    @asynctest.skipIf(
        DATA_AVAILABLE is False,
        "Data not available for test_take_sequence, skipping.",
    )
    async def test_take_sequence(self):
        async with self.make_script():
            # Date for file to be produced
            self.date = "20200315"
            # sequence number start
            self.seq_num_start = 120
            object_name = "HR8799"
            grating_sequence = ["test_disp1", "test_disp2"]
            filter_sequence = ["test_filt1", "test_filt2"]
            exposure_time_sequence = [0.3, 0.8]
            do_acquire = False
            await self.configure_script(
                object_name=object_name,
                grating_sequence=grating_sequence,
                filter_sequence=filter_sequence,
                exposure_time_sequence=exposure_time_sequence,
                do_acquire=do_acquire,
                dataPath=DATAPATH,
            )

            # publish ataos event saying corrections are enabled
            self.ataos.evt_correctionEnabled.set_put(atspectrograph=True, hexapod=True)

            # Send spectrograph events
            logger.debug("Sending atspectrograph position events")
            self.atspectrograph.evt_reportedFilterPosition.set_put(name="filter0")
            self.atspectrograph.evt_reportedDisperserPosition.set_put(name="disp0")
            self.atspectrograph.evt_reportedLinearStagePosition.set_put(position=65)

            await self.run_script()

            self.assertEqual(
                self.atcamera.cmd_takeImages.callback.await_count,
                len(exposure_time_sequence),
            )
            # Check that appropriate filters/gratings were used
            for i, e in enumerate(exposure_time_sequence):
                # Inspection into the calls is cryptic. So leaving this as
                # multiple lines as it's easier to debug/understand
                # Note that each take_object command also calls setup_atspec,
                # but with no changes so we only every 2nd instance as
                # comparison
                called_filter = self.script.latiss.setup_atspec.call_args_list[2 * i][
                    1
                ]["filter"]
                called_grating = self.script.latiss.setup_atspec.call_args_list[2 * i][
                    1
                ]["grating"]
                self.assertEqual(filter_sequence[i], called_filter)
                self.assertEqual(grating_sequence[i], called_grating)
            # Verify the same group ID was used?

    @asynctest.skipIf(
        DATA_AVAILABLE is False,
        "Data not available for test_take_acquisition_pointing, skipping.",
    )
    async def test_take_acquisition_pointing(self):
        async with self.make_script():
            # Date for file to be produced
            self.date = "20200314"
            # sequence number start
            self.seq_num_start = 188

            object_name = "HD145600"
            acq_filter = "test_filt1"
            acq_grating = "empty_1"
            target_pointing_tolerance = 4
            max_acq_iter = 4
            do_acquire = True
            do_take_sequence = False
            do_pointing_model = True
            await self.configure_script(
                object_name=object_name,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                target_pointing_tolerance=target_pointing_tolerance,
                max_acq_iter=max_acq_iter,
                do_pointing_model=do_pointing_model,
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
            self.assertEqual(
                self.atcamera.cmd_takeImages.callback.await_count, 3,
            )
            # should offset only once
            self.assertEqual(self.script.atcs.offset_xy.call_count, 1)

    @asynctest.skipIf(
        DATA_AVAILABLE is False,
        "Data not available for test_take_acquisition_with_verification, skipping.",
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
            target_pointing_tolerance = 5
            max_acq_iter = 3
            do_acquire = True
            do_take_sequence = False
            do_pointing_model = False
            acq_exposure_time = 0.4
            target_pointing_verification = False
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
            self.assertEqual(
                self.atcamera.cmd_takeImages.callback.await_count, 3,
            )
            # should offset only once
            self.assertEqual(self.script.atcs.offset_xy.call_count, 2)

    @asynctest.skipIf(
        DATA_AVAILABLE is False,
        "Data not available for test_take_spectral_acquisition, skipping.",
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
            target_pointing_tolerance = 4
            max_acq_iter = 4
            do_acquire = True
            do_take_sequence = False
            target_pointing_verification = False
            await self.configure_script(
                object_name=object_name,
                do_acquire=do_acquire,
                do_take_sequence=do_take_sequence,
                acq_filter=acq_filter,
                acq_grating=acq_grating,
                target_pointing_tolerance=target_pointing_tolerance,
                max_acq_iter=max_acq_iter,
                target_pointing_verification=target_pointing_verification,
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
            self.assertEqual(
                self.atcamera.cmd_takeImages.callback.await_count, 2,
            )
            # should offset only once
            self.assertEqual(self.script.atcs.offset_xy.call_count, 1)

    @asynctest.skipIf(
        DATA_AVAILABLE is False, "Data not available for test_full_sequence, skipping."
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
            self.assertEqual(
                self.atcamera.cmd_takeImages.callback.await_count, 2 + 2,
            )
            # Make sure offset was applied to telescope
            self.script.atcs.offset_xy.assert_called()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_acquire_and_take_sequence.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
