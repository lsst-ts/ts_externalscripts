# This file is part of ts_externalscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import asyncio
import logging
import types
import unittest

import pytest
from lsst.ts import externalscripts, salobj, standardscripts, utils
from lsst.ts.externalscripts.maintel.warmup_m2 import WarmUpM2
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.xml.enums import Script
from lsst.ts.xml.enums.Watcher import AlarmSeverity

index_gen = utils.index_generator()


class TestWarmUpM2(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.log.debug("Starting basic_make_script")
        self.script = WarmUpM2(index=index)
        self.script.mtcs = MTCS(
            domain=self.script.domain,
            intended_usage=MTCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.mtcs.rem.mtm2 = unittest.mock.AsyncMock()
        self.script.watcher = unittest.mock.AsyncMock()

        self.m2_in_position = types.SimpleNamespace(inPosition=True)
        self._m2_move_task = utils.make_done_future()
        self._m2_in_position_event = asyncio.Event()

        self.log.debug("Finished initializing from basic_make_script")
        # Return a single element tuple
        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            # Note that all are scalars and should be converted to arrays
            axis = "xRot"
            step_size = 5
            sleep_time = 2.0
            max_position = 50
            max_warmup_iterations = 3

            await self.configure_script(
                axis=axis,
                step_size=step_size,
                sleep_time=sleep_time,
                max_position=max_position,
                max_warmup_iterations=max_warmup_iterations,
            )

            assert self.script.config.axis == axis
            assert self.script.config.step_size == [step_size]
            assert self.script.config.sleep_time == [sleep_time]
            assert self.script.config.max_position == max_position
            assert self.script.config.max_warmup_iterations == max_warmup_iterations
            assert self.script.mtcs.check.mtm2
            assert not self.script.mtcs.check.mtmount

    async def test_configure_mismatched_steps(self):
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(step_size=[5, 10], sleep_time=[1.0])

    async def test_run(self):
        async with self.make_script():
            await self.configure_script(
                axis="z",
                step_size=20,
                sleep_time=0.1,
                max_position=100,
                max_warmup_iterations=5,
            )
            assert self.script.state.state == Script.ScriptState.CONFIGURED

            self.script.mtcs.assert_liveliness = unittest.mock.AsyncMock()
            self.script.mtcs.assert_all_enabled = unittest.mock.AsyncMock()
            self.script.move_m2 = unittest.mock.AsyncMock()
            self.script.mtcs.rem.mtm2.configure_mock(
                **{
                    "tel_position.aget.return_value": types.SimpleNamespace(
                        x=0.0, y=0.0, z=0.0, xRot=0.0, yRot=0.0, zRot=0.0
                    ),
                    "evt_m2AssemblyInPosition.next.side_effect": self.next_m2_assembly_in_position,
                    "evt_m2AssemblyInPosition.aget.side_effect": self.aget_m2_assembly_in_position,
                    "evt_m2AssemblyInPosition.flush.side_effect": self._m2_in_position_event.clear,
                    "cmd_positionMirror.set_start.side_effect": self.m2_position_mirror,
                }
            )

            await self.run_script()

            self.script.mtcs.assert_liveliness.assert_awaited_once()
            self.script.mtcs.assert_all_enabled.assert_awaited_once()
            self.script.watcher.cmd_mute.set_start.assert_awaited_with(
                name="Enabled.MTM2",
                duration=3600.0,
                severity=AlarmSeverity.CRITICAL.value,
                mutedBy="warmup_m2.py",
                timeout=60.0,
            )
            self.script.watcher.cmd_unmute.set_start.assert_awaited_with(
                name="Enabled.MTM2"
            )
            self.script.move_m2.assert_any_await(
                x=0.0, y=0.0, z=100, xRot=0.0, yRot=0.0, zRot=0.0
            )
            self.script.move_m2.assert_any_await(
                x=0.0, y=0.0, z=-100, xRot=0.0, yRot=0.0, zRot=0.0
            )
            assert self.script.state.state == Script.ScriptState.DONE

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "warmup_m2.py"
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)

    async def next_m2_assembly_in_position(self, timeout, flush):
        async with asyncio.timeout(delay=timeout):
            await self._m2_in_position_event.wait()
        return self.m2_in_position

    async def aget_m2_assembly_in_position(self, timeout, flush):
        await asyncio.sleep(1.0)
        return self.m2_in_position

    async def m2_position_mirror(self, x, y, z, xRot, yRot, zRot, timeout):
        self.m2_in_position.inPosition = False
        self._m2_move_task = asyncio.create_task(self._emulate_m2_move())

    async def _emulate_m2_move(self):
        await asyncio.sleep(2.0)
        self.m2_in_position.inPosition = True
        self._m2_in_position_event.set()
