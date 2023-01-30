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

import logging
import unittest

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
        self.script = RandomWalk(index=index)

        self.log.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def test_configure(self):
        async with self.make_script():

            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 3600.0

            await self.configure_script(total_time=total_time)

            assert self.script.config.total_time == total_time

    async def test_run(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 3600.0
            await self.configure_script(total_time=total_time)

            assert self.script.state.state == Script.ScriptState.CONFIGURED

            # Add some mocks
            async def foo():
                yield (0, 80)
                yield (180, 60)

            self.script.slew_and_track = unittest.mock.AsyncMock()
            self.script.random_walk_azel_by_time = unittest.mock.MagicMock()
            self.script.random_walk_azel_by_time.__aiter__.return_value = [
                (0, 80),
                (180, 60),
            ]

            # Run the script
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tma" / "random_walk.py"
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
