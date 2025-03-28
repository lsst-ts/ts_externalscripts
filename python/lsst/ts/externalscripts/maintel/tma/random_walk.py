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

__all__ = ["RandomWalk", "RandomWalkData"]

from dataclasses import dataclass

import numpy as np
import yaml
from lsst.ts import utils
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.base_track_target import BaseTrackTarget


@dataclass
class RandomWalkData:
    """Data-class used during Random Walk scripts.

    Store information used during the execution of the RandomWalk and similar
    scripts. The script uses `az` and `el` to calculate an offset relative
    to the initial position on sky of the previous target. This avoids a
    "trend" in azimuth movement.

    Attributes
    ----------
    az : float
        New azimuth coordinates in degrees.
        Reference azimuth value before applying new offset.
    el : float
        New elevation coordinates in degrees.
        Reference elevation before applying new offset.
    """

    az: float
    el: float


class RandomWalk(BaseTrackTarget):
    """Perform offsets of a fixed size in random directions with a probability
    of performing a large offset also in a random direction.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component
    """

    def __init__(self, index, remotes: bool = True):
        super().__init__(
            index=index,
            descr="Slew and track random targets on sky with a fixed size "
            "offset between them",
        )
        self.config = None
        self._mtcs = None

    @property
    def tcs(self):
        return self._mtcs

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/ts_externalscripts/"
        path = "python/lsst/ts/externalscripts/maintel/random_walk.py"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}/{path}
            title: RandomWalk v1
            description: Configuration for running a random walk on sky with slews and tracks.
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
                default: 39
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
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        if self._mtcs is None:
            self._mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.Slew
            )
            await self._mtcs.start_task

        self.log.debug(
            f"Setting up configuration: \n"
            f"  total_time: {config.total_time}\n"
            f"  radius: {config.radius}\n"
            f"  min_az: {config.min_az}\n"
            f"  max_az: {config.max_az}\n"
            f"  min_el: {config.min_el}\n"
            f"  max_el: {config.max_el}\n"
            f"  big_offset_prob: {config.big_offset_prob}\n"
            f"  big_offset_radius: {config.big_offset_radius}\n"
            f"  track_for: {config.track_for}\n"
            f"  rot_value: {config.rot_value}\n"
            f"  rot_type: {config.rot_type}\n"
        )

        self.config = config

        self.config.rot_type = getattr(RotType, self.config.rot_type)

        if hasattr(self.config, "ignore"):
            self.tcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""
        metadata.duration = self.config.total_time

    async def run(self):
        """Main loop of the script."""
        counter = 0
        azel_gen = self.get_azel_random_walk()
        end_tai = utils.current_tai() + self.config.total_time

        while True:
            if utils.current_tai() > end_tai:
                break

            counter += 1
            data = await anext(azel_gen)
            await self.checkpoint(f"[{counter}] Tracking {data.az=}/{data.el=}.")
            await self.slew_and_track(
                data.az, data.el, target_name=f"random_walk_{counter}"
            )

    async def get_azel_random_walk(self):
        """Generate new Az/El coordinates based on the current telescope
        position. The offset size is randomly selected between the radius
        and big_offset_radius.

        Yield
        -----
        RandomWalkData
            Az/El coordinates.
        """
        n_points = 10
        self.log.debug("Gathering current Az/El coordinates for random walk.")
        current_az_list = [
            await self.tcs.rem.mtmount.tel_azimuth.aget(timeout=self.tcs.fast_timeout)
            for _ in range(n_points)
        ]
        self.log.debug(f"{current_az_list=}")
        current_az = np.abs(np.median([az.actualPosition for az in current_az_list]))

        current_el_list = [
            await self.tcs.rem.mtmount.tel_elevation.aget(timeout=self.tcs.fast_timeout)
            for _ in range(n_points)
        ]
        current_el = np.abs(np.median([el.actualPosition for el in current_el_list]))

        self.log.debug(f"Current Az/El: {current_az=}/{current_el=}")

        current_radius = (
            self.config.big_offset_radius
            if np.random.rand() <= self.config.big_offset_prob
            else self.config.radius
        )

        random_angle = 2 * np.pi * np.random.rand()

        # Get elevation offset first
        offset_el = current_radius * np.sin(random_angle)
        new_el = current_el + offset_el

        if new_el <= self.config.min_el or new_el >= self.config.max_el:
            new_el = current_el - offset_el

        # Azimuth offset depends on elevation to offsets on sky consistent
        offset_az = (current_radius * np.cos(random_angle)) / np.cos(
            np.deg2rad(0.5 * (new_el + current_el))
        )
        new_az = current_az + offset_az

        if new_az <= self.config.min_az or new_az >= self.config.max_az:
            new_az = current_az - offset_az

        self.log.info(
            f"{current_az=:>10.4f}, "
            f"{new_az=:>10.4f}, "
            f"{current_el=:>10.4f}, "
            f"{new_el=:>10.4f}, "
        )

        # Yield the sky offset for testing purposes and
        # and the counter to be displayed in the checkpoints
        yield RandomWalkData(az=new_az, el=new_el)

        current_az, current_el = new_az, new_el

    async def slew_and_track(self, az, el, target_name=None):
        """Slew to and track a new target.

        Parameters
        ----------
        az : `float`
            Azimuth in hour angle.
        el :  `float`
            Elevation in degrees.
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
