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

import types
import unittest
import contextlib
import unittest.mock
import os
import tempfile

import numpy as np

from lsst.ts.standardscripts import BaseScriptTestCase
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.auxtel.build_pointing_model import BuildPointingModel
from lsst.ts.observatory.control.utils.enums import RotType
import lsst.daf.butler as dafButler
from lsst.utils import getPackageDir

# Declare the local path that has the information to build a
# local gen3 butler database

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


class TestBuildPointingModel(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.remotes_needed = True

    async def basic_make_script(self, index):

        self.script = BuildPointingModel(index=index, remotes=self.remotes_needed)

        # Mock the method that returns the BestEffortIsr class if it is
        # not available for import
        self.script.get_best_effort_isr = unittest.mock.AsyncMock()

        return (self.script,)

    async def test_configure(self):

        async with self.make_configured_dry_script() as test_configuration:
            self.assert_config(test_configuration)

    def assert_config(self, configuration):
        self.check_configuration_values(configuration)
        self.check_azel_grid()

    def check_configuration_values(self, configuration):

        for key in configuration:
            with self.subTest(key=key, value=configuration[key]):
                assert getattr(self.script.config, key) == configuration[key]

    def check_azel_grid(self):

        assert len(self.script.elevation_grid) == len(self.script.azimuth_grid)

        assert len(self.script.elevation_grid) > 0

        assert (
            np.min(self.script.elevation_grid) >= self.script.config.elevation_minimum
        )

        assert (
            np.max(self.script.elevation_grid) <= self.script.config.elevation_maximum
        )

    async def test_metadata(self):

        async with self.make_configured_dry_script():

            metadata = types.SimpleNamespace(
                duration=0.0,
                nimages=0,
                datapath=DATAPATH,
            )

            self.script.set_metadata(metadata)

            self.assert_metadata(metadata)

    def assert_metadata(self, metadata):

        assert metadata.nimages == len(self.script.elevation_grid) * 2
        assert metadata.duration == metadata.nimages * (
            self.script.config.exposure_time
            + self.script.camera_readout_time
            + self.script.estimated_average_slew_time
        )

    async def test_executable(self):

        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "build_pointing_model.py"
        await self.check_executable(script_path)

    async def test_arun(self):

        async with self.make_configured_dry_script():

            self.script.execute_grid = unittest.mock.AsyncMock()

            await self.script.arun()

            self.assert_arun()

    def assert_arun(self):

        assert self.script.execute_grid.await_count == self.script.grid_size
        calls = [
            unittest.mock.call(azimuth, elevation)
            for azimuth, elevation in zip(
                self.script.azimuth_grid, self.script.elevation_grid
            )
        ]
        self.script.execute_grid.assert_has_awaits(calls)

    async def test_execute_grid(self):

        async with self.make_configured_dry_script():

            azimuth, elevation = (
                self.script.azimuth_grid[0],
                self.script.elevation_grid[0],
            )

            target_name = "HD 12345"

            self.script.atcs.find_target = unittest.mock.AsyncMock(
                return_value=target_name
            )
            self.script.atcs.slew_object = unittest.mock.AsyncMock()
            self.script.center_on_brightest_source = unittest.mock.AsyncMock()

            await self.script.execute_grid(azimuth=azimuth, elevation=elevation)

            self.assert_execute_grid(
                azimuth=azimuth, elevation=elevation, target_name=target_name
            )

    def assert_execute_grid(self, azimuth, elevation, target_name):

        self.script.atcs.find_target.assert_awaited_once_with(
            az=azimuth,
            el=elevation,
            mag_limit=self.script.config.magnitude_limit,
            mag_range=self.script.config.magnitude_range,
        )
        self.script.atcs.slew_object.assert_awaited_once_with(
            name=target_name,
            rot_type=RotType.PhysicalSky,
        )
        self.script.center_on_brightest_source.assert_awaited()
        assert self.script.iterations["failed"] == 0
        assert self.script.iterations["successful"] == 1

    async def test_execute_grid_fail_to_find_target(self):

        async with self.make_configured_dry_script():

            azimuth, elevation = (
                self.script.azimuth_grid[0],
                self.script.elevation_grid[0],
            )

            self.script.atcs.find_target = unittest.mock.AsyncMock(
                side_effect=RuntimeError("Unittesting failure.")
            )
            self.script.atcs.slew_object = unittest.mock.AsyncMock()
            self.script.center_on_brightest_source = unittest.mock.AsyncMock()

            await self.script.execute_grid(azimuth=azimuth, elevation=elevation)

            self.assert_execute_grid_fail(azimuth=azimuth, elevation=elevation)

    def assert_execute_grid_fail(self, azimuth, elevation):

        self.script.atcs.find_target.assert_awaited_once_with(
            az=azimuth,
            el=elevation,
            mag_limit=self.script.config.magnitude_limit,
            mag_range=self.script.config.magnitude_range,
        )
        self.script.atcs.slew_object.assert_not_awaited()
        self.script.center_on_brightest_source.assert_not_awaited()
        assert self.script.iterations["failed"] == 1
        assert self.script.iterations["successful"] == 0

    async def test_center_on_brightest_source(self):

        async with self.make_configured_dry_script():

            self.find_offset_image_id = [
                123,
            ]
            self.find_offset_return_value = (-10.0, 10.0)

            self.script.latiss.rem.atarchiver = unittest.mock.AsyncMock()
            self.script.latiss.rem.atarchiver.evt_imageInOODS.attach_mock(
                unittest.mock.Mock(),
                "flush",
            )
            self.script.latiss.take_engtest = unittest.mock.AsyncMock(
                return_value=self.find_offset_image_id
            )

            self.script.find_offset = unittest.mock.AsyncMock(
                return_value=self.find_offset_return_value
            )

            self.script.atcs.offset_xy = unittest.mock.AsyncMock()
            self.script.atcs.add_point_data = unittest.mock.AsyncMock()

            await self.script.center_on_brightest_source()

            self.assert_center_on_brightest_source()

    def assert_center_on_brightest_source(self):

        self.script.latiss.rem.atarchiver.evt_imageInOODS.flush.assert_called_once()

        take_engtest_calls = [
            unittest.mock.call(exptime=self.script.config.exposure_time, n=1),
            unittest.mock.call(exptime=self.script.config.exposure_time, n=1),
        ]

        self.script.latiss.rem.atarchiver.evt_imageInOODS.next.assert_awaited_once_with(
            flush=False, timeout=self.script.image_in_oods_timeout
        )

        self.script.latiss.take_engtest.assert_has_awaits(take_engtest_calls)

        self.script.find_offset.assert_awaited_once_with(
            image_id=self.find_offset_image_id[0]
        )

        self.script.atcs.offset_xy.assert_awaited_once_with(
            x=self.find_offset_return_value[0], y=self.find_offset_return_value[1]
        )

        self.script.atcs.add_point_data.assert_awaited_once()

    async def set_test_configuration(self):

        test_configuration = dict(
            nside=3,
            azimuth_origin=-265,
            elevation_minimum=20.0,
            elevation_maximum=80.0,
            magnitude_limit=9.0,
            datapath=DATAPATH,
            exposure_time=1.0,
        )

        await self.configure_script(**test_configuration)

        return test_configuration

    @contextlib.asynccontextmanager
    async def make_configured_dry_script(self):
        """Construct script without remotes.

        This is useful for developing fast unit tests for methods that do not
        require DDS communication or when mocking the remote's behavior.
        """

        self.remotes_needed = False
        async with self.make_script():

            test_configuration = await self.set_test_configuration()

            yield test_configuration
