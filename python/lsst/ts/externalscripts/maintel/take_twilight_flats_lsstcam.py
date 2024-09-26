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

__all__ = ["TakeTwilightFlatsLSSTCam"]

import yaml
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS

from ..base_take_twilight_flats import BaseTakeTwilightFlats


class TakeTwilightFlatsLSSTCam(BaseTakeTwilightFlats):
    """Specialized script for taking Twilight flats with LSSTCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Twilight flats with LSSTCam.")

        self.mtcs = None
        self.LSSTcam = None

    @property
    def tcs(self):
        return self.mtcs

    @property
    def camera(self):
        return self.lsstcam

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

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.lsstcam is None:
            self.log.debug("Creating Camera.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
                tcs_ready_to_take_data=self.tcs.ready_to_take_data,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/take_twilight_flats_lsstcam.yaml
            title: TakeTwilightFlatsLSSTCam v1
            description: Configuration for TakeTwilightFlatsLSSTCam.
            type: object
            properties:
              filter:
                description: Filter name or ID.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
            required: ["filter"]
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeTwilightFlatsLSSTCam, cls).get_schema()

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
        return "LSSTCam"

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
        return f"{self.config.filter}"
