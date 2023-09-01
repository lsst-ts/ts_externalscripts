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
from lsst.ts.externalscripts.maintel.tma import RandomWalkAndTakeImagesGenCam
from lsst.ts.idl.enums import Script
from lsst.ts.observatory.control.utils import RotType


class TestRandomWalkAndTakeImagesGenCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    @classmethod
    def setUpClass(cls) -> None:
        cls.log = logging.getLogger(__name__)
        cls.log.propagate = True

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make_script")
        self.script = RandomWalkAndTakeImagesGenCam(index=index, add_remotes=False)

        self.log.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def configure_script_full(self):
        configuration_full = dict(
            total_time=60.0,
            radius=3.55,
            min_az=-202,
            max_az=201,
            min_el=19,
            max_el=81,
            big_offset_prob=0.11,
            big_offset_radius=8.99,
            track_for=32.1,
            stop_when_done=True,
            ignore=["mtaos"],
            rot_value=0.01,
            rot_type="Physical",
            az_wrap_strategy=2,
            camera_sal_indexes=[1, 2],
            exp_times=[0.1, 0.2],
            sleep_time=0.1,
        )

        await self.configure_script(**configuration_full)

        return configuration_full

    async def get_telemetry(self, *args, **kwargs):
        self.log.debug(f"get_telemetry called with {args=} {kwargs=}")
        await asyncio.sleep(0.1)

        actual_position = 0.1 * np.random.rand()
        self.log.debug(f"{actual_position=}")
        return types.SimpleNamespace(actualPosition=actual_position)

    async def get_dome_telemetry(self, *args, **kwargs):
        self.log.debug(f"get_dome_telemetry called with {args=} {kwargs=}")
        await asyncio.sleep(0.1)

        actual_position = 0.1 * np.random.rand()
        self.log.debug(f"{actual_position=}")
        return types.SimpleNamespace(positionActual=actual_position)

    async def test_configure(self):
        async with self.make_script():
            # Try configure with minimum set of parameters declared
            # Note that all are scalars and should be converted to arrays
            total_time = 3600.0
            camera_sal_indexes = [0, 1]
            exp_times = [1, 2]

            await self.configure_script(
                total_time=total_time,
                camera_sal_indexes=camera_sal_indexes,
                exp_times=exp_times,
            )

            assert self.script.config.camera_sal_indexes == camera_sal_indexes
            assert self.script.config.exp_times == exp_times
            assert self.script.config.total_time == total_time
            assert len(self.script.gencam_list) == len(camera_sal_indexes)

    async def test_configure_good(self):
        async with self.make_script():
            configuration_full = await self.configure_script_full()
            for key in configuration_full:
                if key != "rot_type":
                    assert configuration_full[key] == getattr(self.script.config, key)
                else:
                    assert getattr(RotType, configuration_full[key]) == getattr(
                        self.script.config, key
                    )

    async def test_executable(self):
        script_name = "random_walk_and_take_image_gencam.py"
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tma" / script_name
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)

    async def test_run(self):
        async with self.make_script():
            total_time = 3600.0
            camera_sal_indexes = [0, 1]
            exp_times = [1, 2]

            await self.configure_script(
                total_time=total_time,
                camera_sal_indexes=camera_sal_indexes,
                exp_times=exp_times,
            )

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

            self.script._mtcs.rem.mtdome = unittest.mock.AsyncMock()
            self.script._mtcs.rem.mtdome.configure_mock(
                **{
                    "cmd_exitFault.set_start.side_effect": unittest.mock.AsyncMock(),
                    "tel_azimuth.next": self.get_dome_telemetry,
                }
            )

            self.script.slew_and_track = unittest.mock.AsyncMock()

            # Run the script
            self.log.debug("Running script")
            await self.run_script()
            assert self.script.state.state == Script.ScriptState.DONE
