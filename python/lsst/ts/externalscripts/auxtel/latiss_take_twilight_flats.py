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

__all__ = ["TakeTwilightFlatsLatiss"]

import warnings

import numpy as np
import yaml
from lsst.ts.observatory.control.auxtel.atcs import ATCS
from lsst.ts.observatory.control.auxtel.latiss import LATISS, LATISSUsages
from lsst.ts.observatory.control.utils import RotType

from ..base_take_twilight_flats import BaseTakeTwilightFlats

try:
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import (
        get_image_sync as get_image,
    )
    from lsst.ts.observing.utilities.auxtel.latiss.utils import parse_visit_id
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


class TakeTwilightFlatsLatiss(BaseTakeTwilightFlats):
    """Specialized script for taking Twilight flats with LATISS."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Twilight flats with LATISS.")

        self.atcs = None
        self.latiss = None

    @property
    def tcs(self):
        return self.atcs

    @property
    def camera(self):
        return self.latiss

    async def configure_tcs(self) -> None:
        """Handle creating the ATCS object and waiting remote to start."""
        if self.atcs is None:
            self.log.debug("Creating ATCS.")
            self.atcs = ATCS(
                domain=self.domain,
                log=self.log,
            )
            await self.atcs.start_task
        else:
            self.log.debug("ATCS already defined, skipping.")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.latiss is None:
            self.log.debug("Creating Camera.")
            self.latiss = LATISS(
                self.domain,
                intended_usage=LATISSUsages.TakeImageFull,
                log=self.log,
                tcs_ready_to_take_data=self.atcs.ready_to_take_data,
            )
            await self.latiss.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/take_twilight_flats_latiss.yaml
            title: TakeTwilightFlatsLatiss v1
            description: Configuration for TakeTwilightFlatsLatiss.
            type: object
            properties:
              filter:
                description: Filter name or ID.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
              grating:
                description: Grating name; if omitted the grating is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: "empty_1"
            required: ["filter"]
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeTwilightFlatsLatiss, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    def get_sky_counts(self) -> float:
        """Abstract method to get the median sky counts from the last image.

        Returns
        -------
        float
            Sky counts in electrons.
        """
        best_effort_isr = BestEffortIsr()
        timeout_get_image = 30

        # Get latest image
        latest_exposure = get_image(
            parse_visit_id(self.latest_exposure_id),
            best_effort_isr,
            timeout=timeout_get_image,
        )

        sky_counts = np.nanmedian(latest_exposure.image.array)

        return sky_counts

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return "LATISS"

    def get_instrument_configuration(self) -> dict:
        return dict(
            filter=self.config.filter,
            grating=self.config.grating,
            linear_stage=self.config.linear_stage,
        )

    def get_instrument_filter(self) -> str:
        """Get instrument filter configuration.

        Returns
        -------
        instrument_filter: `string`
        """
        return f"{self.config.filter}~{self.config.grating}"

    async def track_radec_and_setup_instrument(self, ra, dec):
        """Method to set the instrument filter and slew to desired field.

        Parameters
        ----------
        ra : float
            RA of target field.
        dec : float
            Dec of target field.
        """
        # slew to desired field
        await self.tcs.slew_icrs(
            ra,
            dec,
            rot_type=RotType.PhysicalSky,
        )

        await self.latiss.setup_instrument(
            filter=self.config.filter,
            grating=self.config.grating,
        )

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
        # slew to desired field
        await self.tcs.point_azel(
            az,
            el,
        )

        await self.latiss.setup_instrument(
            filter=self.config.filter,
            grating=self.config.grating,
        )

    async def setup_instrument(self, az, el):
        """Abstract method to set the instrument. Change the filter
        and start tracking.
        """
        await self.tcs.start_tracking()

        await self.latiss.setup_instrument(
            filter=self.config.filter,
            grating=self.config.grating,
        )
