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

__all__ = ["SerpentWalk"]

import asyncio

import numpy as np
import yaml
from astropy.time import Time
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.base_track_target import BaseTrackTarget


class SerpentWalk(BaseTrackTarget):
    """Performs slew and tracks for targets going up and down for different
    azimuth and elevation (like a serpent).

    Parameters
    ----------
    index : `int`
        Index of Script SAL component
    """

    def __init__(self, index, remotes: bool = True):
        super().__init__(
            index=index,
            descr="Slew and track targets on an az/el grid going up and down.",
        )
        self.config = None
        self._mtcs = (
            MTCS(domain=self.domain, log=self.log, intended_usage=MTCSUsages.Slew)
            if remotes
            else MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.DryTest
            )
        )

    @property
    def tcs(self):
        return self._mtcs

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/ts_externalscripts/"
        path = "python/lsst/ts/externalscripts/maintel/serpent_walk.py"
        schema_yaml = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}/{path}
            title: SerpentWalk v1
            description: Configuration for an az/el grid going up and down.
            type: object
            properties:
              total_time:
                description: Total execution time in seconds.
                type: number
              az_grid:
                description: Azimuth coordinates in degree.
                type: array
                items:
                  type: number
              el_grid:
                description: Elevation coordinates in degree.
                type: array
                items:
                  type: number
              el_cutoff:
                description: >-
                  Elevation cutoff limit to skip targets when going down. Using
                  the default value includes all the targets.
                type: number
                default: 90.
              track_for:
                description: >-
                  How long to track target for (in seconds). If zero, the default,
                  finish script as soon as in position, otherwise, continue tracking target
                  until time expires.
                type: number
                minimum: 0
                default: 0
              stop_when_done:
                description: >-
                  Stop tracking once tracking time expires. Only valid if
                  `track_for` is larger than zero.
                type: boolean
                default: false
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
            required:
              - total_time
              - az_grid
              - el_grid
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
        self.log.debug(
            f"Setting up configuration: \n"
            f"  total_time: {config.total_time}\n"
            f"  track_for: {config.track_for}\n"
            f"  rot_value: {config.rot_value}\n"
            f"  rot_type: {config.rot_type}\n"
        )

        self.config = config

        self.config.rot_type = getattr(RotType, self.config.rot_type)

        if hasattr(self.config, "ignore"):
            for comp in self.config.ignore:
                if comp not in self.tcs.components_attr:
                    self.log.warning(
                        f"Component {comp} not in CSC Group. "
                        f"Must be one of {self.tcs.components_attr}. Ignoring."
                    )
                else:
                    self.log.debug(f"Ignoring component {comp}.")
                    setattr(self.tcs.check, comp, False)

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""
        metadata.duration = self.config.total_time

    async def run(self):
        for i, az, el in self.azel_grid_by_time():
            await self.checkpoint(f"[{i}] Tracking {az=}/{el=}.")
            await self.slew_and_track(az, el, target_name=f"serpent_walk_{i}")

    async def azel_grid_by_time(self):
        """
        Generate Az/El coordinates for a a long time so we can slew and track
        to these targets using a predefined az_grid and el_grid.
        """
        step = 0
        timer_task = asyncio.create_task(asyncio.sleep(self.config.total_time))
        self.log.info(
            f"{'Time':25s}{'Steps':>10s}{'Old Az':>10s}{'New Az':>10s}{'Old El':>10s}{'New El':>10s}"
        )

        generator = self.generate_azel_sequence(
            self.config.az_grid, self.config.el_grid, el_cutoff=self.config.el_cutoff
        )

        n_points = 10
        old_az = np.median(
            [
                self.tcs.rem.mtmount.tel_azimuth.get().actualPosition
                for i in range(n_points)
            ]
        )
        old_el = np.median(
            [
                self.tcs.rem.mtmount.tel_elevation.get().actualPosition
                for i in range(n_points)
            ]
        )

        while not timer_task.done():

            new_az, new_el = next(generator)

            if new_az == old_az and new_el == old_el:
                continue

            t = Time.now().to_value("isot")
            self.log.info(
                f"{t:25s}{step:10d}{old_az:10.2f}{new_az:10.2f}{old_el:10.2f}{new_el:10.2f}"
            )

            yield step, new_az, new_el
            old_az, old_el = new_az, new_el
            step += 1

    @staticmethod
    def generate_azel_sequence(az_seq, el_seq, el_cutoff=90.0):
        """A generator that cicles through the input azimuth and
        elevation sequences forward and backwards.

        Parameters
        ----------
        az_seq : `list` [`float`]
            A sequence of azimuth values to cicle through
        el_seq : `list` [`float`]
            A sequence of elevation values to cicle through
        el_cutoff : `float`, default 90.
            Elevation cutoff limit used to skip targets to minimize the number
            of targets in high elevation. The default value of 90 deg keeps
            all targets.
        Yields
        ------
        `list`
            Values from the sequence.
        Notes
        -----
        This generator is designed to generate sequence of values cicling
        through the input forward and backwards. It will also reverse the
        list when moving backwards.
        Use it as follows:
        >>> az_seq = [0, 180]
        >>> el_seq = [15, 45]
        >>> seq_gen = generate_azel_sequence(az_seq, el_seq)
        >>> next(seq_gen)
        [0, 15]
        >>> next(seq_gen)
        [0, 45]
        >>> next(seq_gen)
        [180, 45]
        >>> next(seq_gen)
        [180, 15]
        >>> next(seq_gen)
        [0, 15]
        """
        i, j = 1, 1
        while True:
            for az in az_seq[::j]:
                for el in el_seq[::i]:
                    if el > el_cutoff and i == -1:
                        continue
                    else:
                        yield (az, el)
                i *= -1
            j *= -1

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
