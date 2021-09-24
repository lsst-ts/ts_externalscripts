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

__all__ = ["LatissCWFSAlign"]

import random
import unittest
import asyncio
import numpy as np
import warnings
import os
import pathlib

try:
    # TODO: (DM-24904) Remove this try/except clause when WEP is adopted
    from lsst import cwfs

    CWFS_AVAILABLE = True
except ImportError:
    CWFS_AVAILABLE = False
    warnings.warn("Could not import cwfs package. Most tests will be skipped.")

from lsst.ts import salobj
from lsst.ts import standardscripts
from lsst.ts import externalscripts
from lsst.ts.externalscripts.auxtel import LatissCWFSAlign
import lsst.daf.butler as dafButler
import logging

# Make matplotlib less chatty
logging.getLogger("matplotlib").setLevel(logging.WARNING)
# Make obslsst translators less chatty
logging.getLogger("lsst.obs.lsst.translators").setLevel(logging.WARNING)
logging.getLogger("astro_metadata_translator").setLevel(logging.WARNING)
logging.getLogger("flake8.style_guide").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)
logger.propagate = True

random.seed(47)  # for set_random_lsst_dds_domain

# Check to see if the test data is accessible for testing at NCSA
# Depending upon how we load test data this will change
# for now just checking if butler is instantiated with
# the default path used on the summit and on the NTS.

DATAPATH = "/readonly/repo/main/"
try:
    butler = dafButler.Butler(
        DATAPATH, instrument="LATISS", collections="LATISS/raw/all"
    )
    DATA_AVAILABLE = True
except FileNotFoundError:
    logger.warning("Data unavailable, certain tests will be skipped")
    DATA_AVAILABLE = False
    DATAPATH = pathlib.Path(__file__).parents[1].joinpath("data", "auxtel").as_posix()
except PermissionError:
    logger.warning(
        "Data unavailable due to permissions (at a minimum),"
        " certain tests will be skipped"
    )
    DATA_AVAILABLE = False
    DATAPATH = pathlib.Path(__file__).parents[1].joinpath("data", "auxtel").as_posix()


