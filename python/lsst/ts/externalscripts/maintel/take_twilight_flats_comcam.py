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

__all__ = ["TakeTwilightFlatsComCam"]

import yaml
from lsst.ts.observatory.control.maintel.comcam import ComCam, ComCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS

from ..base_take_twilight_flats import BaseTakeTwilightFlats


class TakeTwilightFlatsComCam(BaseTakeTwilightFlats):
    """Specialized script for taking Twilight flats with ComCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Twilight flats with ComCam.")

        self.mtcs = None
        self.comcam = None

        self.instrument_name = "LSSTComCam"

    @property
    def tcs(self):
        return self.mtcs

    async def configure_tcs(self) -> None:
        """Handle creating the ATCS object and waiting remote to start."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                log=self.log,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    @property
    def camera(self):
        return self.comcam

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.comcam is None:
            self.log.debug("Creating Camera.")
            self.comcam = ComCam(
                self.domain, intended_usage=ComCamUsages.TakeImage, log=self.log
            )
            await self.comcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/take_twilight_flats_comcam.yaml
            title: TakeTwilightFlatsComCam v1
            description: Configuration for TakeTwilightFlatsComCam.
            type: object
            properties:
              filter:
                description: Filter name or ID.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: "r_03"
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeTwilightFlatsComCam, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    async def get_sky_counts(self) -> float:
        """Abstract method to get the median sky counts from the last image.

        Returns
        -------
        float
            Sky counts in electrons.
        """
        # query consDB with util once such a function exists
        sky_counts = 0
        return sky_counts

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return self.instrument_name

    def get_instrument_configuration(self) -> dict:
        return dict(
            filter=self.config.filter,
        )

    def get_instrument_filter(self) -> str:
        """Get instrument filter configuration.

        Returns
        -------
        instrument_filter: `string`
        """
        filter = self.config.filter
        return f"{filter}"
