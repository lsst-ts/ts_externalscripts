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

import contextlib
import types
import unittest
import unittest.mock

import numpy as np
from lsst.ts import salobj
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.base_build_pointing_model import (
    GridType,
    generate_rotator_sequence,
)
from lsst.ts.externalscripts.maintel.build_pointing_model import (
    BuildPointingModel,
)
from lsst.ts.standardscripts import BaseScriptTestCase


class TestBuildPointingModel(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.remotes_needed = True

    async def basic_make_script(self, index):
        self.script = BuildPointingModel(index=index, remotes=self.remotes_needed)

        return (self.script,)

    def assert_config(self, configuration):
        self.check_configuration_values(configuration)
        self.check_azel_grid()
        self.check_rotator_gen()

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

        if self.script.config.grid == GridType.RADEC.name:
            # We expect at least one point in the grid is rejected because of
            # high elevation.
            # This is why we subtract one from the number of points in the grid
            # below.
            expected_size = np.sum(self.script.config.radec_grid["ha_grid"]["n"]) - 1
            assert len(self.script.elevation_grid) == expected_size

    def check_rotator_gen(self):
        expected_next_rot_seq = self.script.config.rotator_sequence

        self._check_rotator_sequence(expected_next_rot_seq, reverse=False)

        expected_next_rot_seq = self.script.config.rotator_sequence[:-1:][::-1]

        self._check_rotator_sequence(expected_next_rot_seq, reverse=True)

        expected_next_rot_seq = self.script.config.rotator_sequence[1::]

        self._check_rotator_sequence(expected_next_rot_seq, reverse=False)

    def _check_rotator_sequence(self, expected_next_rot_seq, reverse):
        for rot_grid_expected, rot_grid_gen in zip(
            expected_next_rot_seq, self.script.rotator_sequence_gen
        ):
            with self.subTest(rot_grid_expected=rot_grid_expected):
                for rot_expected, rot_gen in zip(
                    rot_grid_expected if not reverse else rot_grid_expected[::-1],
                    rot_grid_gen,
                ):
                    assert rot_expected == rot_gen

    def assert_metadata(self, metadata):
        assert metadata.nimages == len(self.script.elevation_grid) * 2
        assert metadata.duration == metadata.nimages * (
            self.script.config.exposure_time
            + self.script.camera_readout_time
            + self.script.estimated_average_slew_time
        )

    async def test_configure_use_healpix_grid(self):
        async with self.make_configured_dry_script(
            grid=GridType.HEALPIX
        ) as test_configuration:
            self.assert_config(test_configuration)

    async def test_configure_use_radec_grid(self):
        async with self.make_configured_dry_script(
            grid=GridType.RADEC
        ) as test_configuration:
            self.assert_config(test_configuration)

    async def test_configure_skip(self):
        async with self.make_configured_dry_script(
            grid=GridType.RADEC,
            skip=10,
        ) as test_configuration:
            self.assert_config(test_configuration)

    async def test_configure_fails(self):
        self.remotes_needed = False
        bad_config = [
            dict(grid="this_is_a_typo"),
            dict(healpix_grid=dict(nside=0)),
            dict(radec_grid=dict(dec_grid=dict(min=-100))),
            dict(radec_grid=dict(dec_grid=dict(max=100))),
            dict(radec_grid=dict(dec_grid=dict(n=1))),
            dict(radec_grid=dict(ha_grid=dict(min=-14))),
            dict(radec_grid=dict(ha_grid=dict(max=14))),
            dict(radec_grid=dict(ha_grid=dict(n=[]))),
            dict(grid="radec", radec_grid=dict(ha_grid=dict(n=[3, 5, 6]))),
        ]
        for config in bad_config:
            with self.subTest(config=config), self.assertRaises(salobj.ExpectedError):
                async with self.make_script():
                    await self.configure_script(**config)

    async def test_metadata(self):
        async with self.make_configured_dry_script(grid=GridType.HEALPIX):
            metadata = types.SimpleNamespace(
                duration=0.0,
                nimages=0,
            )

            self.script.set_metadata(metadata)

            self.assert_metadata(metadata)

    async def test_executable(self):
        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "maintel" / "build_pointing_model.py"
        await self.check_executable(script_path)

    async def test_arun(self):
        async with self.make_configured_dry_script(grid=GridType.HEALPIX):
            self.script.execute_grid = unittest.mock.AsyncMock()

            await self.script.arun()

            self.assert_arun()

    async def test_arun_skip_some(self):
        async with self.make_configured_dry_script(grid=GridType.HEALPIX, skip=10):
            self.script.execute_grid = unittest.mock.AsyncMock()

            await self.script.arun()

            self.assert_arun()

    def assert_arun(self):
        rot_seq_gen = generate_rotator_sequence(self.script.config.rotator_sequence)

        expected_execute_grid_calls = []

        grid_index = range(len(self.script.azimuth_grid))
        for index, azimuth, elevation, rot_seq in zip(
            grid_index,
            self.script.azimuth_grid,
            self.script.elevation_grid,
            rot_seq_gen,
        ):
            if index < self.script.config.skip:
                continue
            for rot in rot_seq:
                expected_execute_grid_calls.append(
                    unittest.mock.call(azimuth, elevation, rot)
                )

        assert self.script.execute_grid.await_count == len(expected_execute_grid_calls)
        self.script.execute_grid.assert_has_awaits(expected_execute_grid_calls)

    async def test_execute_grid(self):
        async with self.make_configured_dry_script(grid=GridType.HEALPIX):
            azimuth, elevation, rotator = (
                self.script.azimuth_grid[0],
                self.script.elevation_grid[0],
                np.random.rand(),
            )

            target_name = "HD 12345"

            self.script.tcs.find_target = unittest.mock.AsyncMock(
                return_value=target_name
            )
            self.script.tcs.slew_object = unittest.mock.AsyncMock()
            self.script.center_on_brightest_source = unittest.mock.AsyncMock()

            await self.script.execute_grid(
                azimuth=azimuth, elevation=elevation, rotator=rotator
            )

            self.assert_execute_grid(
                azimuth=azimuth,
                elevation=elevation,
                rotator=rotator,
                target_name=target_name,
            )

    def assert_execute_grid(self, azimuth, elevation, rotator, target_name):
        self.script.tcs.point_azel.assert_awaited_once_with(
            az=azimuth,
            el=elevation,
            rot_tel=rotator,
        )
        self.script.tcs.start_tracking.assert_awaited_once()
        self.script.center_on_brightest_source.assert_awaited()
        assert self.script.iterations["failed"] == 0
        assert self.script.iterations["successful"] == 1

    def assert_execute_grid_fail(self, azimuth, elevation):
        self.script.tcs.find_target.assert_awaited_once_with(
            az=azimuth,
            el=elevation,
            mag_limit=self.script.config.magnitude_limit,
            mag_range=self.script.config.magnitude_range,
        )
        self.script.tcs.slew_object.assert_not_awaited()
        self.script.center_on_brightest_source.assert_not_awaited()
        assert self.script.iterations["failed"] == 1
        assert self.script.iterations["successful"] == 0

    async def test_center_on_brightest_source(self):
        async with self.make_configured_dry_script(grid=GridType.HEALPIX):
            self.script.camera.take_acq = unittest.mock.AsyncMock()

            await self.script.center_on_brightest_source()

            self.assert_center_on_brightest_source()

    def assert_center_on_brightest_source(self):
        take_acq_calls = [
            unittest.mock.call(
                exptime=self.script.config.exposure_time,
                n=1,
                group_id=self.script.group_id,
                reason="PtgModel",
                program="MTPTMODEL",
            ),
        ]

        self.script.camera.take_acq.assert_has_awaits(take_acq_calls)

    async def set_test_configuration(self, grid, **kwargs):
        test_configuration = self._generate_configuration(grid=grid, **kwargs)

        await self.configure_script(**test_configuration)

        return test_configuration

    def _generate_configuration(self, grid, **kwargs):
        """Generate configuration.

        Parameters
        ----------
        grid : `str`
            Grid name,

        Returns
        -------
        configuration : `dict`
            Script configuration.
        """
        configuration = dict(
            grid=grid.name.lower(),
            elevation_minimum=20.0,
            elevation_maximum=80.0,
            magnitude_limit=9.0,
            exposure_time=1.0,
        )
        configuration.update(**kwargs)

        return configuration

    @contextlib.asynccontextmanager
    async def make_configured_dry_script(self, grid, **kwargs):
        """Construct script without remotes with healpix grid configuration.

        This is useful for developing fast unit tests for methods that do not
        require DDS communication or when mocking the remote's behavior.

        Parameters
        ----------
        grid : `str
            Which grid to configure the the script for.
        """
        self.remotes_needed = False
        async with self.make_script():
            test_configuration = await self.set_test_configuration(grid=grid, **kwargs)

            self.script.tcs.rem.mtptg = unittest.mock.AsyncMock()
            self.script.tcs.rem.mtptg.configure_mock(
                **{
                    "evt_summaryState.aget.return_value": types.SimpleNamespace(
                        summaryState=salobj.State.ENABLED
                    )
                }
            )
            self.script.tcs.point_azel = unittest.mock.AsyncMock()
            self.script.tcs.start_tracking = unittest.mock.AsyncMock()

            yield test_configuration
