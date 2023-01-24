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

import logging
import random
import unittest

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel import TrackTargetSched

random.seed(47)  # for set_random_lsst_dds_partition_prefix

logging.basicConfig()


class TestSlewAndTrackSched(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def assert_slew_radec(self):
        self.script.tcs.slew_icrs.assert_awaited_once()
        self.script.tcs.slew_object.assert_not_awaited()
        self.script.tcs.stop_tracking.assert_not_awaited()

    async def basic_make_script(self, index):
        self.script = TrackTargetSched(index=index)

        return (self.script,)

    async def test_configure_good(self):
        async with self.make_script():
            configuration_full = await self.configure_script_full()
            for key in configuration_full:
                assert configuration_full[key] == getattr(self.script.config, key)

    async def test_configuration_no_default(self):
        async with self.make_script():
            # Test no default configuration. User must provide something.
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script()

    async def test_run(self):

        async with self.make_script():

            self.script.tcs.slew_icrs = unittest.mock.AsyncMock()
            self.script.tcs.slew_object = unittest.mock.AsyncMock()
            self.script.tcs.stop_tracking = unittest.mock.AsyncMock()

            await self.configure_script(
                ra=1.0,
                dec=-10.0,
                rot_sky=0.0,
                name="utest",
                obs_time=1.0,
                num_exp=1,
                exp_times=[5],
                band_filter="none",
            )

            await self.run_script()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "track_target_sched.py"
        await self.check_executable(script_path)

    async def configure_script_full(self, band_filter="r", grating="empty_1"):
        configuration_full = dict(
            targetid=10,
            ra="10:00:00",
            dec="-10:00:00",
            rot_sky=0.0,
            name="unit_test_target",
            obs_time=7.0,
            estimated_slew_time=5.0,
            num_exp=2,
            exp_times=[2.0, 1.0],
            band_filter=band_filter,
            grating=grating,
            reason="Unit testing",
            program="UTEST",
        )

        await self.configure_script(**configuration_full)

        return configuration_full


if __name__ == "__main__":
    unittest.main()
