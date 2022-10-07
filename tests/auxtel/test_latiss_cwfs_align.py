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

import asyncio
import os
import unittest
import warnings

import numpy as np
import pytest

try:
    from lsst import cwfs

    CWFS_AVAILABLE = True
except ImportError:
    CWFS_AVAILABLE = False
    warnings.warn("Could not import cwfs package. Most tests will be skipped.")

import logging

import lsst.daf.butler as dafButler
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel import LatissCWFSAlign
from lsst.utils import getPackageDir

# Make matplotlib less chatty
logging.getLogger("matplotlib").setLevel(logging.WARNING)
# Make obslsst translators less chatty
logging.getLogger("lsst.obs.lsst.translators").setLevel(logging.WARNING)
logging.getLogger("astro_metadata_translator").setLevel(logging.WARNING)
logging.getLogger("flake8.style_guide").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)
logger.propagate = True

# Check to see if the test data is accessible for testing. Depending upon how
# we load test data this will change the tests that are executed. For now just
# checking if butler is instantiated with the default path used on the summit
# and on the test stands.

DATAPATH = "/repo/LATISS"  # Same value for SUMMIT and test stands

try:
    butler = dafButler.Butler(
        DATAPATH,
        instrument="LATISS",
        collections=["LATISS/raw/all", "LATISS_test_data"],
    )
    DATA_AVAILABLE = True
except FileNotFoundError:
    warnings.warn("Data unavailable, certain tests will be skipped")
    DATA_AVAILABLE = False
    DATAPATH = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
    )
except PermissionError:
    warnings.warn(
        "Data unavailable due to permissions (at a minimum),"
        " certain tests will be skipped"
    )
    DATA_AVAILABLE = False
    DATAPATH = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
    )


