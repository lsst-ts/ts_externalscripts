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

    @abc.abstractmethod
    async def configure_tcs(self):
        """Abstract method to configure the TCS."""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    async def configure_camera(self):
        """Abstract method to configure the camera, to be implemented
        in subclasses.
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

    @abc.abstractmethod
    def get_sky_counts(self) -> float:
        """Abstract method to get the median sky counts from the last image.

        Returns
        -------
        float
            Sky counts in electrons.
        """
        raise NotImplementedError()

    def offset_telescope(self):
        """Abstract method to dither the camera if desired."""
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

        self.client = self.make_consdb_client()

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

            sky_counts = self.get_sky_counts()
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

    async def assert_feasibility(self) -> None:
        """Verify that camera is in a feasible state to
        execute the script.
        """
        await self.camera.assert_all_enabled()

    async def run_block(self):
        """Run the block of tasks to take PTC flats sequence."""

        await self.assert_feasibility()
        await self.take_twilight_flats()
