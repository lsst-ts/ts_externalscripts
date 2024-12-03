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

__all__ = ["TakeCBPImageSequenceComCam"]

import yaml
from lsst.ts.observatory.control.maintel.comcam import ComCam, ComCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

from ..base_take_cbp_image_sequence import BaseTakeCBPImageSequence


class TakeCBPImageSequenceComCam(BaseTakeCBPImageSequence):
    """Specialized script for taking CBP images with ComCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take CBP images with ComCam.")

        self.mtcs = None
        self.comcam = None

    @property
    def tcs(self):
        return self.mtcs

    @property
    def camera(self):
        return self.comcam

    async def configure_tcs(self) -> None:
        """Handle creating the MTCS object and waiting remote to start."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.StateTransition | MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.comcam is None:
            self.log.debug("Creating Camera.")
            self.comcam = ComCam(
                self.domain,
                intended_usage=ComCamUsages.TakeImageFull
                | ComCamUsages.StateTransition,
                log=self.log,
                tcs_ready_to_take_data=self.mtcs.ready_to_take_data,
            )
            await self.comcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/take_cbp_image_sequence_comcam.yaml
            title: TakeCBPImageSequenceComCam v1
            description: Configuration for TakeCBPImageSequenceComCam.
            type: object
            properties:
              filter:
                description: Filter name or ID.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeCBPImageSequenceComCam, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return "LSSTComCam"

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
        current_filter = await self.comcam.get_current_filter()

        if current_filter != self.config.filter:
            self.log.debug(
                f"Filter change required: {current_filter} -> {self.config.filter}"
            )
            await self.comcam.setup_filter(filter=self.config.filter)
        else:
            self.log.debug(
                f"Already in the desired filter ({current_filter}), slewing."
            )

        await self.mtcs.point_azel(
            az=az,
            el=el,
            rot_tel=self.tma_rotator_angle,
        )

    async def configure(self, config):
        """Take the sequence of twilight flats twilight flats."""
        self.configure_client()
        await super().configure(config)
