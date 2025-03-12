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
import os
import tempfile
import unittest
import unittest.mock

import numpy as np
from lsst.daf import butler as dafButler
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.auxtel.correct_pointing import CorrectPointing
from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.standardscripts import BaseScriptTestCase
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


class TestCorrectPointing(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.remotes_needed = True

    async def basic_make_script(self, index):
        self.script = CorrectPointing(index=index, remotes=self.remotes_needed)
        self.script.atcs = ATCS(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=ATCSUsages.DryTest,
        )
        self.script.latiss = LATISS(
            domain=self.script.domain,
            log=self.script.log,
            intended_usage=LATISSUsages.DryTest,
        )

        # Mock the method that returns the BestEffortIsr class if it is
        # not available for import
        self.script.get_best_effort_isr = unittest.mock.Mock()

        return (self.script,)

    async def test_executable(self):
        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "correct_pointing.py"
        await self.check_executable(script_path)

    async def test_configure(self):
        configs_good = [
            dict(),
            dict(az=100.0),
            dict(el=45.0),
            dict(mag_limit=9.0),
            dict(radius=1.0),
            dict(filter="SDSSr_65mm"),
        ]

        self.remotes_needed = False
        async with self.make_script():
            default_values = dict(
                az=self.script.azimuth,
                el=self.script.elevation,
                radius=self.script.radius,
                mag_limit=self.script.magnitude_limit,
                mag_range=self.script.magnitude_range,
                filter=self.script.filter,
            )
            for config in configs_good:
                await self.configure_script(**config)

                self.assert_config(default_values, config)

    async def test_check_center(self):
        self.remotes_needed = False
        async with self.make_script():
            self.script.find_offset = unittest.mock.AsyncMock(
                return_value=(np.nan, np.nan)
            )
            self.script.latiss.take_acq = unittest.mock.AsyncMock(return_value=([1, 2]))
            self.script.latiss.rem.atoods = unittest.mock.AsyncMock()
            self.script.atcs.offset_xy = unittest.mock.AsyncMock()

            with self.assertRaises(RuntimeError):
                await self.script._center()
            self.script.atcs.offset_xy.assert_not_awaited()

    def assert_config(self, default_values, config):
        configured_values = dict(
            az=self.script.azimuth,
            el=self.script.elevation,
            radius=self.script.radius,
            mag_limit=self.script.magnitude_limit,
            mag_range=self.script.magnitude_range,
            filter=self.script.filter,
        )

        for parameter in default_values:
            with self.subTest(config=config, parameter=parameter):
                assert (
                    config.get(parameter, default_values.get(parameter))
                    == configured_values[parameter]
                )

    @contextlib.asynccontextmanager
    async def make_configured_dry_script(self):
        """Construct script without remotes.

        This is useful for developing fast unit tests for methods that do not
        require DDS communication or when mocking the remote's behavior.
        """
        self.remotes_needed = False
        async with self.make_script():
            self.script.atcs.rem.ataos = unittest.mock.AsyncMock()
            self.script.atcs.rem.atptg = unittest.mock.AsyncMock()
            self.script.latiss.rem.atspectrograph = unittest.mock.AsyncMock()

            await self.configure_script()

            yield
