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
import types

import numpy as np
import yaml
from astropy import coordinates
from astropy import units as u
from astroquery.vizier import Vizier
from lsst.summit.utils import ConsDbClient
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


class BaseTakeTwilightFlats(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base class for taking twilight flats."""

    def __init__(self, index, descr="Base script for taking twilight flats.") -> None:
        super().__init__(index, descr)

        self.config = None

        self.instrument_setup_time = 0.0

        self.long_timeout = 30

        self.client = ConsDbClient()

    @property
    @abc.abstractmethod
    def tcs(self):
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

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

    @abc.abstractmethod
    async def get_sky_counts(self) -> float:
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
                description: >
                  Target sky intensity in electron counts for the twilight flats.
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 15000
                description: Target mean electron count for twilight flats.
              n_flat:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 20
                description: Number of flats to take.
              dither:
                description: Distance to dither in between images in arcsec azimuth.
                type: float
                default: 0
              max_exp_time:
                description: Maximum exposure time allowed.
                type: float
                default: 300
              min_sun:
                description: Lowest position of sun in degrees at which twilight flats can be taken.
                type: float
                default: -3.0
              max_sun:
                description: Highest position in degrees of sun at which twilight flats can be taken.
                type: float
                default: 0.0
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

    async def offset_telescope(self):
        """Dither the camera between exposures if desired."""
        await self.tcs.offset_azel(
            az=self.config.dither,
            el=0,
            relative=True,
            absorb=False,
        )

    async def configure(self, config: types.SimpleNamespace):
        """Configure script components including camera.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        await self.configure_tcs()
        await self.configure_camera()

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
        target_flat_exptime = 30

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
        """Configure script components including camera.

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

        return self.config.target_sky_counts * exp_time / sky_counts

    def get_target_radec(self, distance_from_sun=180, target_el=45, time=None):
        """
        Returns the RADEC of the target area of the sky that's an azimuth
        `distance_from_sun` away from the Sun, given `elevation`,
        and at a given `time`.

        Parameters
        ----------
        distance_from_sun : float, (-180, 180)
            The distance from the Sun in degrees.
            Positive angles go towards the North.
        elevation : float
            Target elevation for Sky Flats.
        time : datetime
            The time for the calculation in UTC.
        """

        az_sun, el_sun = self.tcs.get_sun_azel()

        target_az = (az_sun + distance_from_sun) % 360

        target_radec = self.tcs.radec_from_azel(target_az, target_el)

        return target_radec

    def get_empty_field(self, target, radius=5):
        """
        Query the "Deep blank field catalogue : J/MNRAS/427/679" in Vizier.

        Parameters
        ----------
        target : astropy.coordinates.SkyCoord
            Sky coordinates near the field
        radius : float
            Search radius in degrees.

        Reference
        ---------
        http://cdsarc.u-strasbg.fr/viz-bin/Cat?J/MNRAS/427/679
        """
        _table = Vizier.query_region(
            catalog="J/MNRAS/427/679/blank_fld",
            coordinates=target,
            radius=radius * u.deg,
        )

        if len(_table) == 0:
            self.log.info(
                f"Could not find a field near {target} " f"within {radius} deg radius"
            )
            return None

        _table = _table["J/MNRAS/427/679/blank_fld"]

        coords = coordinates.SkyCoord(
            ra=_table["RAJ2000"],
            dec=_table["DEJ2000"],
            unit=(u.hourangle, u.deg),
            frame=coordinates.ICRS,
        )

        arg = target.separation(coords).argmin()

        return coords[arg]

    def confirm_sun_location(self):
        """Confirm sun's elevation is safe for taking twilight flats."""
        sun_coordinates = self.tcs.get_sun_azel()
        where_sun = "setting" if (sun_coordinates[0] > 180) else "rising"
        self.log.debug(
            f" The azimuth of the {where_sun} Sun is {sun_coordinates[0]:.2f} deg \n"
            f" The elevation of the Sun is {sun_coordinates[1]:.2f} deg"
        )

        if (where_sun < self.config.min_sun) or (where_sun > self.config.max_sun):
            raise Exception(
                f"Sun elevation {where_sun} is outside appropriate elvation limits. Aborting."
            )

    async def take_twilight_flats(self):

        # Setup instrument filter
        try:
            await self.camera.setup_instrument(filter=self.get_instrument_filter())
        except salobj.AckError:
            self.log.warning(
                f"Filter is already set to {self.get_instrument_filter()}. "
                f"Continuing."
            )

        group_id = self.group_id if self.obs_id is None else self.obs_id

        self.confirm_sun_location()

        target = self.get_target_radec()

        # get an empty field
        search_area_degrees = 10

        empty_field_coords = self.get_empty_field(target, radius=search_area_degrees)
        self.log.info(
            f"ICRS Empty field coordinates:\n"
            f"  RA  = {empty_field_coords.ra.to_string(u.hour, sep=':')} ;"
            f" DEC = {empty_field_coords.dec.to_string(u.degree, alwayssign=True, sep=':')}"
        )

        # slew to desired field
        await self.tcs.slew_icrs(empty_field_coords.ra, empty_field_coords.dec)

        # Take one 1s flat to calibrate the exposure time
        self.log.info("Taking 1s flat to calibrate exposure time.")
        exp_time = 1
        await self.camera.take_flats(
            exptime=exp_time,
            nflats=1,
            group_id=group_id,
            program=self.program,
            reason=self.reason,
        )

        for i in range(self.config.n_flat):

            sky_counts = await self.get_sky_counts()
            self.log.info(
                f"Flat just taken with exposure time {exp_time} had counts of {sky_counts}"
            )

            exp_time = self.get_new_exptime(sky_counts, exp_time)

            if exp_time > self.config.max_exp_time:
                raise Exception(
                    f"Calculated exposure time {exp_time} above max exposure time. Aborting."
                )

            await self.checkpoint(
                f"Taking flat {i + 1} of {self.config.n_flat} with exposure time {exp_time}."
            )

            if np.abs(self.config.dither) > 0:
                self.offset_telescope()

            await self.camera.take_flats(
                exptime=exp_time,
                nflats=1,
                group_id=group_id,
                program=self.program,
                reason=self.reason,
            )

            self.confirm_sun_location()

    async def assert_feasibility(self) -> None:
        """Verify that camera is in a feasible state to
        execute the script.
        """
        await self.camera.assert_all_enabled()

    async def run_block(self):
        """Run the block of tasks to take PTC flats sequence."""

        await self.assert_feasibility()
        await self.take_twilight_flats()
