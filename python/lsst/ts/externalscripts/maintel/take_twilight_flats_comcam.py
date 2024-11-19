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

import asyncio
import functools
import warnings

import yaml
from lsst.ts.observatory.control.maintel.comcam import ComCam, ComCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.observatory.control.utils import RotType

try:
    from lsst.summit.utils import ConsDbClient
    from lsst.summit.utils.utils import computeCcdExposureId
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


from ..base_take_twilight_flats import BaseTakeTwilightFlats


class TakeTwilightFlatsComCam(BaseTakeTwilightFlats):
    """Specialized script for taking Twilight flats with ComCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Twilight flats with ComCam.")

        self.mtcs = None
        self.comcam = None

    @property
    def tcs(self):
        return self.mtcs

    @property
    def camera(self):
        return self.comcam

    async def configure_tcs(self) -> None:
        """Handle creating the ATCS object and waiting remote to start."""
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

    def configure_client(self) -> None:
        """Handle creating the ConsDB client and waiting remote to start."""
        if self.client is None:
            self.log.debug("Creating ConsDB client.")
            self.client = ConsDbClient("http://consdb-pq.consdb:8080/consdb")
        else:
            self.log.debug("ConsDB client already defined, skipping.")

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
            required: ["filter"]
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
        timeout = 60
        detector_num = 4
        ccd_exp_id = computeCcdExposureId(
            "LSSTComCam", self.latest_exposure_id, detector_num
        )

        query = f"SELECT * from cdb_lsstcomcam.ccdvisit1_quicklook \
            where ccdvisit_id={ccd_exp_id}"
        item = "postisr_pixel_median"
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

    async def track_radec_and_setup_instrument(self, ra, dec):
        """Method to set the instrument filter and slew to desired field.

        Parameters
        ----------
        ra : float
            RA of target field.
        dec : float
            Dec of target field.
        """

        await self.mtcs.slew_icrs(
            ra=ra,
            dec=dec,
            rot_type=RotType.Physical,
            rot=0,
        )

        current_filter = await self.comcam.get_current_filter()

        if current_filter != self.config.filter:
            self.log.debug(
                f"Filter change required: {current_filter} -> {self.config.filter}"
            )
            await self.comcam.setup_filter(filter=self.config.filter)
        else:
            self.log.debug(
                f"Already in the desired filter ({current_filter}), slewing and tracking."
            )

        await self.mtcs.slew_icrs(
            ra=ra,
            dec=dec,
            rot_type=RotType.PhysicalSky,
            rot=self.config.rotator_angle,
        )

        self.tracking_started = True

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
            rot_tel=self.config.rotator_angle,
        )

    async def configure(self, config):
        """Take the sequence of twilight flats twilight flats."""
        self.configure_client()
        await super().configure(config)
