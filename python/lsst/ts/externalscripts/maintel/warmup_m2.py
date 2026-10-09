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

__all__ = ["WarmUpM2"]

import asyncio
from collections.abc import Iterable, Sized

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.xml.enums.Watcher import AlarmSeverity

M2_AXES = ("x", "y", "z", "xRot", "yRot", "zRot")


class WarmUpM2(salobj.BaseScript):
    """Warm up the M2 mirror after it has been idle for a long time.

    This sequence consists of moving the M2 mirror rigid body position in
    one direction until it reaches its maximum position in both positive
    and negative directions. It moves in discrete steps, adapting the step
    size based on the result of each movement.

    This is the M2 equivalent of `WarmUpHexapod`. Since
    ``ts_observatory_control`` does not provide support for moving M2
    itself, the movement is sent directly to the MTM2 CSC through the
    `move_m2` method.
    """

    def __init__(self, index, remotes: bool = True):
        super().__init__(
            index=index,
            descr="Warm up the M2 mirror by moving it to its extremes in "
            "discrete steps",
        )

        self.config = None
        self.mtcs = None
        self.watcher = None

        self.m2_name = "m2"
        self.move_timeout = 60.0
        self.aget_timeout = 5.0

        # The checkpoints depend on the configuration
        self.checkpoints_activities = [
            ("Run warm-up sequence for M2", self.warm_up),
        ]

    @classmethod
    def get_schema(cls):
        yaml_schema = """
            $schema: http://json-schema/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/maintel/WarmUpM2.yaml
            title: WarmUpM2 v1
            description: Configuration for WarmUpM2.
            type: object
            properties:
              axis:
                description: >-
                  Which axis will move? (x, y, z, xRot, yRot, zRot).
                type: string
                enum: ["x", "y", "z", "xRot", "yRot", "zRot"]
                default: z
              step_size:
                description: >-
                  The discrete step size in which M2 will move, in microns
                  for x, y and z, and in arcsec for xRot, yRot and zRot.
                  This can be a number or an array of numbers.
                anyOf:
                  - type: number
                  - type: array
                default: 10
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
                description: >-
                  Maximum position (absolute value) for the movements, in
                  microns for x, y and z, and in arcsec for xRot, yRot and
                  zRot.
                type: number
                exclusiveMinimum: 0.0
                default: 100.0
              max_verification_position:
                description: >-
                  Maximum verification position (absolute value) for the
                  movements, in microns for x, y and z, and in arcsec for
                  xRot, yRot and zRot.
                type: number
                exclusiveMinimum: 0.0
                default: 50.0
              max_warmup_iterations:
                description: >-
                  Maximum number of iterations to try warming up M2.
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
            # No MTCSUsages provides the MTM2 topics needed to move the
            # mirror, so load all resources.
            self.mtcs = MTCS(
                domain=self.domain,
                log=self.log,
                intended_usage=None,
            )
            await self.mtcs.start_task

        if self.watcher is None:
            self.watcher = salobj.Remote(domain=self.domain, name="Watcher", include=[])
            await self.watcher.start_task

        # Only check M2 when asserting liveliness and states.
        for component in self.mtcs.components_attr:
            setattr(self.mtcs.check, component, component == "mtm2")

        self.log.debug(
            f"Setting up configuration: \n"
            f"  axis: {config.axis}\n"
            f"  step_size: {config.step_size}\n"
            f"  sleep_time: {config.sleep_time}\n"
            f"  max_position: {config.max_position}\n"
            f"  max_verification_position: {config.max_verification_position}\n"
        )

        self.config = config

        # Make sure step_size and sleep_time are arrays.
        if not isinstance(self.config.step_size, Iterable):
            self.config.step_size = [self.config.step_size]

        if not isinstance(self.config.sleep_time, Iterable):
            self.config.sleep_time = [self.config.sleep_time]

        assert isinstance(self.config.step_size, Sized)
        assert isinstance(self.config.sleep_time, Sized)

        if len(self.config.step_size) != len(self.config.sleep_time):
            raise ValueError(
                f"Expected same number of elements for step_size and "
                f"sleep_time, got {len(config.step_size)} and "
                f"{len(config.sleep_time)}, respectively."
            )

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""

        assert self.config is not None

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
            Step size in microns or in arcsec.

        Returns
        -------
        int : total number of steps.
        """
        assert self.config is not None
        return 4 * self.config.max_position // step_size

    async def run(self):
        """Runs the script"""
        assert self.mtcs is not None

        await self.mtcs.assert_liveliness()
        await self.mtcs.assert_all_enabled()

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
            When M2 fails to pass the verification stage.
        """
        assert self.config is not None

        # Mute the watcher alarm
        alarm_name = "Enabled.MTM2"
        self.log.info(f"Muting {self.m2_name} alarm: {alarm_name} for 3600 seconds.")

        try:
            assert self.watcher is not None
            await self.watcher.cmd_mute.set_start(
                name=alarm_name,
                duration=3600.0,
                severity=AlarmSeverity.CRITICAL.value,
                mutedBy="warmup_m2.py",
                timeout=60.0,
            )

            is_mutted = True

            self.log.info(f"{self.m2_name} alarm: {alarm_name} is muted.")

        except Exception as error:
            self.log.exception(
                f"Failed to mute the {self.m2_name} {alarm_name} alarm: {error}"
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
                f"{self.m2_name} failed to pass the verification stage with {max_count} attempts."
            )

    async def _verify_full_range(self) -> bool:
        """Verify the full range of M2.

        Returns
        -------
        `bool`
            True if the verification is successful, False otherwise.
        """

        try:
            assert self.config is not None
            all_positions = await self._get_position()

            # Move to the maximum position
            all_positions[self.config.axis] = self.config.max_verification_position
            await self.move_m2(**all_positions)

            # Move to the minimum position
            all_positions[self.config.axis] = -self.config.max_verification_position
            await self.move_m2(**all_positions)

            # Move back to the origin
            await self.move_m2(**self._origin())

            return True

        except Exception:
            self.log.info(
                f"{self.m2_name} failed to verify the full range. Rewarming..."
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
                assert self.watcher is not None
                await self.watcher.cmd_unmute.set_start(name=alarm_name)

                self.log.info(f"{self.m2_name}: alarm {alarm_name} is unmuted.")

            except Exception as error:
                self.log.exception(
                    f"Failed to unmute the {self.m2_name} {alarm_name} alarm: {error}"
                )

    async def move_stepwise(
        self,
        start: float,
        stop: float,
        step_initial: float,
        sleep_time: float,
        max_count: int = 5,
    ):
        """Moves M2 from `start` to `stop` that begins from `step_initial`.
        The step size is updated based on the result of the movement.

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
            When M2 fails to move in a single stage.
        """

        assert self.config is not None

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
                f"{self.m2_name} moves from {position_current} to "
                f"{position_next} with step size: {step_current}"
            )

            # Do the movement
            all_positions = await self._get_position()
            all_positions[self.config.axis] = position_next

            is_successful = await self._move_m2(**all_positions)

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
                    f"{self.m2_name} failed to move with {max_count} "
                    "tries in a single stage"
                )

            self.log.debug(f"Current position of {self.m2_name} is {position_current}")

            await asyncio.sleep(sleep_time)

    @staticmethod
    def _origin() -> dict:
        """Return the origin position for all M2 axes.

        Returns
        -------
        `dict`
            Zero position for every axis.
        """
        return {axis: 0.0 for axis in M2_AXES}

    async def _get_position(self) -> dict:
        """Get the current position of M2.

        Returns
        -------
        `dict`
            Current position of M2.
        """

        pos = await self.mtcs.rem.mtm2.tel_position.aget(timeout=self.aget_timeout)

        return {axis: getattr(pos, axis) for axis in M2_AXES}

    async def move_m2(
        self,
        x: float,
        y: float,
        z: float,
        xRot: float,
        yRot: float,
        zRot: float,
    ) -> None:
        """Move M2 to the given rigid body position.

        This is the single place where the M2 movement is commanded. Since
        ``ts_observatory_control`` does not support moving M2, the command
        is sent directly to the MTM2 CSC.

        Parameters
        ----------
        x : `float`
            Position x (microns).
        y : `float`
            Position y (microns).
        z : `float`
            Position z (microns).
        xRot : `float`
            Rotation about x (arcsec).
        yRot : `float`
            Rotation about y (arcsec).
        zRot : `float`
            Rotation about z (arcsec).
        """
        assert self.mtcs is not None

        self.mtcs.rem.mtm2.evt_m2AssemblyInPosition.flush()

        await self.mtcs.rem.mtm2.cmd_positionMirror.set_start(
            x=x,
            y=y,
            z=z,
            xRot=xRot,
            yRot=yRot,
            zRot=zRot,
            timeout=self.move_timeout,
        )

        try:
            in_position = await self.mtcs.rem.mtm2.evt_m2AssemblyInPosition.next(
                timeout=self.mtcs.long_timeout, flush=False
            )
        except asyncio.TimeoutError:
            in_position = await self.mtcs.rem.mtm2.evt_m2AssemblyInPosition.aget(
                timeout=self.mtcs.long_timeout
            )

        while not in_position.inPosition:
            in_position = await self.mtcs.rem.mtm2.evt_m2AssemblyInPosition.next(
                timeout=self.mtcs.long_timeout, flush=False
            )

    async def _move_m2(
        self,
        x: float,
        y: float,
        z: float,
        xRot: float,
        yRot: float,
        zRot: float,
    ) -> bool:
        """Move M2 to the given position, recovering on failure.

        Parameters
        ----------
        x : `float`
            Position x (microns).
        y : `float`
            Position y (microns).
        z : `float`
            Position z (microns).
        xRot : `float`
            Rotation about x (arcsec).
        yRot : `float`
            Rotation about y (arcsec).
        zRot : `float`
            Rotation about z (arcsec).

        Returns
        -------
        `bool`
            `True` if the movement is successful, `False` otherwise.
        """

        try:
            await self.move_m2(x=x, y=y, z=z, xRot=xRot, yRot=yRot, zRot=zRot)

            return True
        except (asyncio.CancelledError, TimeoutError, salobj.base.AckError):
            self.log.exception(
                f"Error moving the {self.m2_name} to {x=}, {y=}, {z=}, "
                f"{xRot=}, {yRot=}, {zRot=}."
            )

            await self._recover()

            return False

    async def _recover(self) -> None:
        """Recover the system."""
        assert self.mtcs is not None

        # If M2 is in fault, recover it
        state = self.mtcs.rem.mtm2.evt_summaryState.get().summaryState
        if state == salobj.State.FAULT:
            self.log.info(f"Recover the {self.m2_name} CSC from the Fault.")
            await self.mtcs.set_state(salobj.State.ENABLED, components=["mtm2"])

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
        assert self.config is not None

        self.log.info(
            f"{self.m2_name} starts loop with {step} step and {sleep_time} sleep time."
        )

        # Move to the origin first
        self.log.info(f"Move the {self.m2_name} to the origin")
        await self._move_to_origin()

        # Positive direction
        self.log.info(f"Move {self.m2_name} from 0 to maximum position")
        await self.move_stepwise(
            0.0,
            self.config.max_position,
            step,
            sleep_time,
        )

        self.log.info(f"Move {self.m2_name} from maximum position back to 0")
        await self.move_stepwise(
            self.config.max_position,
            0.0,
            -step,
            sleep_time,
        )

        # Negative direction
        self.log.info(f"Move {self.m2_name} from 0 to minimum position")
        await self.move_stepwise(
            0.0,
            -self.config.max_position,
            -step,
            sleep_time,
        )

        self.log.info(f"Move {self.m2_name} from minimum position back to 0")
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
            When M2 fails to move to the origin.
        """

        count = 0
        while count < max_count:
            is_done = await self._move_m2(**self._origin())
            if is_done:
                return
            else:
                count += 1

        raise RuntimeError(
            f"Failed to move {self.m2_name} to the origin. with {max_count} tries"
        )
