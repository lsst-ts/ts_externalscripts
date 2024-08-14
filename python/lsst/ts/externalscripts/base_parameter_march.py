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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["BaseParameterMarch"]

import abc
import asyncio
import types

import numpy as np
import yaml
from lsst.ts import salobj

from .base_block_script import BaseBlockScript


class BaseParameterMarch(BaseBlockScript):
    """Perform a parameter march by incrementally adjusting a
    specific combination of degrees of freedom. This process
    involves moving the parameters in specified increments
    to evaluate the system's response. The sensitivity matrix
    is an example of this technique, where the system's behavior
    is assessed by capturing data at various incremental adjustments
    for each degree of freedom.


    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    * Step 1/n_steps starting position: start_position.
    * Step n/n_steps.
    """

    def __init__(self, index, descr="Perform a parameter march.") -> None:
        super().__init__(index=index, descr=descr)

        self.ocps = None

        self.config = None

        self.total_offset = 0.0
        self.iterations_started = False

    @property
    @abc.abstractmethod
    def tcs(self):
        raise NotImplementedError()

    @abc.abstractmethod
    async def configure_tcs(self):
        """Abstract method to configure the TCS."""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    @abc.abstractmethod
    async def configure_camera(self):
        """Abstract method to configure the Camera."""
        raise NotImplementedError()

    async def configure_ocps(self):
        """Configure the OCPS remote object."""
        if self.ocps is None:
            self.log.debug("Configuring remote for OCPS:101")
            self.ocps = salobj.Remote(self.domain, "OCPS", 101)
            await self.ocps.start_task
        else:
            self.log.debug("OCPS already configured. Ignoring.")

    @classmethod
    def get_schema(cls) -> dict:
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/base_parameter_march.yaml
            title: BaseParameterMarch v1
            description: Configuration for BaseParameterMarch.
            type: object
            properties:
              filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
              exp_time:
                description: The exposure time to use when taking images (sec).
                type: number
                default: 30.
              dofs:
                description: >
                    Degrees of freedom to adjust. The array must contain 50 values.
                type: array
                items:
                  type: number
                minItems: 50
                maxItems: 50
              rotation_sequence:
                description: >
                    Rotation sequence used for the parameter march. This can either be a single number
                    to use the same rotation angle throughout or an array specifying custom rotation angles.
                    If not provided, the script will determine the increments automatically.
                oneOf:
                    - type: number
                    description: >
                        A single rotation angle to be used throughout the parameter march.
                    - type: array
                    items:
                        type: number
                    minItems: 2
                    description: >
                        User-provided sequence of rotation angles for the parameter march.
                        The array must contain n_steps values.
              range:
                description: Total range for the parameter march.
                type: number
              n_steps:
                description: Number of steps to take inside the march range.
                type: number
                minimum: 2
              step_sequence:
                description: >-
                    User-provided sequence of steps to take for the parameter march,
                    used for unevenly spaced steps.
                type: array
                items:
                  type: number
                minItems: 2
              program:
                description: >-
                    Optional name of the program this dataset belongs to.
                type: string
                default: PARAMETER_MARCH
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              ignore:
                description: >-
                    CSCs from the group to ignore in status check. Name must
                    match those in self.group.components, e.g.; hexapod_1.
                type: array
                items:
                  type: string
            oneOf:
                - required:
                    - dof
                    - range
                    - n_steps
                - required:
                    - dof
                    - step_sequence
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await self.configure_tcs()
        await self.configure_camera()
        await self.configure_ocps()

        if hasattr(config, "ignore"):
            for comp in config.ignore:
                if comp in self.tcs.components_attr:
                    self.log.debug(f"Ignoring TCS component {comp}.")
                    setattr(self.tcs.check, comp, False)
                elif comp in self.camera.components_attr:
                    self.log.debug(f"Ignoring Camera component {comp}.")
                    setattr(self.camera.check, comp, False)
                else:
                    self.log.warning(
                        f"Component {comp} not in CSC Groups. "
                        f"Must be one of {self.tcs.components_attr} or "
                        f"{self.camera.components_attr}. Ignoring."
                    )

        if hasattr(config, "step_sequence"):
            config.range = config.step_sequence[-1] - config.step_sequence[0]
            config.n_steps = len(config.step_sequence)
        elif hasattr(config, "range"):
            config.step_sequence = [
                i * config.range / (config.n_steps - 1) for i in range(config.n_steps)
            ]

        self.config = config

        await super().configure(config=config)

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        """Sets script metadata.

        Parameters
        ----------
        metadata : `salobj.type_hints.BaseMsgType`
            Script metadata topic.
        """
        raise NotImplementedError()

    async def assert_feasibility(self) -> None:
        """Verify that the telescope and camera are in a feasible state to
        execute the script.
        """
        await asyncio.gather(
            self.tcs.assert_all_enabled(), self.camera.assert_all_enabled()
        )

    async def format_values(self, offset_values: np.ndarray) -> np.ndarray:
        """Format the values for display.

        Parameters
        ----------
        offset_values : `numpy.ndarray`
            Array of degrees of freedom.

        Returns
        -------
        cam_hex_values : `list`
            List of formatted values for the Camera Hexapod.
        m2_hex_values : `list`
            List of formatted values for the M2 Hexapod.
        m1m3_bend_values : `list`
            List of formatted values for the M1M3 Bend.
        m2_bend_values : `list`
            List of formatted values for the M2 Bend.
        """
        # Arrays to hold formatted values for each subsystem
        cam_hex_values = []
        m2_hex_values = []
        m1m3_bend_values = []
        m2_bend_values = []

        # Format the first 5 elements as Cam Hexapod
        cam_hex_values = [
            f"{val:+0.2f} {'um' if i < 3 else 'arcsec'}"
            for i, val in enumerate(offset_values[:5])
        ]

        # Format the next 5 elements as M2 Hexapod
        m2_hex_values = [
            f"{val:+0.2f} {'um' if i < 3 else 'arcsec'}"
            for i, val in enumerate(offset_values[5:10])
        ]

        # Format the next 20 elements as M1M3 Bend (all in um)
        m1m3_bend_values = [f"{val:+0.2f} um" for val in offset_values[10:30]]

        # Format the last 20 elements as M2 Bend (all in um)
        m2_bend_values = [f"{val:+0.2f} um" for val in offset_values[30:50]]

        # Return the arrays of formatted strings
        return cam_hex_values, m2_hex_values, m1m3_bend_values, m2_bend_values

    async def parameter_march(self) -> None:
        """Perform the parameter_march operation."""

        start_position = self.config.step_sequence[0]

        offset_values = start_position * self.config.dofs
        cam_hex, m2_hex, m1m3_bend, m2_bend = self.format_values(offset_values)

        await self.checkpoint(
            f"Step 1/{self.config.n_steps} starting positions:\n"
            f"Cam Hexapod: {cam_hex}\n"
            f"M2 Hexapod: {m2_hex}\n"
            f"M1M3 Bend: {m1m3_bend}\n"
            f"M2 Bend: {m2_bend}."
        )
        self.log.info("Offset dofs to starting position.")

        # Apply dof vector with offset
        offset_dof_data = self.mtcs.rem.mtaos.cmd_offsetDOF.DataType()
        for i, dof_offset in enumerate(offset_values):
            offset_dof_data.value[i] = dof_offset
        await self.mtcs.rem.mtaos.cmd_offsetDOF.start(data=offset_dof_data)
        self.total_offset += start_position

        self.iterations_started = True

        # Move rotator
        await self.mtcs.move_rotator(
            position=self.config.rotation_sequence[0], wait_for_in_position=True
        )

        await self.take_images()

        for self.iterations_executed in range(1, self.config.n_steps):
            await self.checkpoint(
                f"Step {self.iterations_executed+1}/{self.config.n_steps}."
            )
            # Calculate the offset for the current step
            offset = (
                self.config.step_sequence[self.iterations_executed]
                - self.config.step_sequence[self.iterations_executed - 1]
            )

            # Apply dof vector with offset
            offset_dof_data = self.mtcs.rem.mtaos.cmd_offsetDOF.DataType()
            for i, dof_offset in enumerate(self.config.dofs * offset):
                offset_dof_data.value[i] = dof_offset
            await self.mtcs.rem.mtaos.cmd_offsetDOF.start(data=offset_dof_data)

            # Store the total offset
            self.total_offset += offset

            # Move rotator
            await self.mtcs.move_rotator(
                position=self.config.rotation_sequence[self.iterations_executed],
                wait_for_in_position=True,
            )

            # Take images at the current dof position
            await self.take_images()

    @abc.abstractmethod
    def get_instrument_configuration(self) -> dict:
        """Get the instrument configuration.

        Returns
        -------
        dict
            Dictionary with instrument configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_filter(self) -> str:
        """Get the instrument filter configuration.

        Returns
        -------
        str
            Instrument filter configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def take_images(self) -> None:
        """Take images at the current dof position."""
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_name(self) -> str:
        raise NotImplementedError()

    async def run_block(self) -> None:
        """Execute script operations."""

        await self.assert_feasibility()
        await self.parameter_march()

    async def cleanup(self):
        try:
            if self.iterations_started:
                self.log.info(
                    f"Returning telescope to original position by moving "
                    f"{self.total_offset} back along dofs vector {self.config.dofs}."
                )
                offset_dof_data = self.mtcs.rem.mtaos.cmd_offsetDOF.DataType()
                for i, dof_offset in enumerate(self.config.dofs * -self.total_offset):
                    offset_dof_data.value[i] = dof_offset
                await self.mtcs.rem.mtaos.cmd_offsetDOF.start(data=offset_dof_data)
        except Exception:
            self.log.exception(
                "Error while trying to return hexapod to its original position."
            )
