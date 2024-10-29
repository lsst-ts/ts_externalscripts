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

import asyncio
import functools

import yaml
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS
from lsst.ts.observatory.control.utils import RotType

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

        await self.mtcs.slew_icrs(
            ra=ra,
            dec=dec,
            rot_type=RotType.PhysicalSky,
        )

    async def _handle_slew_and_change_filter(self, ra, dec):
        """Handle slewing and changing filter at the same time.

        For ComCam (and MainCam) we need to send the rotator to zero and keep
        it there while the filter is changing.
        """

        tasks_slew_with_fixed_rot = [
            asyncio.create_task(
                self.mtcs.slew_icrs(
                    ra=ra,
                    dec=dec,
                    rot_type=RotType.Physical,
                )
            ),
        ]

        await self.mtcs.process_as_completed(tasks_slew_with_fixed_rot)

        await self.lsstcam.setup_filter(filter=self.config.filter)

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

        await self.mtcs.point_azel(
            az=az,
            el=el,
        )

    async def setup_instrument(self):
        """Abstract method to set the instrument. Change the filter
        and slew and track target.
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

        await self.mtcs.start_tracking()
