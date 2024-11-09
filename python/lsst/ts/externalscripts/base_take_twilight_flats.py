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

__all__ = ["BaseTakeTwilightFlats"]

import abc
import asyncio
import functools
import types

import numpy as np
import yaml
from astropy import coordinates
from astropy import units as u
from astroquery.vizier import Vizier
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript

"""
try:
    from lsst.summit.utils import ConsDbClient
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")
"""


class BaseTakeTwilightFlats(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base class for taking twilight flats."""

    def __init__(self, index, descr="Base script for taking twilight flats.") -> None:
        super().__init__(index, descr)

        self.config = None

        self.instrument_setup_time = 0.0

        self.long_timeout = 30

        self.latest_exposure_id = None

        self.client = None

        self.vizier = None

        self.where_sun = None

    @property
    @abc.abstractmethod
    def tcs(self):
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    @property
    def consdb(self):
        return self.client

    @property
    def catalog(self):
        return self.vizier

    @abc.abstractmethod
    async def configure_tcs(self):
        """Abstract method to configure the TCS."""
        raise NotImplementedError()

    @abc.abstractmethod
    async def configure_camera(self):
        """Abstract method to configure the camera, to be implemented
        in subclasses.
        """
        raise NotImplementedError()

    '''
    def configure_consdb(self):
        """Method to configure the consdb client."""
        if self.client is None:
            self.log.debug("Creating consdb client.")
            self.client = ConsDbClient("http://consdb-pq.consdb:8080/consdb")
        else:
            self.log.debug("Client already defined, skipping.")
    '''

    def configure_catalog(self):
        """Method to configure the catalog."""
        if self.vizier is None:
            self.log.debug("Creating Vizier catalog.")
            self.vizier = Vizier
        else:
            self.log.debug("Catalog already defined, skipping.")

    @abc.abstractmethod
    def get_sky_counts(self) -> float:
        """Abstract method to get the median sky counts from the last image.

        Returns
        -------
        float
            Sky counts in electrons.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_name(self):
        """Abstract method to be defined in subclasses to provide the
        instrument name.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_configuration(self) -> dict:
        """Abstract method to get the instrument configuration.

        Returns
        -------
        dict
            Dictionary with instrument configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_filter(self) -> str:
        """Abstract method to get the instrument filter configuration.

        Returns
        -------
        str
            Instrument filter configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def track_radec_and_setup_instrument(self, ra, dec):
        """Abstract method to set the instrument. Change the filter
        and slew and track target.

        Parameters
        ----------
        ra : float
            RA of target field.
        dec : float
            Dec of target field.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def slew_azel_and_setup_instrument(self, az, el):
        """Abstract method to set the instrument. Change the filter
        and slew and track target.

        Parameters
        ----------
        az : float
            Azimuth of target field.
        el : float
            Elevation of target field.
        """
        raise NotImplementedError()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/base_take_twilight_flats.yaml
            title: BaseTakeTwilightFlats
            description: Configuration schema for BaseTakeTwilightFlats.
            type: object
            properties:
              target_sky_counts:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 15000
                description: Target mean electron count for twilight flats.
              max_counts:
                description: Maximum counts tolerable in a sky flat
                anyOf:
                  - type: integer
                    minimum: 0
                default: 60000
              n_flat:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 20
                description: Number of flats to take.
              dither:
                description: Distance to dither in between images in arcsec azimuth.
                type: number
                default: 0.0
              max_exp_time:
                description: Maximum exposure time allowed.
                type: number
                default: 30.0
              min_exp_time:
                description: Minimum exposure time allowed.
                type: number
                minimum: 0.1
                default: 1.0
              min_sun_elevation:
                description: Lowest position of sun in degrees at which twilight flats can be taken.
                type: number
                default: -18.0
              max_sun_elevation:
                description: Highest position in degrees of sun at which twilight flats can be taken.
                type: number
                default: 0.0
              distance_from_sun:
                description: The distance from the Sun in degrees. Positive angles go towards the North.
                type: number
                minimum: -180.0
                maximum: 180.0
                default: 179.0
              target_el:
                description: Target elevation for sky flats.
                type: number
                minimum: 0.0
                maximum: 90.0
                default: 45.0
              target_az:
                description: Target azimuth for sky flats.
                type: number
                default: 90
              point_directly:
                description: If True, point at target az el. If False, point relative to sun.
                type: boolean
                default: False
              tracking:
                description: If True, track sky. If False, keep az and el constant.
                type: boolean
                default: True
              ignore:
                description: >-
                    CSCs from the camera group to ignore in status check.
                    Name must match those in self.group.components.
                type: array
                items:
                  type: string

            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config: types.SimpleNamespace):
        """Configure script components including camera.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        await self.configure_tcs()
        await self.configure_camera()
        # self.configure_consdb()
        self.configure_catalog()

        if hasattr(config, "ignore"):
            for comp in config.ignore:
                if comp in self.camera.components_attr:
                    self.log.debug(f"Ignoring Camera component {comp}.")
                    setattr(self.camera.check, comp, False)
                else:
                    self.log.warning(
                        f"Component {comp} not in CSC Group. "
                        f"Must be one of {self.camera.components_attr}. "
                        f"Ignoring."
                    )

        self.config = config

        await super().configure(config)

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""

        n_flats = self.config.n_flat

        # Initialize estimate flat exposure time
        target_flat_exptime = (self.config.max_exp_time + self.config.min_exp_time) / 2

        # Setup time for the camera (readout and shutter time)
        setup_time_per_image = self.camera.read_out_time + self.camera.shutter_time

        # Total duration calculation
        total_duration = (
            self.instrument_setup_time  # Initial setup time for the instrument
            + target_flat_exptime * (n_flats)  # Time for taking all flats
            + setup_time_per_image * (n_flats)  # Setup time p/image
        )

        metadata.duration = total_duration
        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    def get_new_exptime(self, sky_counts, exp_time):
        """Calculate exposure time for next image.

        Parameters
        ----------
        sky_counts : float
            Counts in electrons of previous flat.
        exp_time : float
            Exposure time of previous flat

        Returns
        -------
        float
            Calculated new exposure time.
        """
        new_exp_time = self.config.target_sky_counts * exp_time / sky_counts

        if new_exp_time < self.config.min_exp_time:
            if (
                self.config.max_counts * exp_time / sky_counts
                > self.config.min_exp_time
            ):
                # return a short exposure time if the max counts
                # won't be exceeded
                return self.config.min_exp_time * 1.01

        return round(new_exp_time, 2)

    def get_target_radec(self):
        """
        Returns the RADEC of the target area of the sky that's an azimuth
        `distance_from_sun` away from the Sun, given `elevation`,
        and at a given `time`.

        Returns
        ----------
        target_radec :
            target ra dec
        """

        min_sun_distance = 60

        az_sun, el_sun = self.tcs.get_sun_azel()

        if self.config.point_directly:
            if np.abs(az_sun - (self.config.target_az % 360)) < min_sun_distance:
                raise RuntimeError(
                    f"Distance from sun {az_sun - (self.config.target_az % 360)} is \
                        less than {min_sun_distance}. Stopping."
                )

            target_az = self.config.target_az
        else:
            if np.abs(self.config.distance_from_sun) < min_sun_distance:
                raise RuntimeError(
                    f"Distance from sun {self.config.distance_from_sun} is less than {min_sun_distance}. \
                        Stopping."
                )

            target_az = (az_sun + self.config.distance_from_sun) % 360

        target_radec = self.tcs.radec_from_azel(target_az, self.config.target_el)

        return target_radec

    def get_target_az(self):
        """
        Returns the AZ of the target area of the sky that's an azimuth
        `distance_from_sun` away from the Sun, given `elevation`,
        and at a given `time`.

        returns
        ----------
        target_az : float, (-180, 180)
            The target azimuth in degrees
        """

        az_sun, el_sun = self.tcs.get_sun_azel()

        target_az = (az_sun + self.config.distance_from_sun) % 360

        return target_az

    async def get_twilight_flat_sky_coords(self, target, radius=5):
        """
        Query the "Deep blank field catalogue : J/MNRAS/427/679" in Vizier.

        Parameters
        ----------
        target : astropy.coordinates.SkyCoord
            Sky coordinates near the field
        radius : float
            Search radius in degrees.

        Returns
        ----------
        ra : astropy.coordinates.SkyCoord
            Right ascension of the twilight flats
        dec : astropy.coordinates.SkyCoord
            Declination of the twilight flats

        Reference
        ---------
        http://cdsarc.u-strasbg.fr/viz-bin/Cat?J/MNRAS/427/679
        """
        query_region = functools.partial(
            self.vizier.query_region,
            catalog="J/MNRAS/427/679/blank_fld",
            coordinates=target,
            radius=radius * u.deg,
        )

        _table = await asyncio.get_event_loop().run_in_executor(None, query_region)

        if len(_table) == 0:
            self.log.info(
                f"Could not find a field near {target} within {radius} deg radius"
            )
            return target.ra, target.dec

        self.log.debug(f"Table is {_table}")

        _table = _table["J/MNRAS/427/679/blank_fld"]

        coords = coordinates.SkyCoord(
            ra=_table["RAJ2000"],
            dec=_table["DEJ2000"],
            unit=(u.hourangle, u.deg),
            frame=coordinates.ICRS,
        )

        arg = target.separation(coords).argmin()

        self.log.info(
            f"ICRS Empty field coordinates:\n"
            f"  RA  = {coords[arg].ra.to_string(u.hour, sep=':')} ;"
            f" DEC = {coords[arg].dec.to_string(u.degree, alwayssign=True, sep=':')}"
        )

        return coords[arg].ra, coords[arg].dec

    def assert_sun_location(self):
        """Confirm sun's elevation is safe for taking twilight flats."""
        sun_coordinates = self.tcs.get_sun_azel()
        self.where_sun = "setting" if (sun_coordinates[0] > 180) else "rising"
        self.log.debug(
            f" The azimuth of the {self.where_sun} Sun is {sun_coordinates[0]:.2f} deg \n"
            f" The elevation of the Sun is {sun_coordinates[1]:.2f} deg"
        )

        if (sun_coordinates[1] < self.config.min_sun_elevation) or (
            sun_coordinates[1] > self.config.max_sun_elevation
        ):
            raise RuntimeError(
                f"Sun elevation {sun_coordinates} is outside appropriate elevation limits. \
            Must be above {self.config.min_sun_elevation} or below {self.config.max_sun_elevation}."
            )

    async def take_twilight_flats(self):
        """Take the sequence of twilight flats twilight flats."""
        self.assert_sun_location()

        target = self.get_target_radec()

        # get an empty field
        search_area_degrees = 0.05

        if self.config.tracking:
            ra, dec = await self.get_twilight_flat_sky_coords(
                target, radius=search_area_degrees
            )

            await self.track_radec_and_setup_instrument(ra, dec)
        else:
            az = self.get_target_az()

            await self.slew_azel_and_setup_instrument(az, self.config.target_el)

        # Take one 1s flat to calibrate the exposure time
        self.log.info(
            "Taking {self.config.min_exp_time}s flat to calibrate exposure time."
        )
        exp_time = self.config.min_exp_time
        # TODO: change from take_acq to take_sflat (DM-46675)
        flat_image = await self.camera.take_acq(
            exptime=exp_time,
            n=1,
            group_id=self.group_id,
            program=self.program,
            reason=self.reason,
        )

        self.log.debug("First image taken")

        self.latest_exposure_id = int(flat_image[0])

        i = 0

        while i < self.config.n_flat:

            # TODO: make consistent with LATISS and comcam
            sky_counts = await self.get_sky_counts()
            self.log.info(
                f"Flat just taken with exposure time {exp_time} had counts of {sky_counts}"
            )

            exp_time = self.get_new_exptime(sky_counts, exp_time)

            if exp_time > self.config.max_exp_time:
                self.log.warning(
                    f"Calculated exposure time {exp_time} above max exposure time \
                        {self.config.max_exp_time} s. Taking images with exposure \
                            time {self.config.max_exp_time}."
                )
                exp_time = self.config.max_exp_time

            if exp_time < self.config.min_exp_time:
                self.log.warning(
                    f"Calculated exposure time {exp_time} below min exposure time \
                        {self.config.min_exp_time}. Stopping."
                )
                break

            await self.checkpoint(
                f"Taking flat {i+1} of {self.config.n_flat} with exposure time {exp_time}."
            )

            if np.abs(self.config.dither) > 0:
                await self.tcs.offset_azel(
                    az=self.config.dither,
                    el=0,
                    relative=True,
                    absorb=False,
                )

            # TODO: change from take_acq to take_sflat (DM-46675)
            flat_image = await self.camera.take_acq(
                exptime=exp_time,
                n=1,
                group_id=self.group_id,
                program=self.program,
                reason=self.reason,
            )

            self.latest_exposure_id = int(flat_image[0])

            self.log.debug(f"Just took image {i} of {self.config.n_flat}")

            self.assert_sun_location()

            i += 1

            exp_repeat_time = 2

            if (exp_time < exp_repeat_time) and (self.where_sun != "rising"):
                # take fast repeated images if the exposure time is short
                nrepeats = 4

                for k in range(nrepeats):

                    if np.abs(self.config.dither) > 0:
                        await self.tcs.offset_azel(
                            az=self.config.dither,
                            el=0,
                            relative=True,
                            absorb=False,
                        )

                    # TODO: change from take_acq to take_sflat (DM-46675)
                    flat_image = await self.camera.take_acq(
                        exptime=exp_time,
                        n=1,
                        group_id=self.group_id,
                        program=self.program,
                        reason=self.reason,
                    )

                    self.latest_exposure_id = int(flat_image[0])

                    i += 1
                    self.log.debug(f"Just took image {i} of {self.config.n_flat}")

                    self.assert_sun_location()

        await self.camera.take_darks(
            exptime=15,
            ndarks=40,
            group_id=self.group_id,
            program=self.program,
            reason=self.reason,
        )

    async def assert_feasibility(self) -> None:
        """Verify that camera is in a feasible state to
        execute the script.
        """
        await self.camera.assert_all_enabled()

    async def run_block(self):
        """Run the block of tasks to take PTC flats sequence."""

        await self.assert_feasibility()
        await self.take_twilight_flats()