class TestLatissCWFSAlign(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = LatissCWFSAlign(index=index, remotes=True)

        self.visit_id_angles = {}
        self.end_image_tasks = []

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour

        self.atcamera = salobj.Controller(name="ATCamera")
        self.atheaderservice = salobj.Controller(name="ATHeaderService")
        self.atarchiver = salobj.Controller(name="ATArchiver")
        self.ataos = salobj.Controller(name="ATAOS")
        self.athexapod = salobj.Controller(name="ATHexapod")
        self.atptg = salobj.Controller(name="ATPtg")
        self.atmcs = salobj.Controller(name="ATMCS")

        # Create mocks
        self.atcamera.cmd_takeImages.callback = unittest.mock.AsyncMock(
            wraps=self.cmd_take_images_callback
        )
        self.script.latiss.ready_to_take_data = salobj.make_done_future
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

        # things to track
        self.nimages = 0
        self.date = None  # Used to fake dataId output from takeImages
        self.seq_num_start = None  # Used to fake proper dataId from takeImages

        # Return a single element tuple
        return (self.script,)

    async def ataos_cmd_offset_callback(self, data):
        """Publishes event from hexapod saying movement completed"""
        logger.debug("Sending hexapod event ")

        self.athexapod.evt_positionUpdate.put()
        self.athexapod.tel_positionStatus.put()
        return

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        logger.debug("Closing Remotes")
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        await asyncio.gather(
            self.atarchiver.close(),
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
        imgNum = self.atcamera.cmd_takeImages.callback.await_count - 1
        image_name = f"AT_O_{self.date}_{(imgNum + self.seq_num_start):06d}"
        self.atcamera.evt_endReadout.set_put(imageName=image_name)
        await asyncio.sleep(0.5)
        self.atheaderservice.evt_largeFileObjectAvailable.put()
        await asyncio.sleep(1.0)
        self.atarchiver.evt_imageInOODS.set_put(obsid=image_name)

    @unittest.skipIf(
        CWFS_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}. Skipping test_configure.",
    )
    async def test_configure(self):
        async with self.make_script():
            # First make sure the cwfs package is present
            self.assertTrue(os.path.exists(cwfs.__file__))
            # Try configure with minimum set of parameters declared
            grating = "test_disp1"
            filter = "test_filt1"
            exposure_time = 1.0
            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
                dataPath=DATAPATH,
            )

            self.assertEqual(self.script.filter, filter)
            self.assertEqual(self.script.grating, grating)
            self.assertEqual(self.script.exposure_time, exposure_time)
            self.assertEqual(self.script.cwfs_target, None)
            self.assertEqual(self.script.cwfs_target_ra, None)
            self.assertEqual(self.script.cwfs_target_dec, None)

            # Test with find_target
            find_target = dict(az=-180.0, el=60.0, mag_limit=8.0)
            await self.configure_script(find_target=find_target)

            self.assertNotEqual(self.script.cwfs_target, None)
            self.assertEqual(self.script.cwfs_target_ra, None)
            self.assertEqual(self.script.cwfs_target_dec, None)

            # Test with find_target; fail if only az is provided
            find_target = dict(az=0.0)
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with find_target; fail if only el is provided
            find_target = dict(el=60.0)
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with find_target; fail if only az and el is provided
            find_target = dict(az=0.0, el=60.0)
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

            # Test with track_target; give target name only
            track_target = dict(target_name="HD 185975")
            await self.configure_script(track_target=track_target)

            self.assertEqual(self.script.cwfs_target, track_target["target_name"])
            self.assertEqual(self.script.cwfs_target_ra, None)
            self.assertEqual(self.script.cwfs_target_dec, None)

            # Test with track_target; give target name and ra/dec
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5, dec=-87.5))
            await self.configure_script(track_target=track_target)

            self.assertEqual(self.script.cwfs_target, track_target["target_name"])
            self.assertEqual(self.script.cwfs_target_ra, track_target["icrs"]["ra"])
            self.assertEqual(self.script.cwfs_target_dec, track_target["icrs"]["dec"])

            # Test with track_target; fail if name is not provided ra/dec
            track_target = dict(icrs=dict(ra=20.5, dec=-87.5))
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

            # Test with track_target; fail if only ra is provided
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5))
            with self.assertRaises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

            # Test with track_target; fail if only dec is provided
            track_target = dict(target_name="HD 185975", icrs=dict(dec=-87.5))
            with self.assertRaises(salobj.ExpectedError):
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
        async with self.make_script():
            # Date for file to be produced
            self.date = "20210323"
            # sequence number start
            target_name = "HD 24661"
            self.seq_num_start = 307
            grating = "empty_1"
            filter = "RG610"
            # visitID: elevationCalculatedAngle, nasymth2CalculatedAngle
            self.visit_id_angles.update({2021032300308: [47.907, -118.61]})
            self.visit_id_angles.update({2021032300310: [47.907, -118.61]})
            # publish required events
            self.atptg.evt_currentTarget.set_put(targetName=target_name)

            # exposures are 20s but putting short time here for speed
            exposure_time = 0.5
            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
                dataPath=DATAPATH,
            )

            # await self.run_script()
            await self.script.arun()

            # output on-sky from first pair
            # Selected source 2 @ [1915.2870675674224, 1629.638405]
            # Looking at image 309, centroid is ~1926, 1450
            # the centroid above is for image 308
            # Poor centroid, so eyeballing gives this.
            centroid = [1926.0, 1450.0]  # [y,x]

            # == == == == == == == == == == == == == == ==
            # Measured[coma - X, coma - Y, focus] zernike
            # coefficients in nm: [-19.40256, -51.19022, -11.11000]
            # De - rotated zernike
            # coefficients: [30.81990987 45.24411764 - 11.11000346]
            # Hexapod offset: [0.14961121 - 0.21963164 0.0083452]
            # Telescope offsets: [8.97667278 - 13.17789834 0.]
            # == == == == == == == == == == == == == == ==
            # Applying offset: x = 0.14961121297507113, y = -0.219631639005,
            # z = 0.008345202883904302.
            # Applying telescope offset
            # x / y: 8.976672778504268 / 13.177898340311959.

            # second pair
            # Selected source 1  @ [1908.3507014028055, 1454.0437162985766]

            # == == == == == == == == == == == == == == ==
            # Measured[coma - X, coma - Y, focus] zernike
            # coefficients in nm: [-5.15634, 0.65542, -19.83415]
            meas_zerns = [-5.156342491620025, 0.6554215087770965, -19.8341551660864]
            # De - rotated zernike
            # coefficients: [4.86354471 - 1.83395149 - 19.83415517]
            rot_zerns = [4.86354471, -1.83395149, -19.83415517]
            # Hexapod offset: [0.02360944 0.00890268 0.00449137]
            hex_offsets = [0.02360944, 0.00890268, 0.00449137]
            # Telescope
            # offsets: [1.41656642 0.53416063 0.]
            # tel_offsets = [1.41656642, 0.53416063, 0.0]
            # == == == == == == == == == == == == == == ==

            # Focus(0.0044913722282236765) and comma(0.025232188452070977)
            # offsets inside  tolerance
            # level(0.01).Total focus correction: 0.012836575112127978
            total_focus = 0.012836575112127978
            # mm.Total
            # comma - x
            # correction: 0.14961121297507113
            # mm.Total
            # comma - y
            # correction: -0.21963163900519933
            # mm.
            # Applying telescope offset
            # x / y: 1.4165664213786795 / -0.5341606280075011.

            # Note that printed coma corrections above do *NOT* have the final
            # adjustment included
            total_xcoma = 0.14961121297507113 + 0.02360944
            total_ycoma = -0.21963163900519933 + 0.00890268

            with self.subTest(
                msg="Y-Centroid Comparison, index=0",
                measured=self.script.extra_result.brightestObjCentroidCofM[0],
                actual=centroid[0],
            ):
                self.assertTrue(
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
                self.assertTrue(
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[1]
                        - centroid[1]
                    )
                    <= 100
                )

            # Check that output values are within ~15-20nm of on-sky
            # validated values
            zern_tol = [20, 20, 20]  # [nm]
            hex_tol = abs(np.matmul(zern_tol, self.script.sensitivity_matrix))  # [mm]
            logger.info(
                f"Hex_tol is {np.matmul(zern_tol, self.script.sensitivity_matrix)}"
            )
            results = self.script.calculate_results()

            for i, z in enumerate(results["zerns"]):
                with self.subTest(
                    msg="zern comparison", z=z, measured=meas_zerns[i], i=i
                ):
                    self.assertTrue(abs(z - meas_zerns[i]) <= zern_tol[i])
            for i, rz in enumerate(results["rot_zerns"]):
                with self.subTest(
                    msg="rot-zern comparison", rz=rz, measured=rot_zerns[i], i=i
                ):
                    self.assertTrue(abs(rz - rot_zerns[i]) <= zern_tol[i])
            for i, h in enumerate(results["hex_offset"]):
                with self.subTest(
                    msg="hexapod comparison", h=h, measured=hex_offsets[i], i=i
                ):
                    self.assertTrue(abs(h - hex_offsets[i]) <= hex_tol[i])

            # Note that there is a known issue with the sign of the telescope
            # offsets, omitting for now.
            # for i, t in enumerate(results['tel_offset']):
            #     if t != 0:
            #         with self.subTest(t=t, i=i):
            #             self.assertTrue(abs(t - tel_offsets[i])
            #             / abs(tel_offsets[i]) <= 0.05)

            # Check that hexapod offsets were applied -  too hard to keep
            # track of how many calls should happen since
            # it also calls this to take the intra/extra focal images
            self.assertTrue(self.ataos.cmd_offset.callback.called)
            # check that telescope offsets were applied twice
            self.assertEqual(self.script.atcs.offset_xy.call_count, 2)
            # check that total offsets are correct within the tolerance or 5%
            #
            self.assertTrue(
                (
                    abs(self.script.total_coma_x_offset - total_xcoma)
                    / abs(total_xcoma)
                    <= 0.05
                )
                or (abs(self.script.total_coma_x_offset - total_xcoma) < hex_tol[0])
            )
            self.assertTrue(
                (
                    abs(self.script.total_coma_y_offset - total_ycoma)
                    / abs(total_ycoma)
                    <= 0.05
                )
                or (abs(self.script.total_coma_x_offset - total_xcoma) < hex_tol[1])
            )
            logger.debug(
                f"Measured total focus offset is {self.script.total_focus_offset:0.5f}"
            )
            logger.debug(f"Reference total focus offset value is {total_focus:0.5f}")
            logger.debug(f"Tolerance is {max((0.05*total_focus, hex_tol[2])):0.5f}")
            self.assertTrue(
                (
                    abs(self.script.total_focus_offset - total_focus) / abs(total_focus)
                    <= 0.05
                )
                or (abs(self.script.total_focus_offset - total_focus) < hex_tol[2])
            )

    @unittest.skipIf(
        CWFS_AVAILABLE is False or DATA_AVAILABLE is False,
        f"CWFS package availibility is {CWFS_AVAILABLE}."
        f"Test data availability is {DATA_AVAILABLE}."
        f"Skipping test_analysis.",
    )
    async def test_analysis(self):
        """This tests only the analysis part"""
        async with self.make_script():

            # visitID: elevationCalculatedAngle, nasymth2CalculatedAngle
            self.visit_id_angles.update({2021032300308: [47.907, -118.61]})
            self.visit_id_angles.update({2021032300310: [47.907, -118.61]})

            self.script.intra_visit_id = 2021032300307
            self.script.extra_visit_id = 2021032300308
            self.script.angle = 90.0 - await self.atcs_get_bore_sight_angle()
            self.script._binning = 2
            self.script.dataPath = DATAPATH
            logger.debug(f"boresight angle is {self.script.angle}")
            await self.script.run_cwfs()

            # output on-sky from first pair
            # Selected source 2 @ [1915.2870675674224, 1629.638405]
            centroid = [1915.2870675674224, 1629.638405]  # [y,x]
            # Looking at image 309, centroid is ~1926, 1450
            # the centroid above is for image 308

            # == == == == == == == == == == == == == == ==
            # Measured[coma - X, coma - Y, focus] zernike
            # coefficients in nm: [-19.40256, -51.19022, -11.11000]
            meas_zerns = [-19.40256, -51.19022, -11.11000]
            # De - rotated zernike
            # coefficients: [30.81990987 45.24411764 - 11.11000346]
            rot_zerns = [30.81990987, 45.24411764, -11.11000346]
            # Hexapod offset: [0.14961121 - 0.21963164 0.0083452]
            hex_offsets = [0.14961121, -0.21963164, 0.0083452]
            # Telescope
            # offsets: [8.97667278 - 13.17789834 0.]
            # == == == == == == == == == == == == == == ==
            # Applying
            # offset: x = 0.14961121297507113, y = -0.21963163900519933,
            # z = 0.008345202883904302.
            # Applying telescope offset
            # x / y: 8.976672778504268 / 13.177898340311959.

            # second pair
            # Selected source 1  @ [1908.3507014028055, 1454.0437162985766]

            # == == == == == == == == == == == == == == ==
            # Measured[coma - X, coma - Y, focus] zernike
            # coefficients in nm: [-5.15634, 0.65542, -19.83415]
            # meas_zerns = [-5.156342491620025, 0.6554215087770965, -19.834155]
            # De - rotated zernike
            # coefficients: [4.86354471 - 1.83395149 - 19.83415517]
            # rot_zerns = [4.86354471, -1.83395149, -19.83415517]
            # Hexapod offset: [0.02360944 0.00890268 0.00449137]
            # hex_offsets = [0.02360944, 0.00890268, 0.00449137]
            # Telescope offsets: [1.41656642 0.53416063 0.]
            # tel_offsets = [1.41656642, 0.53416063, 0.0]
            # == == == == == == == == == == == == == == ==

            # Check that Centroid is correct to within 100 pixels
            # the original script used a single centroid for a combination of
            # the two donuts. Now we used two, so taking the extra for now.
            with self.subTest(
                msg="Y-Centroid Comparison, index=0",
                measured=self.script.extra_result.brightestObjCentroidCofM[0],
                actual=centroid[0],
            ):
                self.assertTrue(
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
                self.assertTrue(
                    abs(
                        self.script.extra_result.brightestObjCentroidCofM[1]
                        - centroid[1]
                    )
                    <= 100
                )

            # get dict of results from the last run and check they're within
            # ~15nm of the expected values
            zern_tol = [10, 10, 10]  # [nm]
            hex_tol = abs(np.matmul(zern_tol, self.script.sensitivity_matrix))  # [mm]
            logger.info(
                f"Hex_tol is {np.matmul(zern_tol, self.script.sensitivity_matrix)}"
            )
            results = self.script.calculate_results()

            for i, z in enumerate(results["zerns"]):
                with self.subTest(
                    msg="zern comparison", z=z, measured=meas_zerns[i], i=i
                ):
                    self.assertTrue(abs(z - meas_zerns[i]) <= zern_tol[i])
            for i, rz in enumerate(results["rot_zerns"]):
                with self.subTest(
                    msg="rot-zern comparison", rz=rz, measured=rot_zerns[i], i=i
                ):
                    self.assertTrue(abs(rz - rot_zerns[i]) <= zern_tol[i])
            for i, h in enumerate(results["hex_offset"]):
                with self.subTest(
                    msg="hexapod comparison", h=h, measured=hex_offsets[i], i=i
                ):
                    self.assertTrue(abs(h - hex_offsets[i]) <= hex_tol[i])

            # Note that there is a known issue with the sign of the telescope
            # offsets, omitting for now.
            # for i, t in enumerate(results['tel_offset']):
            #     if t != 0:
            #         with self.subTest(t=t, i=i):
            #             self.assertTrue(abs(t - tel_offsets[i])
            #             / abs(tel_offsets[i]) <= 0.05)

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_cwfs_align.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
