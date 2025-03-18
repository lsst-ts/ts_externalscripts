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
from lsst.ts.externalscripts.maintel.tma import ShortLongSlews


class TestShortLongSlews(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = ShortLongSlews(index=index)
        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            # Mock the mtcs component
            self.script.mtcs = AsyncMock()
            self.script.mtcs.components_attr = ["mtm1m3"]
            # Mock the mtcs.check object
            self.script.mtcs.disable_checks_for_components = MagicMock()

            yield

    async def test_config_ignore(self) -> None:
        async with self.make_dry_script():
            grid_az = 0.0
            grid_el = 60.0
            comps_to_ignore = ["mtm1m3", "no_comp"]

            await self.configure_script(
                grid_az=grid_az, grid_el=grid_el, ignore=comps_to_ignore
            )
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                comps_to_ignore
            )

    async def test_config_directions(self) -> None:
        """Test that the direction parameter is correctly set
        and positions differ."""
        async with self.make_dry_script():
            grid_az = 30.0
            grid_el = 60.0

            # Test with direction='forward'
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
                direction="forward",
            )
            assert self.script.direction == "forward"
            positions_forward = self.script.generate_diamond_pattern(
                az0=grid_az, el0=grid_el
            )

            # Test with direction='backward'
            await self.configure_script(
                grid_az=grid_az,
                grid_el=grid_el,
                direction="backward",
            )
            assert self.script.direction == "backward"
            positions_backward = self.script.generate_diamond_pattern(
                az0=grid_az, el0=grid_el
            )

            # The positions should not be the same
            assert positions_forward != positions_backward

            # Compare the movement deltas to ensure they are opposite
            for i in range(1, len(positions_forward)):
                az_fwd_prev, el_fwd_prev = positions_forward[i - 1]
                az_fwd_curr, el_fwd_curr = positions_forward[i]
                delta_az_fwd = az_fwd_curr - az_fwd_prev
                delta_el_fwd = el_fwd_curr - el_fwd_prev

                az_bwd_prev, el_bwd_prev = positions_backward[i - 1]
                az_bwd_curr, el_bwd_curr = positions_backward[i]
                delta_az_bwd = az_bwd_curr - az_bwd_prev
                delta_el_bwd = el_bwd_curr - el_bwd_prev

                # Check that the movement deltas are opposite
                assert delta_az_fwd == pytest.approx(-delta_az_bwd)
                assert delta_el_fwd == pytest.approx(-delta_el_bwd)

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
            assert self.script.direction == "forward"  # Default value

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

            for direction in ["forward", "backward"]:
                await self.configure_script(
                    grid_az=grid_az,
                    grid_el=grid_el,
                    pause_for=pause_for,
                    move_timeout=move_timeout,
                    direction=direction,
                )

                # Mock move_to_position to prevent actual calls
                self.script.move_to_position = AsyncMock()
                # Mock checkpoint to prevent actual calls
                self.script.checkpoint = AsyncMock()

                await self.script.run_block()

                # Calculate expected number of diamond sequences and positions
                total_sequences = len(self.script.diamond_sequences)
                expected_total_positions = sum(
                    len(seq["positions"]) for seq in self.script.diamond_sequences
                )

                # Verify checkpoint messages
                assert self.script.checkpoint.call_count == total_sequences

                # Verify move_to_position calls
                assert (
                    self.script.move_to_position.await_count == expected_total_positions
                )

                # Optionally, check the specific calls
                expected_calls = []
                for sequence in self.script.diamond_sequences:
                    for position in sequence["positions"]:
                        expected_calls.append(
                            unittest.mock.call(position[0], position[1])
                        )
                self.script.move_to_position.assert_has_awaits(expected_calls)

                # Reset mocks for the next iteration
                self.script.move_to_position.reset_mock()
                self.script.checkpoint.reset_mock()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tma" / "short_long_slews.py"
        await self.check_executable(script_path)
