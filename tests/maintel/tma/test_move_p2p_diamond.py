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

import contextlib
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.tma import MoveP2PDiamond


class TestMoveP2PDiamond(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = MoveP2PDiamond(index=index)
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            # Mock the mtcs component
            self.script.mtcs = AsyncMock()
            self.script.mtcs.components_attr = ["mtm1m3"]
            # Mock the mtcs.check object
            self.script.mtcs.check = MagicMock()

            yield

    async def test_config_ignore(self) -> None:
        async with self.make_dry_script():
            grid_az = 0.0
            grid_el = 60.0

            await self.configure_script(
                grid_az=grid_az, grid_el=grid_el, ignore=["mtm1m3", "no_comp"]
            )
            assert self.script.mtcs.check.mtm1m3 is False
            self.script.mtcs.check.no_comp.assert_not_called()

    async def test_config_grid_az_el_scalars(self) -> None:
        async with self.make_dry_script():
            grid_az = 30.0
            grid_el = 60.0
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
            )
            assert self.script.grid["azel"]["az"] == [grid_az]
            assert self.script.grid["azel"]["el"] == [grid_el]
            assert self.script.pause_for == 0.0
            assert self.script.move_timeout == 120.0

    async def test_config_az_el_arrays(self) -> None:
        async with self.make_dry_script():
            grid_az = [30.0]
            grid_el = [45.0, 45.0, 35.0]
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
            )
            # assert config_tcs was awaited once
            assert self.script.grid["azel"]["az"] == grid_az
            assert self.script.grid["azel"]["el"] == grid_el
            assert self.script.pause_for == 0.0
            assert self.script.move_timeout == 120.0

    async def test_config_pause_for_move_timeout(self) -> None:
        async with self.make_dry_script():
            grid_az = 30.0
            grid_el = [60.0]
            pause_for = 10.0
            move_timeout = 200.0
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
                pause_for=pause_for,
                move_timeout=move_timeout,
            )
            assert self.script.pause_for == pause_for
            assert self.script.move_timeout == move_timeout

    async def test_az_outside_limits(self):
        async with self.make_dry_script():
            # Use an azimuth value beyond the maximum limit
            grid_az = self.script.max_az + 10  # Exceeds max azimuth limit
            grid_el = 60.0  # Valid elevation within limits
            with pytest.raises(
                salobj.ExpectedError, match=f"Azimuth {grid_az} out of limits"
            ):
                await self.configure_script(grid_az=grid_az, grid_el=grid_el)

    async def test_el_outside_limits(self):
        async with self.make_dry_script():
            grid_az = 30.0  # Valid azimuth within limits
            # Use an elevation value below the minimum limit
            grid_el = self.script.min_el - 5  # Below min elevation limit
            with pytest.raises(
                salobj.ExpectedError, match=f"Elevation {grid_el} out of limits"
            ):
                await self.configure_script(grid_az=grid_az, grid_el=grid_el)

    async def test_run_block(self):
        async with self.make_dry_script():
            grid_az = [-75]
            grid_el = [35.0, 55.0]
            pause_for = 1.0
            move_timeout = 120.0
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
                pause_for=pause_for,
                move_timeout=move_timeout,
            )

            # Mock move_to_position to prevent actual calls
            self.script.move_to_position = AsyncMock()
            # Mock checkpoint to prevent actual calls
            self.script.checkpoint = AsyncMock()

            await self.script.run_block()

            # Calculate expected number of diamond sequences and positions
            total_sequences = len(grid_az) * len(grid_el)
            total_positions_per_sequence = len(
                self.script.generate_diamond_pattern(0, 0)
            )
            expected_total_positions = total_sequences * total_positions_per_sequence

            # Verify checkpoint messages
            assert self.script.checkpoint.call_count == total_sequences

            # Verify move_to_position calls
            assert self.script.move_to_position.await_count == expected_total_positions

            # Optionally, check the specific calls
            expected_calls = []
            for sequence in self.script.diamond_sequences:
                for position in sequence["positions"]:
                    expected_calls.append(unittest.mock.call(position[0], position[1]))
            self.script.move_to_position.assert_has_awaits(expected_calls)

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tma" / "move_p2p_diamond.py"
        self.log.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
