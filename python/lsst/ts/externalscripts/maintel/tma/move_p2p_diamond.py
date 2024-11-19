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

__all__ = ["MoveP2PDiamond"]

import asyncio

import yaml
from lsst.ts.idl.enums.Script import ScriptState
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.salobj import type_hints
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


class MoveP2PDiamond(BaseBlockScript):
    """Moves the telescope in a diamond pattern around each grid position.

    Overview:

    This script performs a series of point-to-point (P2P) telescope
    movements forming a diamond pattern around each user-defined grid
    position. It is designed for dynamic tests and performance evaluations,
    reproducing patterns used in specific engineering tasks (e.g., BLOCK-T227,
    T293, T294).

    Execution Order:

    The script processes the grid positions by iterating over `grid_az`
    first, then `grid_el`. For each azimuth value in `grid_az`, it executes
    the diamond patterns at all elevation values in `grid_el` in order.

    User Guidance:

    - Grid Selection: Choose `grid_az` and `grid_el` values within the
      telescope's operational limits. Ensure that cumulative movements
      from the diamond pattern do not exceed these limits.
    - Understanding the Pattern: The diamond pattern consists of cumulative
      offsets applied to the initial position. Familiarity with the pattern
      helps in anticipating telescope movements.
    - Operational Limits: Azimuth: -180° to +180°, Elevation: 15° to 86.5°.
    """

    def __init__(self, index: int) -> None:
        super().__init__(index, descr="Move telescope in diamond pattern around grid.")
        self.mtcs = None
        self.grid = dict()
        self.pause_for = 0.0
        self.move_timeout = 120.0

        self.LONG_SLEW_AZ = 24.0  # degrees
        self.LONG_SLEW_EL = 12.0  # degrees
        self.SHORT_SLEW_AZ = 3.5  # degrees
        self.SHORT_SLEW_EL = 3.5  # degrees

        # Telescope limits
        self.max_el = 86.5
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
        title: MoveDiamondPattern Configuration
        type: object
        properties:
            grid_az:
                description: >
                  Azimuth coordinate(s) in degrees where the diamond patterns will be executed.
                  Can be a single number or a list of numbers. Ensure that the azimuth values,
                  along with the cumulative offsets from the diamond pattern, remain within
                  the telescope's operational limits.
                anyOf:
                  - type: number
                  - type: array
                    items:
                      type: number
                minItems: 1
            grid_el:
                description: >
                  Elevation coordinate(s) in degrees where the diamond patterns will be executed.
                  Can be a single number or a list of numbers. Ensure that the elevation values,
                  along with the cumulative offsets from the diamond pattern, remain within
                  the telescope's operational limits
                anyOf:
                  - type: number
                  - type: array
                    items:
                      type: number
                minItems: 1
            pause_for:
               description: Pause duration between movements in seconds.
               type: number
               default: 0.0
            move_timeout:
                description: Timeout for each move command.
                type: number
                default: 120.0
            ignore:
                description: CSCs to ignore in status check.
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

        # Generate and validate all positions
        self.generate_and_validate_positions()

        await self.configure_tcs()
        for comp in getattr(config, "ignore", []):
            if comp not in self.mtcs.components_attr:
                self.log.warning(f"Ignoring unknown component {comp}.")
            else:
                self.log.debug(f"Ignoring component {comp}.")
                setattr(self.mtcs.check, comp, False)

        await super().configure(config=config)

    def set_metadata(self, metadata: type_hints.BaseMsgType) -> None:
        """Set the estimated duration based on the number of positions."""
        num_positions = sum(len(seq["positions"]) for seq in self.diamond_sequences)
        estimated_duration = num_positions * (self.move_timeout + self.pause_for)
        metadata.duration = estimated_duration

    def generate_diamond_pattern(self, az0, el0):
        """
        Generate a diamond pattern of azimuth and elevation coordinates.

        Parameters:
        az0 (float): Initial azimuth coordinate.
        el0 (float): Initial elevation coordinate.

        Returns:
        - `positions` (list of tuple):  List of positions forming
           the diamond patterns.

        Pattern Details:
        - The pattern consists of cumulative movements starting from the
          initial position `(az0, el0)`.
        - Movements include long and short slews in azimuth and elevation,
          as well as diagonal movements.
        - The sequence is designed to test the telescope's dynamic performance.

        Notes:
        The diamond pattern created here aims to reproduce the pattern used
        for dynamic tests done under BLOCK-T227, T293 abd T294
        """

        # Define the slew offsets for the diamond pattern to match dynamic
        # tests done under BLOCK-T227, T293, T294
        azel_slew_offsets = [
            (0, 0),
            (0, +self.LONG_SLEW_EL),
            (0, -self.LONG_SLEW_EL),
            (+self.LONG_SLEW_AZ, 0),
            (-self.LONG_SLEW_AZ, 0),
            (0, +self.SHORT_SLEW_EL),
            (0, -self.SHORT_SLEW_EL),
            (+self.SHORT_SLEW_AZ, 0),
            (-self.SHORT_SLEW_AZ, 0),
            (+self.LONG_SLEW_AZ / 2 / (2**0.5), +self.LONG_SLEW_EL / (2**0.5)),
            (-self.LONG_SLEW_AZ / 2 / (2**0.5), +self.LONG_SLEW_EL / (2**0.5)),
            (-self.LONG_SLEW_AZ / 2 / (2**0.5), -self.LONG_SLEW_EL / (2**0.5)),
            (+self.LONG_SLEW_AZ / 2 / (2**0.5), -self.LONG_SLEW_EL / (2**0.5)),
            (+self.SHORT_SLEW_AZ / (2**0.5), +self.SHORT_SLEW_EL / (2**0.5)),
            (-self.SHORT_SLEW_AZ / (2**0.5), +self.SHORT_SLEW_EL / (2**0.5)),
            (-self.SHORT_SLEW_AZ / (2**0.5), -self.SHORT_SLEW_EL / (2**0.5)),
            (+self.SHORT_SLEW_AZ / (2**0.5), -self.SHORT_SLEW_EL / (2**0.5)),
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
        self.log.debug(f"Moving telescope to az={az}, el={el}.")
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
                f"Starting diamond sequence {i+1}/{total_diamonds} at grid point (Az={az0}, El={el0})"
            )
            total_positions = len(positions)
            for j, (az, el) in enumerate(positions, start=1):
                self.log.info(
                    f"Moving to position {j}/{total_positions} in diamond sequence {i+1}: Az={az}, El={el}"
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
