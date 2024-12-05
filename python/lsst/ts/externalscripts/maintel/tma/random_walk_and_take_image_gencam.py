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

__all__ = ["RandomWalkAndTakeImagesGenCam"]

import asyncio

import yaml
from lsst.ts import utils
from lsst.ts.observatory.control import Usages
from lsst.ts.observatory.control.generic_camera import GenericCamera
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.base_track_target_and_take_image import (
    BaseTrackTargetAndTakeImage,
)

from .random_walk import RandomWalk


class RandomWalkAndTakeImagesGenCam(BaseTrackTargetAndTakeImage):
    """Perform random slews while taking images with one or more GenCam.

    Perform offsets of a fixed size in random directions with a probability
    of performing a large offset also in a random direction. Take images in
    each position with GenericCamera. Move the Dome whenever the difference
    between its position and the position of the telescope.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component
    add_remotes : `bool` (optional)
        Create remotes to control components (default: `True`)? If False, the
        script will not work for normal operations. Useful for unit testing.
    """

    def __init__(self, index, add_remotes: bool = True):
        super().__init__(
            index=index,
            descr="Slew and track random targets on sky with offsets between. "
            "Each offset might be a small offset or a big offset (both in the configuration). "
            "After each slew and having the dome in position, it will take images with one or "
            "more Generic Cameras while tracking. ",
        )
        self.config = None

        self.mtcs_usage, self.gencam_usage = (
            (MTCSUsages.Slew, None)
            if add_remotes
            else (MTCSUsages.DryTest, Usages.DryTest)
        )

        self._mtcs = MTCS(
            domain=self.domain, log=self.log, intended_usage=self.mtcs_usage
        )
        self.gencam_list = None

        # Define timeouts in seconds
        self.fast_timeout = 1
        self.slow_timeout = 10
        self.dome_wait_leave_fault_delay = 5
        self.dome_wait_slew_start_delay = 20

        setattr(
            RandomWalkAndTakeImagesGenCam,
            "get_azel_random_walk",
            RandomWalk.get_azel_random_walk,
        )

        self.instrument_name = "GenCam"

    async def _take_data(self):
        """Takes data with all the generic cameras"""
        for i in range(self.config.num_exp):
            self.log.info(f"Taking exposure #{i+1}")
            tasks = [
                asyncio.create_task(
                    cam.take_object(
                        exptime=exptime,
                        group_id=self.group_id,
                        reason=self.config.reason,
                        program=self.config.program,
                    )
                )
                for (cam, exptime) in zip(self.gencam_list, self.config.exp_times)
            ]
            await asyncio.gather(*tasks)
            await asyncio.sleep(self.config.sleep_time)

    async def assert_feasibility(self):
        """Verify that the system is in a feasible state to execute the
        script.
        """
        tasks = [
            asyncio.create_task(cam.assert_all_enabled()) for cam in self.gencam_list
        ]
        tasks += [
            asyncio.create_task(cam.assert_liveliness()) for cam in self.gencam_list
        ]

        await asyncio.gather(
            self.tcs.assert_all_enabled(), self.tcs.assert_liveliness(), *tasks
        )

    def get_instrument_name(self):
        return self.instrument_name

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        fields_str = "\n".join(
            f"  {key}: {value}" for key, value in vars(config).items()
        )
        self.log.debug(f"Setting up configuration: \n{fields_str}")
        assert len(config.camera_sal_indexes) == len(config.exp_times)

        self.config = config
        self.config.rot_type = getattr(RotType, self.config.rot_type)

        for comp in self.config.ignore:
            if comp not in self.tcs.components_attr:
                self.log.warning(
                    f"Component {comp} not in CSC Group. "
                    f"Must be one of {self.tcs.components_attr}. Ignoring."
                )
            else:
                self.log.debug(f"Ignoring component {comp}.")
                setattr(self.tcs.check, comp, False)

        self.gencam_list = [
            GenericCamera(
                index,
                self.domain,
                intended_usage=self.gencam_usage,
                log=self.log,
            )
            for index in self.config.camera_sal_indexes
        ]

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/ts_externalscripts/"
        path = "python/lsst/ts/externalscripts/maintel/random_walk.py"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}/{path}
            title: RandomWalkAndTakeImageGenCam v1
            description: >-
              Configuration for running a random walk on sky with slews and tracks
              while moving the dome and taking images with generic cameras.
            type: object
            properties:
              total_time:
                description: Total execution time in seconds.
                type: number
              radius:
                description: Canonical offset radius in degrees.
                type: number
                default: 3.5
              min_az:
                description: Minimum azimuth allowed in degrees.
                type: number
                default: -200
              max_az:
                description: Maximum azimuth allowed in degrees.
                type: number
                default: 200
              min_el:
                description: Minimum elevation allowed in degrees.
                type: number
                default: 20
              max_el:
                description: Maximum elevation allowed in degrees.
                type: number
                default: 80
              big_offset_prob:
                description: Probability of performing a bigger offset.
                type: number
                default: 0.10
                minimum: 0
                maximum: 1
              big_offset_radius:
                description: Bigger offset radius in degrees.
                type: number
                default: 9
              track_for:
                description: >-
                  How long to track target for (in seconds). If zero, the default,
                  finish script as soon as in position, otherwise, continue tracking target
                  until time expires.
                type: number
                minimum: 0
                default: 32
              stop_when_done:
                description: >-
                    Stop tracking once tracking time expires. Only valid if
                    `track_for` is larger than zero.
                type: boolean
                default: False
              ignore:
                description: >-
                  CSCs from the group to ignore in status check. Name must match
                  those in self.group.components, e.g.; hexapod_1.
                type: array
                items:
                  type: string
                default: []
              rot_value:
                description: Rotator position value. Actual meaning depends on rot_type.
                type: number
                default: 0
              rot_type:
                description: >-
                  Rotator strategy. Options are:
                    Sky: Sky position angle strategy. The rotator is positioned with respect
                         to the North axis so rot_angle=0. means y-axis is aligned with North.
                         Angle grows clock-wise.

                    SkyAuto: Same as sky position angle but it will verify that the requested
                             angle is achievable and wrap it to a valid range.

                    Parallactic: This strategy is required for taking optimum spectra with
                                 LATISS. If set to zero, the rotator is positioned so that the
                                 y-axis (dispersion axis) is aligned with the parallactic
                                 angle.

                    PhysicalSky: This strategy allows users to select the **initial** position
                                 of the rotator in terms of the physical rotator angle (in the
                                 reference frame of the telescope). Note that the telescope
                                 will resume tracking the sky rotation.

                    Physical: Select a fixed position for the rotator in the reference frame of
                              the telescope. Rotator will not track in this mode.
                type: string
                enum: ["Sky", "SkyAuto", "Parallactic", "PhysicalSky", "Physical"]
                default: Physical
              az_wrap_strategy:
                description: >-
                  Azimuth wrap strategy. By default use maxTimeOnTarget=3, which attempts to
                  maximize the time on target. Other options are; 1-noUnWrap, 2-optimize.
                type: integer
                minimum: 1
                maximum: 3
                default: 3
              camera_sal_indexes:
                description: SAL Indexes for the Generic Cameras.
                type: array
                items:
                  type: integer
                  minimum: 0
                  maximum: 2147483647
              exp_times:
                description: Exposure times used on each camera.
                type: array
                items:
                  type: number
                  minimum: 0
              num_exp:
                description: Number of exposures for all cameras.
                type: integer
                minimum: 1
                default: 1
              sleep_time:
                description: Sleep time between exposures.
                type: number
                minimum: 0
                default: 0
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              program:
                description: Optional name of the program this data belongs to, e.g. WFD, DD, etc.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              camera_playlist:
                description: >-
                  Optional name a camera playlist to load before running the script.
                  This parameter is mostly designed to use for integration tests and is
                  switched off by default (e.g. null).
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              max_dome_mount_az:
                description: >-
                  Maximum difference between dome position and target mount azimuth in degrees.
                  If the actuall difference is larger than this parameter, the dome moves.
                type: number
                default: 10.
              dome_offset:
                description: Artificial offset for when the dome loses reference.
                type: number
                default: 0
            required:
            - total_time
            - radius
            - min_az
            - max_az
            - min_el
            - max_el
            - big_offset_prob
            - big_offset_radius
            - track_for
            - stop_when_done
            - ignore
            - rot_value
            - rot_type
            - az_wrap_strategy
            - camera_sal_indexes
            - exp_times
            - num_exp
            - sleep_time
            - reason
            - program
            - camera_playlist
            - max_dome_mount_az
            - dome_offset
        """
        return yaml.safe_load(schema_yaml)

    async def load_playlist(self):
        """Load playlist."""
        raise NotImplementedError()

    async def move_dome(self, az: float):
        """Move the dome to a give position

        Parameters
        ----------
        az : float
            New dome Azimuth position in degrees.
        """
        # Return right away if ignoring the dome
        if "mtdome" in self.config.ignore:
            return

        # The dome usually goes to a fault when the brakes engage.
        # This usually happens because they are engaged when the dome
        # is slighly out of its target position. For this script,
        # this difference is negligible.
        await self.tcs.rem.mtdome.cmd_exitFault.start(timeout=self.slow_timeout)

        # This time is required to have the Dome getting out its Fault
        # state before moving
        await asyncio.sleep(self.dome_wait_leave_fault_delay)

        # Determine from the current position if we want to move or not
        dome_az_encoder = await self.tcs.rem.mtdome.tel_azimuth.next(
            flush=True, timeout=self.fast_timeout
        )
        dome_az_encoder = dome_az_encoder.positionActual
        dome_az_physical = dome_az_encoder - self.config.dome_offset
        self.log.debug(
            f"Current dome encoder position: {dome_az_encoder:.3f}, "
            f"Dome offset: {self.config.dome_offset:.3f}, "
            f"Current dome physical position: {dome_az_physical:.3f}, "
            f"Target telescope az: {az:.3f}, "
            f"Dome Physical - Target Az: {dome_az_physical - az:.3f}"
        )

        # Do nothing if our next target is too close
        # to the current dome position
        if abs(dome_az_physical - az) <= self.config.max_dome_mount_az:
            self.log.info(
                "The difference between Dome and TMA is too small. "
                "Keeping the dome at its current position."
            )
            return

        # Move the dome and wait until it finds its final position
        self.log.info(
            f"Moving from to {az:.3f} deg physical, "
            f"{az + self.config.dome_offset:.3f} deg encoder"
        )

        new_dome_az = az + self.config.dome_offset

        await self.tcs.rem.mtdome.evt_azMotion.flush()
        await self.tcs.rem.mtdome.cmd_moveAz.set_start(position=new_dome_az, velocity=0)

        # The dome takes a long time to start moving
        await asyncio.sleep(self.dome_wait_slew_start_delay)

        self.tcs.rem.mtdome.evt_azMotion.flush()
        az_motion = await self.tcs.rem.mtdome.evt_azMotion.aget(
            timeout=self.fast_timeout
        )

        while not az_motion.inPosition:
            az_motion = await self.tcs.rem.mtdome.evt_azMotion.next(
                flush=False, timeout=self.fast_timeout
            )

    async def run(self):
        """Main loop of the script."""
        counter = 0
        azel_gen = self.get_azel_random_walk()
        end_tai = utils.current_tai() + self.config.total_time

        self.log.info("Start random walk and take images")
        while True:
            if utils.current_tai() > end_tai:
                break

            counter += 1
            try:
                data = await anext(azel_gen)
            except StopAsyncIteration:
                self.log.debug("StopAsyncIteration - end of random walk.")
                break

            await self.checkpoint(f"[{counter}] Tracking {data.az=}/{data.el=}.")
            await self.slew_and_track(
                data.az, data.el, target_name=f"random_walk_{counter}"
            )

            # Move the dome to the new position
            await self.move_dome(data.az)

            # Take data in sync with all the GenericCameras
            await self.take_data()

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""
        metadata.duration = self.config.total_time

    async def slew_and_track(self, az, el, target_name=None):
        """Slew to new position on Sky and start tracking.

        Parameters
        ----------
        az : `float`
            Azimuth in hour angle.
        el :  `float`
            Elevation in degrees.
        target_name : `str`, optional
            Target name. In this case, not necessarily an astronomical
            target. Default: None
        """
        target_name = target_name if target_name else "random_walk"
        radec = self.tcs.radec_from_azel(az, el)

        ra = float(radec.ra.hour)
        dec = float(radec.dec.deg)

        self.log.info(
            f"Slew and track target_name={target_name}; "
            f"ra={ra}, dec={dec}; "
            f"rot={self.config.rot_value}; rot_type={self.config.rot_type}; "
        )

        await self.tcs.slew_icrs(
            ra=ra,
            dec=dec,
            rot=self.config.rot_value,
            rot_type=self.config.rot_type,
            target_name=target_name,
        )

        if self.config.track_for > 0.0:
            self.log.info(f"Tracking for {self.config.track_for}s .")
            await self.tcs.check_tracking(self.config.track_for)
            if self.config.stop_when_done:
                self.log.info("Tracking completed. Stop tracking.")
                await self.tcs.stop_tracking()
            else:
                self.log.info("Tracking completed.")

    async def stop_tracking(self):
        """Execute stop tracking on MTCS."""
        await self.tcs.stop_tracking()

    async def take_data(self):
        """Take data while making sure MTCS is tracking."""

        tasks = [
            asyncio.create_task(self._take_data()),
            asyncio.create_task(self.tcs.check_tracking()),
        ]

        await self.tcs.process_as_completed(tasks)

    @property
    def tcs(self):
        return self._mtcs

    async def track_target_and_setup_instrument(self):
        """Track target and setup instrument in parallel."""

        self.tracking_started = True

        await self.tcs.slew_icrs(
            ra=self.config.ra,
            dec=self.config.dec,
            rot=self.config.rot_sky,
            rot_type=RotType.Sky,
            target_name=self.config.name,
            az_wrap_strategy=self.config.az_wrap_strategy,
        )
