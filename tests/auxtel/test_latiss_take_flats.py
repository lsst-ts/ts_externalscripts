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
import unittest
import shutil
import yaml

import pytest
from lsst.ts import externalscripts, standardscripts
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
        self.script = LatissTakeFlats(index=index, remotes=False, simulation_mode=True)

        # Mock the latiss instrument setups
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock()

        # Mock setup of electrometer
        self.script.setup_electrometer = unittest.mock.AsyncMock()

        # Mock setup of atmonochromator
        self.script.setup_atmonochromator_axes = unittest.mock.AsyncMock(
            side_effect=self.setup_atmonochromator_axes_callback
        )

        # mock fiber spectrograph exposures
        self.script.take_fs_exposures = unittest.mock.AsyncMock(
            side_effect=self.take_fs_exposures_callback
        )

        # mock electrometer exposures
        self.script.take_em_exposures = unittest.mock.AsyncMock(
            side_effect=self.take_em_exposures_callback
        )

        # Mock Latiss.take_flats
        self.script.latiss.take_flats = unittest.mock.AsyncMock(
            side_effect=self.take_flats_callback
        )

        self.end_image_tasks = []

        # things to track
        self.nimages = 0
        self.counter = 0
        self.date = None  # Used to fake dataId output from takeImages
        self.seq_num_start = None  # Used to fake proper dataId from takeImages

        logger.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def setup_atmonochromator_axes_callback(
        self,
        wavelength: float,
        grating: str,
        entrance_slit_width: float,
        exit_slit_width: float,
    ):
        """
        Mocks the monochromator setup.
        """

        # Check that all inputs are the correct type.

        assert type(wavelength) == float
        assert type(grating) == int
        assert type(entrance_slit_width) == float
        assert type(exit_slit_width) == float

        return

    async def take_fs_exposures_callback(self, expTime, n):
        """
        Mocks the taking of fiber spectrograph images
        """

        # FIXME TO SUPPORT MULTIPLE IMAGES

        self.counter += 1
        return [f"FS_LFA_url{self.counter}"]

    async def take_em_exposures_callback(self, expTime, n):
        """
        Mocks the taking of fiber spectrograph images
        """
        # FIXME TO SUPPORT MULTIPLE images
        # For now just use 1

        self.counter += 1
        return [f"EM_LFA_url{self.counter}"]

    async def take_flats_callback(
        self,
        exptime: float,
        n_flats: int,
        group_id: str,
        program: str,
        reason: str,
        note: str,
    ):
        """
        Mocks the take_flats, which is only ever called with a single image.
        Returns a list of ids (ints)
        """

        self.counter += 1
        return [self.counter]

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        logger.debug("Closing end_image_tasks")
        await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
        logger.debug("Closing remotes")
        # await asyncio.gather(
        #     self.atcamera.close(),
        # )
        logger.debug("Remotes closed")

    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            latiss_filter = "SDSSr_65mm"
            latiss_grating = "empty_1"
            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
            )

        async with self.make_script():
            # Try more complex parameters
            latiss_filter = "SDSSr_65mm"
            latiss_grating = "empty_1"
            # load a complex sequence defined as yaml
            test_sequence_path = os.path.join(
                getPackageDir("ts_externalscripts"),
                "tests",
                "data",
                "auxtel",
                "test_sequence1.yaml",
            )
            with open(test_sequence_path, "r") as file:
                sequence = yaml.safe_load(file)

            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
                sequence=sequence,
            )

    async def test_invalid_sequence(self):
        # invalid filters, script should configure and hardware will get
        # setup but fail.
        # Note that in the real case and error will be thrown when an invalid
        #  filter is declared to setup LATISS

        async with self.make_script():
            # Try configure with invalid sequence data. This should fail
            latiss_filter = "filter1"
            latiss_grating = "grating1"

            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
            )

            with pytest.raises(RuntimeError):
                await self.script.arun()

    async def test_sequence(self):
        # valid sequence, using the default

        async with self.make_script():
            # Try configure with invalid sequence data.
            latiss_filter = "SDSSr_65mm"
            latiss_grating = "empty_1"

            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
            )
            # indication simulation for s3 bucket.
            await self.script.arun(simulation_mode=1)

    async def test_sequence_custom(self):
        # valid sequence, using a custom input

        async with self.make_script():
            # Try configure with complex sequence data.
            latiss_filter = "SDSSr_65mm"
            latiss_grating = "empty_1"
            # load a complex sequence defined as yaml
            test_sequence_path = os.path.join(
                getPackageDir("ts_externalscripts"),
                "tests",
                "data",
                "auxtel",
                "test_sequence1.yaml",
            )

            with open(test_sequence_path, "r") as file:
                sequence = yaml.safe_load(file)

            await self.configure_script(
                latiss_filter=latiss_filter,
                latiss_grating=latiss_grating,
                sequence=sequence,
            )

            # indication of simulation for s3 bucket.
            await self.script.arun(simulation_mode=1)

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_take_flats.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
