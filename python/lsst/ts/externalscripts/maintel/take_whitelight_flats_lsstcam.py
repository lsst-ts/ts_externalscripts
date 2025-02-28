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

__all__ = ["TakeWhiteLightFlatsLSSTCam"]

import asyncio
import functools

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys


class TakeWhiteLightFlatsLSSTCam(salobj.BaseScript):
    """Specialized script for taking Whitelight flats with LSSTCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Whitelight flats with LSSTCam.")

        self.LSSTcam = None
        self.mtcalsys = None

    @property
    def camera(self):
        return self.lsstcam

    async def configure_tcs(self) -> None:
        """Handle creating the ATCS object and waiting remote to start."""
        if self.mtcalsy is None:
            self.log.debug("Creating MTCalsys.")
            self.mtcalsys = MTCalsys(
                domain=self.domain,
                log=self.log,
            )
            await self.mtcalsys.start_task
        else:
            self.log.debug("MTCalsys already defined, skipping.")

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
            $id: https://github.com/lsst-ts/ts_externalscripts/take_whitelight_flats_lsstcam.yaml
            title: TakeWhiteLightFlatsLSSTCam v1
            description: Configuration for TakeWhiteLightFlatsLSSTCam.
            type: object
            properties:
              sequence_name:
                description: Name of sequence in MTCalsys
                type: string
                default: whitelight_r
              use_camera:
                description: Whether or not to take images with LSSTCam
                type: bool
                default: True

            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeWhiteLightFlatsLSSTCam, cls).get_schema()

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
        timeout = 30
        query = f"SELECT * from cbd_lsstcam.exposure_quicklook where exposure_id = {self.latest_exposure_id}"
        item = "post_isr_pixel_median_median"
        get_counts = functools.partial(
            self.client.wait_for_item_in_row,
            query=query,
            item=item,
            timeout=timeout,
        )
        sky_counts = await asyncio.get_running_loop().run_in_executor(None, get_counts)
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

    async def track_radec_and_setup_instrument(self, ra, dec):
        """Method to set the instrument filter and slew to desired field.

        Parameters
        ----------
        ra : float
            RA of target field.
        dec : float
            Dec of target field.
        """
        current_filter = await self.lsstcam.get_current_filter()

        self.tracking_started = True

        if current_filter != self.config.filter:
            self.log.debug(
                f"Filter change required: {current_filter} -> {self.config.filter}"
            )
            await self._handle_slew_and_change_filter(ra, dec)
        else:
            self.log.debug(
                f"Already in the desired filter ({current_filter}), slewing and tracking."
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
        current_filter = await self.lsstcam.get_current_filter()

        if current_filter != self.config.filter:
            self.log.debug(
                f"Filter change required: {current_filter} -> {self.config.filter}"
            )
            await self.lsstcam.setup_filter(filter=self.config.filter)
        else:
            self.log.debug(
                f"Already in the desired filter ({current_filter}), slewing."
            )
