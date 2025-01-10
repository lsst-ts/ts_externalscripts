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

import asyncio
import logging
import unittest

import numpy as np
import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel import LatissIntraExtraFocalData

logger = logging.getLogger(__name__)
logger.propagate = True


class TestLatissIntraExtraFocalData(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        logger.debug("Starting basic_make_script")
        self.script = LatissIntraExtraFocalData(index=index)

        self.visit_id_angles = {}
        self.end_image_tasks = []
        self.img_cnt_override_list = None

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
        # Set offset_telescope to True
        self.script.offset_telescope = True

        # things to track
        self.nimages = 0
        self.date = None  # Used to fake dataId output from takeImages
        self.seq_num_start = None  # Used to fake proper dataId from takeImages

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def configure_script(self, **kwargs):
        await super().configure_script(**kwargs)

        await self.script._configure_target()

    async def test_configure(self):
        # Try configure with minimum set of parameters declared
        async with self.make_script():
            grating = "test_disp1"
            filter = "test_filt1"
            exposure_time = 1.0
            # Set offsets to degrees of freedom
            offset_x = 0.0
            offset_y = 0.0
            offset_z = 0.8
            offset_rx = 0.0
            offset_ry = 0.0
            offset_m1 = 0.0

            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
                offset_x=offset_x,
                offset_y=offset_y,
                offset_z=offset_z,
                offset_rx=offset_rx,
                offset_ry=offset_ry,
                offset_m1=offset_m1,
            )

            assert self.script.filter == filter
            assert self.script.grating == grating
            assert self.script.exposure_time == exposure_time
            assert self.script.offset_x == offset_x
            assert self.script.offset_y == offset_y
            assert self.script.offset_z == offset_z
            assert self.script.offset_rx == offset_rx
            assert self.script.offset_ry == offset_ry
            assert self.script.offset_m1 == offset_m1

    # Test with find_target
    # this can fail occasionally if you're unlucky and
    # don't get a target so the mag_range is large to
    # prevent this
    async def test_configure_with_find_target(self):
        async with self.make_script():
            find_target = dict(az=-180.0, el=60.0, mag_limit=6.0, mag_range=14)
            await self.configure_script(find_target=find_target)

            assert self.script.cwfs_target is not None
            assert self.script.cwfs_target_ra is None
            assert self.script.cwfs_target_dec is None

        # Test with find_target; fail if only az is provided
        async with self.make_script():
            find_target = dict(az=0.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

        # Test with find_target; fail if only el is provided
        async with self.make_script():
            find_target = dict(el=60.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

        # Test with find_target; fail if only az and el is provided
        async with self.make_script():
            find_target = dict(az=0.0, el=60.0)
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(find_target=find_target)

    async def test_configure_with_track_target(self):
        # Test with track_target; give target name only
        async with self.make_script():
            track_target = dict(target_name="HD 185975")
            await self.configure_script(track_target=track_target)

            assert self.script.cwfs_target == track_target["target_name"]
            assert self.script.cwfs_target_ra is None
            assert self.script.cwfs_target_dec is None

        # Test with track_target; give target name and ra/dec
        async with self.make_script():
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5, dec=-87.5))
            await self.configure_script(track_target=track_target)

            assert self.script.cwfs_target == track_target["target_name"]
            assert self.script.cwfs_target_ra == track_target["icrs"]["ra"]
            assert self.script.cwfs_target_dec == track_target["icrs"]["dec"]

        # Test with track_target; fail if name is not provided ra/dec
        async with self.make_script():
            track_target = dict(icrs=dict(ra=20.5, dec=-87.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

        # Test with track_target; fail if only ra is provided
        async with self.make_script():
            track_target = dict(target_name="HD 185975", icrs=dict(ra=20.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

        # Test with track_target; fail if only dec is provided
        async with self.make_script():
            track_target = dict(target_name="HD 185975", icrs=dict(dec=-87.5))
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(track_target=track_target)

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
        await self.atcamera.evt_startIntegration.set_write(imageName=image_name)
        await asyncio.sleep(one_exp_time * data.numImages)
        self.nimages += 1
        logger.debug("Scheduling finish_take_images before returning from take_images")
        self.end_image_tasks.append(
            asyncio.create_task(self.finish_take_images(image_name=image_name))
        )

    async def finish_take_images(self, image_name):
        await asyncio.sleep(0.5)
        await self.atcamera.evt_endReadout.set_write(imageName=image_name)
        await asyncio.sleep(0.5)
        await self.atheaderservice.evt_largeFileObjectAvailable.write()
        await asyncio.sleep(1.0)
        await self.atoods.evt_imageInOODS.set_write(obsid=image_name)

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
            self.visit_id_angles.update({2021110400951: [76.5, 96.16]})

            self.script.intra_visit_id = 2021110400950
            self.script.extra_visit_id = 2021110400951

            # Use override of images since we need them to be non-sequential
            # Note that 960 is the in-focus image, but needs to be declared
            self.img_cnt_override_list = [950, 951, 954, 955, 958, 959, 960]
            # publish required events
            await self.atptg.evt_currentTarget.set_write(targetName=target_name)

            # exposures are 20s but putting short time here for speed
            exposure_time = 0.5
            # Set offsets to degrees of freedom
            offset_x = 0.5
            offset_y = 0.0
            offset_z = 0.8
            offset_rx = 0.0
            offset_ry = 0.0
            offset_m1 = 0.0

            await self.configure_script(
                grating=grating,
                filter=filter,
                exposure_time=exposure_time,
                offset_x=offset_x,
                offset_y=offset_y,
                offset_z=offset_z,
                offset_rx=offset_rx,
                offset_ry=offset_ry,
                offset_m1=offset_m1,
            )

            assert self.script.filter == filter
            assert self.script.grating == grating
            assert self.script.exposure_time == exposure_time
            assert self.script.offset_x == offset_x
            assert self.script.offset_y == offset_y
            assert self.script.offset_z == offset_z
            assert self.script.offset_rx == offset_rx
            assert self.script.offset_ry == offset_ry
            assert self.script.offset_m1 == offset_m1

            # await self.run_script()
            await self.script.arun()

            # Check that hexapod offsets were applied -  too hard to keep
            # track of how many calls should happen since
            # it also calls this to take the intra/extra focal images
            assert self.ataos.cmd_offset.callback.called

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

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_intra_extra_focal_data.py"

        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
