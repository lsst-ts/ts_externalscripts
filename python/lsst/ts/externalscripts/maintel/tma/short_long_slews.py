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

__all__ = ["ShortLongSlews"]

import asyncio

import yaml
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.salobj import type_hints
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.xml.enums.Script import ScriptState


class ShortLongSlews(BaseBlockScript):
    """Execute short and long slews for a grid of azimuths and elevations.

    Overview:

    This script performs short and long telescope slews, initially moving
    the telescope in single directions with azimuth short/long slews first,
    followed by elevation slews, and then combining both azimuth and elevation
    movements. It is designed for dynamic tests and performance evaluations,
    reproducing patterns used in specific engineering tasks like BLOCK-T293
    and T294.

    Execution Order:

    For each azimuth value specified in `grid_az`, the script sequentially
    performs a complete set of short and long slew maneuvers, as described
    above, for every elevation value in `grid_el`. In other words, the
    telescope executes all defined slew movements (both single + combined
    directions) for all elevation values before moving on to the next azimuth
    value.

    User Guidance:

    - Grid Selection: Choose `grid_az` and `grid_el` values within the
      telescope's operational limits. Ensure that cumulative movements
      from the slews do not exceed these limits.
    - Direction Control: Use the `direction` parameter to specify the initial
      movement direction of the slew. This is particularly useful when starting
      near operational limits (e.g., high elevations), as it allows you to
      avoid exceeding those limits by moving in the opposite direction.
    - Operational Limits: Azimuth: -180° to +180°, Elevation: 15° to 86°.
    """

    def __init__(self, index: int) -> None:
        super().__init__(index, descr="Execute a sequence of short and long slews.")
        self.mtcs = None
        self.grid = dict()
        self.pause_for = 0.0
        self.move_timeout = 120.0
        self.direction = "forward"  # Default direction

        # Slews definitions
        self.AZ_LONG_SLEW = 24  # deg
        self.AZ_SHORT_SLEW = 3.5  # deg
        self.EL_LONG_SLEW = 12  # deg
        self.EL_SHORT_SLEW = 3.5  # deg

        self.EL_DIAG = 0.5
        self.AZ_DIAG = (1 - self.EL_DIAG**2) ** 0.5

        # Telescope limits
        self.max_el = 86.0
        self.min_el = 15
        self.max_az = 180
        self.min_az = -180

        # This will hold all the precomputed diamond sequences
        self.diamond_sequences = []

    async def configure_tcs(self) -> None:
        """Initialize the MTCS component if not already done."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain, intended_usage=MTCSUsages.Slew, log=self.log
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    @classmethod
    def get_schema(cls):
        # You can retain or update the schema as before
        schema_yaml = """
        $schema: http://json-schema.org/draft-07/schema#
        title: ShortLongSlews Configuration
        type: object
        properties:
            grid_az:
                description: >-
                  Azimuth coordinate(s) in degrees representing the starting point for the short
                  and long slews sequence. It can be a single number or a list of numbers. Ensure
                  that the azimuth values, along with the cumulative offsets from the slews, remain
                  within the telescope's operational limits.
                anyOf:
                  - type: number
                  - type: array
                    items:
                      type: number
                minItems: 1
            grid_el:
                description: >-
                  Elevation coordinate(s) in degrees representing the starting point for the short
                  and long slews sequence. It can be a single number or a list of numbers. Ensure
                  that the elevation values, along with the cumulative offsets from the slews, remain
                  within the telescope's operational limits.
                anyOf:
                  - type: number
                  - type: array
                    items:
                      type: number
                minItems: 1
            direction:
                description: >-
                  Direction in which to start the slews. Options are 'forward' or 'backward'.
                  In 'forward' mode, the pattern starts with positive offsets; in 'backward'
                  mode, it starts with negative offsets. Default is 'forward'.
                type: string
                enum:
                  - forward
                  - backward
                default: forward
            pause_for:
               description: Pause duration between movements in seconds.
               type: number
               default: 0.0
            move_timeout:
                description: Timeout for each move command.
                type: number
                default: 120.0
            ignore:
                description: >-
                  CSCs from the group to ignore in status check. Name must match
                  those in self.group.components, e.g.; hexapod_1.
                type: array
                items:
                    type: string
        required:
            - grid_az
            - grid_el
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configures the script based on user-defined grid and settings."""

        # Ensure grid_az and grid_el are arrays
        grid_az = (
            config.grid_az if isinstance(config.grid_az, list) else [config.grid_az]
        )
        grid_el = (
            config.grid_el if isinstance(config.grid_el, list) else [config.grid_el]
        )

        self.grid["azel"] = dict(az=grid_az, el=grid_el)
        self.pause_for = config.pause_for
        self.move_timeout = config.move_timeout
        self.direction = config.direction  # Read the direction property

        # Generate and validate all positions
        self.generate_and_validate_positions()

        await self.configure_tcs()
        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(config.ignore)

        await super().configure(config=config)

    def set_metadata(self, metadata: type_hints.BaseMsgType) -> None:
        """Set the estimated duration based on the number of positions."""
        num_positions = sum(len(seq["positions"]) for seq in self.diamond_sequences)
        estimated_duration = num_positions * (self.move_timeout + self.pause_for)
        metadata.duration = estimated_duration

    def generate_diamond_pattern(self, az0, el0):
        """
        Generate a diamond pattern of azimuth and elevation coordinates
        with short and long slews. Notice that the short and long slews
        are executed first in single direction (az first, el then) and
        then combined in diagonal movements.

        Parameters:
        az0 (float): Initial azimuth coordinate.
        el0 (float): Initial elevation coordinate.

        Returns:
        - `positions` (list of tuple):  List of positions forming
           a kind of a diamond pattern with short and long slews.

        Pattern Details:
        - The pattern consists of cumulative movements starting from the
          initial position `(az0, el0)`.
        - Movements include long and short slews in azimuth and elevation,
          as well as diagonal movements.
        - The sequence is designed to test the telescope's dynamic performance.
        - The `direction` parameter controls whether the pattern starts
          with positive or negative offsets.

        Notes:
        - When `direction` is set to `'backward'`, all movement offsets are
          reversed, allowing the pattern to start in the opposite direction.
        - This is useful for avoiding telescope limits when starting near the
          operational boundaries.
        - The diamond pattern created here aims to reproduce the pattern used
          for dynamic tests done under T293 abd T294
        """

        # Define the slew offsets for the diamond pattern to match dynamic
        # tests done under T293, T294
        azel_slew_offsets = [
            (0, 0),
            (0, +self.EL_LONG_SLEW),
            (0, -self.EL_LONG_SLEW),
            (+self.AZ_LONG_SLEW, 0),
            (-self.AZ_LONG_SLEW, 0),
            (0, +self.EL_SHORT_SLEW),
            (0, -self.EL_SHORT_SLEW),
            (+self.AZ_SHORT_SLEW, 0),
            (-self.AZ_SHORT_SLEW, 0),
            (+self.AZ_LONG_SLEW / 2 * self.AZ_DIAG, +self.EL_LONG_SLEW * self.EL_DIAG),
            (-self.AZ_LONG_SLEW / 2 * self.AZ_DIAG, +self.EL_LONG_SLEW * self.EL_DIAG),
            (-self.AZ_LONG_SLEW / 2 * self.AZ_DIAG, -self.EL_LONG_SLEW * self.EL_DIAG),
            (+self.AZ_LONG_SLEW / 2 * self.AZ_DIAG, -self.EL_LONG_SLEW * self.EL_DIAG),
            (+self.AZ_SHORT_SLEW * self.AZ_DIAG, +self.EL_SHORT_SLEW * self.EL_DIAG),
            (-self.AZ_SHORT_SLEW * self.AZ_DIAG, +self.EL_SHORT_SLEW * self.EL_DIAG),
            (-self.AZ_SHORT_SLEW * self.AZ_DIAG, -self.EL_SHORT_SLEW * self.EL_DIAG),
            (+self.AZ_SHORT_SLEW * self.AZ_DIAG, -self.EL_SHORT_SLEW * self.EL_DIAG),
        ]

        # Adjust offsets based on the specified direction
        if self.direction == "backward":
            azel_slew_offsets = [
                (-az_offset, -el_offset) for az_offset, el_offset in azel_slew_offsets
            ]

        az = az0
        el = el0
        positions = []
        for az_offset, el_offset in azel_slew_offsets:
            az += az_offset
            el += el_offset
            positions.append((round(az, 2), round(el, 2)))
        return positions

    def generate_and_validate_positions(self):
        """
        Generate all positions for the grid points and their diamond patterns,
        validate them, and store them for later use.
        """

        for az0 in self.grid["azel"]["az"]:
            for el0 in self.grid["azel"]["el"]:
                positions = self.generate_diamond_pattern(az0, el0)
                for az, el in positions:
                    if not (self.min_az <= az <= self.max_az):
                        raise ValueError(
                            f"Azimuth {az} out of limits ({self.min_az}, {self.max_az}). "
                            f"Ensure that the entire movement range stays within the "
                            f"allowed azimuth limits. Adjust initial azimuth (Az = {az0}) "
                            f"in your grid accordingly."
                        )
                    if not (self.min_el <= el <= self.max_el):
                        raise ValueError(
                            f"Elevation {el} out of limits ({self.min_el}, {self.max_el}). "
                            f"Ensure that the entire movement range stays within the allowed "
                            f"elevation limits. Adjust initial elevation (El = {el0}) in your "
                            f"grid accordingly."
                        )
                # Add the sequence to the list
                self.diamond_sequences.append(
                    {"az0": az0, "el0": el0, "positions": positions}
                )

    async def move_to_position(self, az, el):
        """Move the telescope to the specified azimuth and elevation."""
        await self.mtcs.move_p2p_azel(az=az, el=el, timeout=self.move_timeout)

    async def run_block(self):
        """Execute the precomputed positions."""
        total_diamonds = len(self.diamond_sequences)
        for i, sequence in enumerate(self.diamond_sequences):
            az0 = sequence["az0"]
            el0 = sequence["el0"]
            positions = sequence["positions"]
            # Output checkpoint message
            await self.checkpoint(
                f"Starting sequence {i+1}/{total_diamonds} at grid point (Az={az0}, El={el0})"
            )
            total_positions = len(positions)
            for j, (az, el) in enumerate(positions, start=1):
                self.log.info(
                    f"Moving to position {j}/{total_positions} of grid sequence {i+1}: Az={az}, El={el}"
                )
                await self.move_to_position(az, el)
                self.log.info(f"Pausing for {self.pause_for}s.")
                await asyncio.sleep(self.pause_for)

    async def cleanup(self):
        """Handle cleanup in case of abnormal termination."""
        if self.state.state != ScriptState.ENDING:
            self.log.warning("Terminating abnormally, stopping telescope.")
            try:
                await self.mtcs.rem.mtmount.cmd_stop.start(
                    timeout=self.mtcs.long_timeout
                )
            except asyncio.TimeoutError:
                self.log.exception("Stop command timed out during cleanup.")
            except Exception:
                self.log.exception("Unexpected error during telescope stop.")
