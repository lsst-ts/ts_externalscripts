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

import asyncio
import logging
import types
import unittest

import numpy as np
from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.tma import RandomWalk
from lsst.ts.idl.enums import Script


class TestRandomWalk(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    @classmethod
    def setUpClass(cls) -> None:
        cls.log = logging.getLogger(__name__)
        cls.log.propagate = True

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make_script")
        self.script = RandomWalk(index=index, remotes=False)
        self.script._mtcs.disable_checks_for_components = unittest.mock.Mock()

        self.log.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def get_telemetry(self, *args, **kwargs):
        self.log.debug(f"get_telemetry called with {args=} {kwargs=}")
        await asyncio.sleep(0.1)

        actual_position = 0.1 * np.random.rand()
        self.log.debug(f"{actual_position=}")
        return types.SimpleNamespace(actualPosition=actual_position)

    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 3600.0

            await self.configure_script(total_time=total_time)

            assert self.script.config.total_time == total_time

    async def test_configure_ignore(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 3600.0
            components = ["mtptg", "no_comp"]

            await self.configure_script(total_time=total_time, ignore=components)

            self.script._mtcs.disable_checks_for_components.assert_called_once_with(
                components=components
            )

    async def test_run(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 1.0
            await self.configure_script(total_time=total_time)

            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Add some mocks
            self.log.info("Setting up mocks")
            self.script._mtcs.rem.mtmount = unittest.mock.AsyncMock()
            self.script._mtcs.rem.mtmount.configure_mock(
                **{
                    "tel_azimuth.aget.side_effect": self.get_telemetry,
                    "tel_elevation.aget.side_effect": self.get_telemetry,
                }
            )

            # Mock the slew_and_track method
            self.script.slew_and_track = unittest.mock.AsyncMock()

            # Run the script
            self.log.debug("Running script")
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tma" / "random_walk.py"
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)

    async def test_get_azel_random_walk(self):
        async with self.make_script():
            self.log.info("Setting up mocks")
            self.script._mtcs.rem.mtmount = unittest.mock.AsyncMock()
            self.script._mtcs.rem.mtmount.configure_mock(
                **{
                    "tel_azimuth.aget.side_effect": self.get_telemetry,
                    "tel_elevation.aget.side_effect": self.get_telemetry,
                }
            )

            await self.configure_script(
                total_time=2.0,
                track_for=0.5,
                # We want only the 3.5 deg offsets for this test
                big_offset_prob=0.0,
            )

            async for data in self.script.get_azel_random_walk():
                self.log.debug(f"{data=}")
                await asyncio.sleep(0.5)
