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

__all__ = ["WarmUpHexapod"]

import asyncio
from collections.abc import Iterable

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.xml.enums.MTHexapod import EnabledSubstate, SalIndex
from lsst.ts.xml.enums.Watcher import AlarmSeverity


class WarmUpHexapod(salobj.BaseScript):
    """Warm up Camera/M2 Hexapod after they have been idle for a long time.

    This sequence consists of moving the hexapod (camera or m2 hexapod) in
    one direction until it reaches its maximum position in both positive
    and negative directions. It moves in discrete steps to avoid
    a FollowingError, which happens when performing long movements.

    This error became more evident in April 2022 and is reported in both
    FRACAS-110_ and FRACAS-111_.

    You will probably run this script a couple times with increasing
    step size (e.g. 100 um, 250 um, 500 um, 1000 um, 2500 um, 5000 um,
    10000 um) with the goal of moving the hexapod from one extreme to the
    other without any faults.

    .. _FRACAS-110: https://jira.lsstcorp.org/browse/FRACAS-110
    .. _FRACAS-111: https://jira.lsstcorp.org/browse/FRACAS-111
    """

    def __init__(self, index, remotes: bool = True):
        super().__init__(
            index=index,
            descr="Warm up the Camera Hexapod or the M2 Hexapod by moving it to its extremes in "
            "discrete steps",
        )

        self.config = None
        self.mtcs = None
        self.watcher = None

        # The checkpoints depend on the configuration
        self.checkpoints_activities = [
            ("Run warm-up sequence for hexapod", self.warm_up),
        ]

    @classmethod
    def get_schema(cls):
        yaml_schema = """
            $schema: http://json-schema/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/maintel/WarmUpHexapod.yaml
            title: WarmUpHexapod v1
            description: Configuration for WarmUpHexapod.
            type: object
            properties:
              hexapod:
                description: >-
                  Which hexapod will move? "camera" for the camera hexapod
                  or "m2" for the m2 hexapod.
                type: string
                enum: ["camera", "m2"]
              axis:
                description: Which axis will move? (x, y, z, u, v, w).
                type: string
                enum: ["x", "y", "z", "u", "v", "w"]
                default: z
              step_size:
                description: >-
                  The discrete step size in microns in which the hexapod will move.
                  This can be a number or an array of numbers.
                anyOf:
                  - type: number
                  - type: array
                default: 100
              sleep_time:
                description: >-
                  The sleep time in seconds between movements. The number of
                  elements must match the number of elements of step_size.
                anyOf:
                  - type: number
                    exclusiveMinimum: 0.0
                  - type: array
                    items:
                      type: number
                      exclusiveMinimum: 0.0
                default: 1
              max_position:
                description: Maximum position (absolute value) for the movements.
                type: number
                exclusiveMinimum: 0.0
                maximum: 13000.0
                default: 13000.0
              max_verification_position:
                description: >-
                  Maximum verification position (absolute value) for the
                  movements. Consider to use the small value for x and y.
                type: number
                exclusiveMinimum: 0.0
                maximum: 11000.0
                default: 2000.0
              max_warmup_iterations:
                description: >-
                  Maximum number of iterations to try warming up the hexapod.
                  The sequence will stop early if successful.
                type: integer
                minimum: 1
                maximum: 5
                default: 5
            additionalProperties: false
            """
        return yaml.safe_load(yaml_schema)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        if self.mtcs is None:
            self.mtcs = MTCS(domain=self.domain, log=self.log)
            await self.mtcs.start_task

        if self.watcher is None:
            self.watcher = salobj.Remote(domain=self.domain, name="Watcher", include=[])
            await self.watcher.start_task

        self.log.debug(
            f"Setting up configuration: \n"
            f"  hexapod: {config.hexapod}\n"
            f"  axis: {config.axis}\n"
            f"  step_size: {config.step_size}\n"
            f"  sleep_time: {config.sleep_time}\n"
            f"  max_position: {config.max_position}\n"
            f"  max_verification_position: {config.max_verification_position}\n"
        )

        self.config = config

        # Converts the string to salindex
        self.hexapod_name = f"{config.hexapod}_hexapod"
        self.hexapod_sal_index = getattr(SalIndex, self.hexapod_name.upper())
        self.hexapod = getattr(self.mtcs.rem, f"mthexapod_{self.hexapod_sal_index}")
        self.log.debug(
            f"Using the {self.hexapod_name} with sal index {self.hexapod_sal_index}"
        )

        # Make sure step_size and sleep_time are arrays.
        if not isinstance(self.config.step_size, Iterable):
            self.config.step_size = [self.config.step_size]

        if not isinstance(self.config.sleep_time, Iterable):
            self.config.sleep_time = [self.config.sleep_time]

        if len(self.config.step_size) != len(self.config.sleep_time):
            raise ValueError(
                f"Expected same number of elements for step_size and "
                f"sleep_time, got {len(config.step_size)} and "
                f"{len(config.sleep_time)}, respectively."
            )

        # Relay the function used to execute the movement
        self.move_hexapod = (
            self.mtcs.move_camera_hexapod
            if self.hexapod_sal_index == SalIndex.CAMERA_HEXAPOD
            else self.mtcs.move_m2_hexapod
        )

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""
        metadata.duration = sum(
            [
                (time + 5.0) * self.get_number_of_steps(step)
                for time, step in zip(self.config.sleep_time, self.config.step_size)
            ]
        )

    def get_number_of_steps(self, step_size):
        """
        Returns the total number of steps depending on the step size
        considering that the starting point might not be zero.

        Parameters
        ----------
        step_size : float
            Step size in microns or in deg.

        Returns
        -------
        int : total number of steps.
        """
        return 4 * self.config.max_position // step_size

    async def run(self):
        """Runs the script"""
        for checkpoint, activity in self.checkpoints_activities:
            self.log.debug(f"Running checkpoint: {checkpoint} [{activity}]")
            await self.checkpoint(checkpoint)
            try:
                await activity()
            except Exception:
                self.log.exception(f"Error running checkpoint: {checkpoint}")
                raise
        await self.checkpoint("Done")

    async def warm_up(self) -> None:
        """Run the `single_loop` function for each step_size/sleep_time pair
        of values.

        Raises
        ------
        `RuntimeError`
            When the hexapod fails to pass the verification stage.
        """

        # Mute the watcher alarm
        alarm_name = f"Enabled.MTHexapod:{self.hexapod_sal_index.value}"
        self.log.info(
            f"Muting {self.hexapod_name} alarm: {alarm_name} for 3600 seconds."
        )

        try:
            await self.watcher.cmd_mute.set_start(
                name=alarm_name,
                duration=3600.0,
                severity=AlarmSeverity.CRITICAL.value,
                mutedBy="warmup_hexapod.py",
                timeout=60.0,
            )

            is_mutted = True

            self.log.info(f"{self.hexapod_name} alarm: {alarm_name} is muted.")

        except Exception as error:
            self.log.exception(
                f"Failed to mute the {self.hexapod_name} {alarm_name} alarm: {error}"
            )

            is_mutted = False

        # Do the warming followed by the verification
        max_count = self.config.max_warmup_iterations

        count = 0
        while count < max_count:
            try:
                # Do the warmings
                for step, sleep_time in zip(
                    self.config.step_size, self.config.sleep_time
                ):
                    await self.single_loop(step, sleep_time)

                # Sleep for some time before the verification
                await asyncio.sleep(5.0)

                # Do the verification. If successful, exit the loop
                self.log.info(f"Doing the verification: {count + 1}")
                if await self._verify_full_range():
                    break

            except Exception:
                # Unmute the watcher alarm
                await self._unmute_alarm(is_mutted, alarm_name)

                raise

            count += 1

        # Unmute the watcher alarm
        await self._unmute_alarm(is_mutted, alarm_name)

        if count >= max_count:
            raise RuntimeError(
                f"{self.hexapod_name} failed to pass the verification stage with {max_count} tries"
            )

    async def _verify_full_range(self) -> bool:
        """Verify the full range of the hexapod.

        Returns
        -------
        `bool`
            True if the verification is successful, False otherwise.
        """

        try:
            all_positions = await self._get_position()

            # Move to the maximum position
            all_positions[self.config.axis] = self.config.max_verification_position
            await self.move_hexapod(**all_positions)

            # Move to the minimum position
            all_positions[self.config.axis] = -self.config.max_verification_position
            await self.move_hexapod(**all_positions)

            # Move back to the origin
            await self.move_hexapod(0.0, 0.0, 0.0, 0.0, 0.0, w=0.0)

            return True

        except Exception:
            self.log.info(
                f"{self.hexapod_name} failed to verify the full range. Rewarming..."
            )

            await self._recover()

            return False

    async def _unmute_alarm(self, is_mutted: bool, alarm_name: str) -> None:
        """Unmute the alarm.

        Parameters
        ----------
        is_mutted : `bool`
            Alarm is muted or not.
        alarm_name : `str`
            Alarm name.
        """

        if is_mutted:
            try:
                await self.watcher.cmd_unmute.set_start(name=alarm_name)

                self.log.info(f"{self.hexapod_name}: alarm {alarm_name} is unmuted.")

            except Exception as error:
                self.log.exception(
                    f"Failed to unmute the {self.hexapod_name} {alarm_name} alarm: {error}"
                )

    async def move_stepwise(
        self,
        start: float,
        stop: float,
        step_initial: float,
        sleep_time: float,
        max_count: int = 5,
    ):
        """Moves the hexapod from `start` to `stop` that begins from
        `step_initial`. The step size is updated based on the result of the
        movement.

        Parameters
        ----------
        start : `float`
            Initial position.
        stop : `float`
            Final position.
        step_initial : `float`
            Initial step size.
        sleep_time : `float`
            Time between movements.
        max_count : `int`, optional
            Maximum count to try. (the default is 5)

        Raises
        ------
        `RuntimeError`
            When the hexapod fails to move in a single stage.
        """

        count = 0
        position_current = start
        position_next = start
        step_current = step_initial
        while position_current != stop:
            # Make sure the next position is not beyond the stop
            position_next = position_current + step_current
            if step_initial >= 0:
                if position_next >= stop:
                    position_next = stop
            else:
                if position_next <= stop:
                    position_next = stop

            self.log.debug(
                f"{self.hexapod_name} moves from {position_current} to "
                f"{position_next} with step size: {step_current}"
            )

            # Do the movement
            all_positions = await self._get_position()
            all_positions[self.config.axis] = position_next

            is_successful = await self._move_hexapod(**all_positions)

            # Update the step size based on the result
            step_current_update = (
                (step_current + step_initial) if is_successful else (step_current / 2)
            )
            step_current = (
                step_current_update
                if (abs(step_current_update) >= abs(step_initial))
                else step_initial
            )

            # Update the current position
            if is_successful:
                position_current = position_next
            else:
                position_fail = await self._get_position()
                position_current = position_fail[self.config.axis]

                count += 1

            if count >= max_count:
                raise RuntimeError(
                    f"{self.hexapod_name} failed to move with {max_count} "
                    "tries in a single stage"
                )

            self.log.debug(
                f"Current position of {self.hexapod_name} is {position_current}"
            )

            await asyncio.sleep(sleep_time)

    async def _get_position(self) -> dict:
        """Get the current position of the hexapod.

        Returns
        -------
        `dict`
            Current position of the hexapod.
        """

        pos = await self.hexapod.tel_application.aget()

        axes = "xyzuvw"
        return {axes[i]: pos.position[i] for i in range(len(axes))}

    async def _move_hexapod(
        self,
        x: float,
        y: float,
        z: float,
        u: float,
        v: float,
        w: float = 0.0,
    ) -> bool:
        """Move the hexapod to the given position.

        Parameters
        ----------
        x : `float`
            Hexapod-x position (microns).
        y : `float`
            Hexapod-y position (microns).
        z : `float`
            Hexapod-z position (microns).
        u : `float`
            Hexapod-u angle (degrees).
        v : `float`
            Hexapod-v angle (degrees).
        w : `float`, optional
            Hexapod-w angle (degrees). Default 0.

        Returns
        -------
        `bool`
            `True` if the movement is successful, `False` otherwise.
        """

        try:
            await self.move_hexapod(x, y, z, u, v, w=w)

            return True
        except (asyncio.CancelledError, TimeoutError, salobj.base.AckError):
            self.log.exception(
                f"Error moving the {self.hexapod_name} to {x=}, {y=}, {z=}, {u=}, {v=}."
            )

            await self._recover()

            return False

    async def _recover(self) -> None:
        """Recover the system."""

        # If the hexapod is in fault, recover it
        state = self.hexapod.evt_summaryState.get().summaryState
        if state == salobj.State.FAULT:
            self.log.info(f"Recover the {self.hexapod_name} CSC from the Fault.")
            await salobj.set_summary_state(self.hexapod, salobj.State.ENABLED)

        # If the hexapod is moving, stop it
        controller_enabled_state = (
            self.hexapod.evt_controllerState.get().enabledSubstate
        )
        if controller_enabled_state == EnabledSubstate.MOVING_POINT_TO_POINT:
            self.log.info(f"Stop the {self.hexapod_name} CSC.")
            await self.hexapod.cmd_stop.set_start()

        # Wait for a few seconds
        await asyncio.sleep(5.0)

    async def single_loop(self, step, sleep_time):
        """
        Do a full loop moving from the current position to the positive limit
        position, then to the negative limit position, and back to 0 using a
        single step size and sleep time.

        Parameters
        ----------
        step : float
            Step size.
        sleep_time : float
            Time between movements.
        """
        self.log.info(
            f"{self.hexapod_name} starts loop with {step} step and {sleep_time} sleep time."
        )

        # Move to the origin first
        self.log.info(f"Move the {self.hexapod_name} to the origin")
        await self._move_to_origin()

        # Positive direction
        self.log.info(f"Move {self.hexapod_name} from 0 to maximum position")
        await self.move_stepwise(
            0.0,
            self.config.max_position,
            step,
            sleep_time,
        )

        self.log.info(f"Move {self.hexapod_name} from maximum position back to 0")
        await self.move_stepwise(
            self.config.max_position,
            0.0,
            -step,
            sleep_time,
        )

        # Negative direction
        self.log.info(f"Move {self.hexapod_name} from 0 to minimum position")
        await self.move_stepwise(
            0.0,
            -self.config.max_position,
            -step,
            sleep_time,
        )

        self.log.info(f"Move {self.hexapod_name} from minimum position back to 0")
        await self.move_stepwise(
            -self.config.max_position,
            0.0,
            step,
            sleep_time,
        )

    async def _move_to_origin(self, max_count: int = 5) -> None:
        """Move to the origin.

        Parameters
        ----------
        max_count : `int`, optional
            Maximum count to try. (the default is 5)

        Raises
        ------
        `RuntimeError`
            When the hexapod fails to move to the origin.
        """

        count = 0
        while count < max_count:
            is_done = await self._move_hexapod(0.0, 0.0, 0.0, 0.0, 0.0, w=0.0)
            if is_done:
                return
            else:
                count += 1

        raise RuntimeError(
            f"Failed to move {self.hexapod_name} to the origin. with {max_count} tries"
        )