class TestLatissCWFSAlign(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = LatissCWFSAlign(index=index, remotes=True)

        self.visit_id_angles = {}
        self.end_image_tasks = []
        self.img_cnt_override_list = None

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour

        self.atcamera = salobj.Controller(name="ATCamera")
        self.atheaderservice = salobj.Controller(name="ATHeaderService")
        self.atoods = salobj.Controller(name="ATOODS")
        self.ataos = salobj.Controller(name="ATAOS")
        self.athexapod = salobj.Controller(name="ATHexapod")
        self.atptg = salobj.Controller(name="ATPtg")
        self.atmcs = salobj.Controller(name="ATMCS")

        # Create mocks
        self.atcamera.cmd_takeImages.callback = unittest.mock.AsyncMock(
            wraps=self.cmd_take_images_callback
        )
        self.script.latiss.ready_to_take_data = unittest.mock.AsyncMock(
            return_value=True
        )
        # mock latiss instrument setup
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock()

        self.ataos.cmd_offset.callback = unittest.mock.AsyncMock(
            wraps=self.ataos_cmd_offset_callback
        )
        self.script.atcs.offset_xy = unittest.mock.AsyncMock()
        self.script.atcs.add_point_data = unittest.mock.AsyncMock()
        # callback for boresight angle
        self.script.atcs.get_bore_sight_angle = unittest.mock.AsyncMock(
            wraps=self.atcs_get_bore_sight_angle
        )

        # Mock method that returns the BestEffortIsr class if it is
        # not available for import
        if not DATA_AVAILABLE:
            self.script.get_best_effort_isr = unittest.mock.AsyncMock()

        # things to track
        self.nimages = 0
        self.date = None  # Used to fake dataId output from takeImages
        self.seq_num_start = None  # Used to fake proper dataId from takeImages

        # Return a single element tuple
        return (self.script,)

    async def ataos_cmd_offset_callback(self, data):
        """Publishes event from hexapod saying movement completed.
        Also flips the ataos detailed state"""
        logger.debug("Sending hexapod events and ataos events")

        ss_idle = np.uint8(0)
        ss_hexapod = np.uint8(1 << 3)  # Hexapod correction running
        # FOCUS = np.uint8(1 << 4)  # Focus correction running

        await self.ataos.evt_detailedState.set_write(
            substate=ss_hexapod, force_output=True
        )
        await self.athexapod.evt_positionUpdate.write()
        await self.athexapod.tel_positionStatus.write()
        await self.ataos.evt_detailedState.set_write(
            substate=ss_idle, force_output=True
        )
        return

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        logger.debug("Closing Remotes")
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        await asyncio.gather(
            self.atoods.close(),
            self.atcamera.close(),
            self.atheaderservice.close(),
            self.ataos.close(),
            self.athexapod.close(),
            self.atptg.close(),
            self.atmcs.close(),
        )
        logger.debug("Remotes Closed")

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
        # Allow an override of image numbers incase the test datasets are
        # non-sequential
        if not self.img_cnt_override_list:
            imgNum = self.atcamera.cmd_takeImages.callback.await_count - 1
            image_name = f"AT_O_{self.date}_{(imgNum + self.seq_num_start):06d}"
        else:
            logger.debug("Mock camera using override list")
            imgNum = self.img_cnt_override_list[
                self.atcamera.cmd_takeImages.callback.await_count - 1
            ]
            image_name = f"AT_O_{self.date}_{(imgNum):06d}"

        logger.debug(f"Mock camera returning imageName={image_name}")
        await self.atcamera.evt_endReadout.set_write(imageName=image_name)
        await asyncio.sleep(0.5)
        await self.atheaderservice.evt_largeFileObjectAvailable.write()
        await asyncio.sleep(1.0)
        await self.atoods.evt_imageInOODS.set_write(obsid=image_name)

    async def configure_script(self, **kwargs):
        await super().configure_script(**kwargs)

        await self.script._configure_target()

    @unittest.skipIf(
        CWFS_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}. Skipping test_configure.",
    )
    async def test_configure(self):
        async with self.make_script():
            # First make sure the cwfs package is present
            assert os.path.exists(cwfs.__file__)
            # Try configure with minimum set of parameters declared
            grating = "test_disp1"
            filter = "test_filt1"
            exposure_time = 1.0
            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
            )

            assert self.script.filter == filter
            assert self.script.grating == grating
            assert self.script.exposure_time == exposure_time
            assert self.script.cwfs_target is None
            assert self.script.cwfs_target_ra is None
            assert self.script.cwfs_target_dec is None

            # Test with find_target
            # this can fail occasionally if you're unlucky and
            # don't get a target so the mag_range is large to
            # prevent this
            find_target = dict(az=-180.0, el=60.0, mag_limit=6.0, mag_range=14)
            await self.configure_script(find_target=find_target)

            assert self.script.cwfs_target is not None
            assert self.script.cwfs_target_ra is None
            assert self.script.cwfs_target_dec is None

            # Test with find_target; fail if only az is provided
            find_target = dict(az=0.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with find_target; fail if only el is provided
            find_target = dict(el=60.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with find_target; fail if only az and el is provided
            find_target = dict(az=0.0, el=60.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with track_target; give target name only
            track_target = dict(target_name="HD 185975")
            await self.configure_script(track_target=track_target)

            assert self.script.cwfs_target == track_target["target_name"]
            assert self.script.cwfs_target_ra is None
            assert self.script.cwfs_target_dec is None

            # Test with track_target; give target name and ra/dec
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5, dec=-87.5))
            await self.configure_script(track_target=track_target)

            assert self.script.cwfs_target == track_target["target_name"]
            assert self.script.cwfs_target_ra == track_target["icrs"]["ra"]
            assert self.script.cwfs_target_dec == track_target["icrs"]["dec"]

            # Test with track_target; fail if name is not provided ra/dec
            track_target = dict(icrs=dict(ra=20.5, dec=-87.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

            # Test with track_target; fail if only ra is provided
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

            # Test with track_target; fail if only dec is provided
            track_target = dict(target_name="HD 185975", icrs=dict(dec=-87.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

    async def atcs_get_bore_sight_angle(self):
        """Returns nasmyth rotator value for image"""
        logger.debug(f"visit_id_angles is: {self.visit_id_angles}")
        logger.debug(
            f"extra_visit_id is {self.script.extra_visit_id} and of type {type(self.script.extra_visit_id)}"
        )
        if self.script.extra_visit_id not in self.visit_id_angles:
            raise IOError(
                f"Image ID of {self.script.extra_visit_id} is not contained"
                " in self.visit_id_angles"
            )

        # modified from atcs.py
        # instrument on nasymth2, so
        parity_x = -1
        elevation_angle = self.visit_id_angles[self.script.extra_visit_id][0]
        nasmyth_angle = self.visit_id_angles[self.script.extra_visit_id][1]
        bore_sight_angle = elevation_angle + parity_x * nasmyth_angle + 90.0

        return bore_sight_angle

    @unittest.skipIf(
        CWFS_AVAILABLE is False or DATA_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}."
        f"Test data availability is {DATA_AVAILABLE}."
        f"Skipping test_take_sequence.",
    )
    async def test_take_sequence(self):
        """This tests the taking of an entire sequence.
        Data was taken on 2021-11-04.
        Prior to the set, telescope was focused, then hexapod was
        offset by x=1, y=1, z=0.05 mm.

        ==============================
        Measured [coma-X, coma-Y, focus] zernike coefficients [nm]:
        [-11.1, 14.5, -9.5, ]
        De-rotated [coma-X, coma-Y, focus]  zernike coefficients [nm]:
        [-9.0, 15.9, -9.5, ]
        Hexapod [x, y, z] offsets [mm] : -0.044, -0.077, -0.004,
        Telescope offsets [arcsec]: -2.3, -3.9, 0.0,
        ==============================

        Focus (-0.004) and coma (0.089) offsets inside tolerance level (0.010).
        Total focus correction: -0.004 mm.
        Total coma-x correction: 0.000 mm. Total coma-y correction: 0.000 mm.
        Applying telescope offset [az,el]: [-3.892, -2.297].
        """
        async with self.make_script():
            # Date for file to be produced
            self.date = "20211104"
            # sequence number start
            target_name = "HD 24661"
            self.seq_num_start = 950
            grating = "empty_1"
            filter = "FELH0600"
            # visitID: elevationCalculatedAngle, nasymth2CalculatedAngle
            self.visit_id_angles.update({2021110400950: [76.5, 96.16]})
            self.visit_id_angles.update({2021110400951: [76.5, 96.75]})
            self.visit_id_angles.update({2021110400954: [76.95, 89.09]})
            self.visit_id_angles.update({2021110400955: [76.96, 88.79]})
            self.visit_id_angles.update({2021110400958: [77.08, 85.1]})
            self.visit_id_angles.update({2021110400959: [77.09, 84.79]})

            # Use override of images since we need them to be non-sequential
            # Note that 960 is the in-focus image, but needs to be declared
            self.img_cnt_override_list = [950, 951, 954, 955, 958, 959, 960]
            # publish required events
            await self.atptg.evt_currentTarget.set_write(targetName=target_name)

            # exposures are 20s but putting short time here for speed
            exposure_time = 0.5
            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
            )

            # await self.run_script()
            await self.script.arun()

            # output on-sky from last pair
            centroid = [2708, 3094]  # [y,x]

            meas_zerns = [-11.1, 14.5, -9.5]
            # De - rotated zernike
            rot_zerns = [-9.0, 15.9, -9.5]
            # Hexapod offsets
            hex_offsets = [-0.044, -0.077, -0.004]
            # Telescope offsets
            tel_offsets = [-2.3, -3.9, 0.0]

            # UPDATE ME!
            total_focus = -0.060 + 0.0067 - 0.0044

            # Note that printed coma corrections above do *NOT* have the final
            # adjustment included
            total_xcoma = -0.712 - 0.255 - 0.044  # -1.011
            total_ycoma = -0.66 - 0.206 - 0.077  # -0.943

            with self.subTest(
                msg="Y-Centroid Comparison, index=0",
                measured=self.script.extra_result.brightestObjCentroidCofM[0],
                actual=centroid[0],
            ):
                assert (
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[0]
                        - centroid[0]
                    )
                    <= 100
                )

            with self.subTest(
                msg="X-Centroid Comparison, index=1",
                measured=self.script.extra_result.brightestObjCentroidCofM[1],
                actual=centroid[1],
            ):
                assert (
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[1]
                        - centroid[1]
                    )
                    <= 100
                )

            # Check that output values are within ~15-20nm of on-sky
            # validated values
            zern_tol = [20, 20, 20]  # [nm]
            hex_tol = abs(np.matmul(zern_tol, self.script.matrix_sensitivity))  # [mm]
            logger.info(
                f"Hex_tol is {np.matmul(zern_tol, self.script.matrix_sensitivity)}"
            )

            tel_offset_tol = np.matmul(hex_tol, self.script.hexapod_offset_scale)
            logger.debug(f"tel_offset_tol is {tel_offset_tol}")

            results = self.script.calculate_results()
            for i, z in enumerate(results.zernikes):
                with self.subTest(
                    msg="zern comparison", z=z, measured=meas_zerns[i], i=i
                ):
                    assert abs(z - meas_zerns[i]) <= zern_tol[i]
            for i, rz in enumerate(results.zernikes_rot):
                with self.subTest(
                    msg="rot-zern comparison", rz=rz, measured=rot_zerns[i], i=i
                ):
                    assert abs(rz - rot_zerns[i]) <= zern_tol[i]
            for i, h in enumerate(results.offset_hex):
                with self.subTest(
                    msg="hexapod comparison", h=h, measured=hex_offsets[i], i=i
                ):
                    assert abs(h - hex_offsets[i]) <= hex_tol[i]

            for i, t in enumerate(results.offset_tel):
                if t != 0:
                    with self.subTest(
                        msg="telescope offset comparison",
                        t=t,
                        measured=tel_offsets[i],
                        i=i,
                    ):
                        assert abs(t - tel_offsets[i]) <= tel_offset_tol[i]

            # Check that hexapod offsets were applied -  too hard to keep
            # track of how many calls should happen since
            # it also calls this to take the intra/extra focal images
            assert self.ataos.cmd_offset.callback.called
            # check that telescope offsets were applied three times
            # once after each iteration
            assert self.script.atcs.offset_xy.call_count == 3
            # check that total offsets are correct within the tolerance or 5%
            #
            assert (
                abs(self.script.offset_total_coma_x - total_xcoma) / abs(total_xcoma)
                <= 0.05
            ) or (abs(self.script.offset_total_coma_x - total_xcoma) < hex_tol[0])
            assert (
                abs(self.script.offset_total_coma_y - total_ycoma) / abs(total_ycoma)
                <= 0.05
            ) or (abs(self.script.offset_total_coma_x - total_xcoma) < hex_tol[1])
            logger.debug(
                f"Measured total focus offset is {self.script.offset_total_focus:0.5f}"
            )
            logger.debug(f"Reference total focus offset value is {total_focus:0.5f}")
            logger.debug(f"Tolerance is {max((0.05*total_focus, hex_tol[2])):0.5f}")
            assert (
                abs(self.script.offset_total_focus - total_focus) / abs(total_focus)
                <= 0.05
            ) or (abs(self.script.offset_total_focus - total_focus) < hex_tol[2])

    @unittest.skipIf(
        CWFS_AVAILABLE is False or DATA_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}."
        f"Test data availability is {DATA_AVAILABLE}."
        f"Skipping test_analysis.",
    )
    async def test_analysis(self):
        """This tests only the analysis of a single pair of donuts.
        It checks the fitting algormithm solution only and should be
        run before the test_full_sequence test.
        Data was taken on 2021-11-04, images 954-955. This is a middle
        iteration of a the set used in test_full_sequence.
        Prior to the set, telescope was focused, then hexapod was
        offset by x=1, y=1, z=0.05 mm.
        This test looks at only the analysis of images 954-955, where
        the output was:

        intraImage expId for target: 2021110400954
        extraImage expId for target: 2021110400955
        angle used in cwfs algorithm is 11.77
        Creating stamp for intra_image donut on centroid
        [y,x] = [3094,2708] with a side length of 228 pixels
        Creating stamp for intra_image donut on centroid
        [y,x] = [3090,2713] with a side length of 228 pixels
        ==============================
        Measured [coma-X, coma-Y, focus] zernike coefficients [nm]:
        [-60.1, 30.8, 50.7, ]
        De-rotated [coma-X, coma-Y, focus]  zernike coefficients [nm]:
        [-52.6, 42.4, 50.7, ]
        Hexapod [x, y, z] offsets [mm] : -0.255, -0.206, 0.007,
        Telescope offsets [arcsec]: -13.4, -10.4, 0.0,
        ==============================
        Applying offset:
        x=-0.2551161770829597, y=-0.20577598056746502, z=0.006737514919628802.
        """
        async with self.make_script():

            await self.configure_script()
            # visitID: elevationCalculatedAngle, nasymth2CalculatedAngle
            self.visit_id_angles.update({2021110400954: [76.95, 89.09]})
            self.visit_id_angles.update({2021110400955: [76.96, 88.79]})

            # intra and extra were reversed prior to this branch, so trying
            # to test this therefore I'll invert the image order
            #
            self.script.intra_visit_id = 2021110400954
            self.script.extra_visit_id = 2021110400955

            self.script.angle = 90.0 - await self.atcs_get_bore_sight_angle()
            # Binning must be set to the default (1) when being instantiated
            # using the configure_script method above, therefore do not
            # modify the parameter
            # self.script._binning = 1

            logger.debug(f"boresight angle is {self.script.angle}")
            await self.script.run_align()

            # output on-sky from first pair
            centroid = [2708, 3094]  # [x,y]

            meas_zerns = [
                -60.1,
                30.8,
                50.7,
            ]
            # De-rotated zernike
            rot_zerns = [
                -52.6,
                42.4,
                50.7,
            ]
            # Hexapod offsets
            hex_offsets = [-0.255, -0.206, 0.007]
            # Telescope offsets
            tel_offsets = [-13.4, -10.4, 0.0]

            # Check that Centroid is correct to within 100 pixels
            # the original script used a single centroid for a combination of
            # the two donuts. Now we used two, so taking the extra for now.
            with self.subTest(
                msg="Y-Centroid Comparison, index=0",
                measured=self.script.extra_result.brightestObjCentroidCofM[0],
                actual=centroid[0],
            ):
                assert (
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[0]
                        - centroid[0]
                    )
                    <= 100
                )

            with self.subTest(
                msg="X-Centroid Comparison, index=1",
                measured=self.script.extra_result.brightestObjCentroidCofM[1],
                actual=centroid[1],
            ):
                assert (
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[1]
                        - centroid[1]
                    )
                    <= 100
                )

            # get dict of results from the last run and check they're within
            # ~15nm of the expected values
            zern_tol = [15, 15, 15]  # [nm]
            # hex_tol is in mm
            hex_tol = abs(np.matmul(zern_tol, self.script.matrix_sensitivity))
            logger.debug(f"Hex_tol is {hex_tol}")

            tel_offset_tol = np.matmul(hex_tol, self.script.hexapod_offset_scale)
            logger.debug(f"tel_offset_tol is {tel_offset_tol}")

            results = self.script.calculate_results()
            for i, z in enumerate(results.zernikes):
                with self.subTest(
                    msg="zern comparison", z=z, measured=meas_zerns[i], i=i
                ):
                    assert abs(z - meas_zerns[i]) <= zern_tol[i]
            for i, rz in enumerate(results.zernikes_rot):
                with self.subTest(
                    msg="rot-zern comparison", rz=rz, measured=rot_zerns[i], i=i
                ):
                    assert abs(rz - rot_zerns[i]) <= zern_tol[i]
            for i, h in enumerate(results.offset_hex):
                with self.subTest(
                    msg="hexapod comparison", h=h, measured=hex_offsets[i], i=i
                ):
                    assert abs(h - hex_offsets[i]) <= hex_tol[i]

            for i, t in enumerate(results.offset_tel):
                if t != 0:
                    with self.subTest(
                        msg="telescope offset comparison",
                        t=t,
                        measured=tel_offsets[i],
                        i=i,
                    ):
                        assert abs(t - tel_offsets[i]) <= tel_offset_tol[i]

    @unittest.skipIf(
        CWFS_AVAILABLE is False or DATA_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}."
        f"Test data availability is {DATA_AVAILABLE}."
        f"Skipping test_source_finding.",
    )
    async def test_source_finding(self):
        """This tests the source finding where there was a mis-match
        in sources found that caused an error in the script.
        Occurred at 17:44:04 Tucson time, on 2022-03-16.
        This test verifies a new functionality where the intra
        box is used as the extra box.
        Previously this would have raised an exception.
        As this has not been used on-sky we cannot verify the results.
        """
        async with self.make_script():

            await self.configure_script()
            # visitID: elevationCalculatedAngle, nasymth2CalculatedAngle
            self.visit_id_angles.update({2022031600232: [51.07, 0.58]})
            self.visit_id_angles.update({2022031600233: [51.07, 0.58]})

            # intra and extra were reversed prior to this branch, so trying
            # to test this therefore I'll invert the image order
            #
            self.script.intra_visit_id = 2022031600232
            self.script.extra_visit_id = 2022031600233

            self.script.angle = 90.0 - await self.atcs_get_bore_sight_angle()
            # Binning must be set to the default (1) when being instantiated
            # using the configure_script method above, therefore do not
            # modify the parameter
            # self.script._binning = 1

            logger.debug(f"boresight angle is {self.script.angle}")
            await self.script.run_align()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_cwfs_align.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
