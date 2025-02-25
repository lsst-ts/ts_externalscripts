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

import hashlib
import io
import json

from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys
from lsst.ts.standardscripts.utils import get_s3_bucket

from ..base_take_dome_flats import BaseTakeDomeFlats


class TakeWhiteLightFlatsLSSTCam(BaseTakeDomeFlats):
    """Specialized script for taking Whitelight flats with LSSTCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Whitelight flats with LSSTCam.")

        self.mtcalsys = None
        self.mtcamera = None
        self.config_data = None

        self.instrument_setup_time = 30
        self.sequence_summary = dict()
        self.exposure_metadata = dict()

    @property
    def camera(self):
        return self.mtcamera

    async def configure_calsys(self) -> None:
        """Handle creating the MTCalsys object and waiting remote to start."""
        if self.mtcalsys is None:
            self.log.debug("Creating MTCalsys.")
            if self.config.use_camera:
                self.mtcalsys = MTCalsys(
                    domain=self.domain, log=self.log, mtcamera=self.mtcamera
                )
            else:
                self.mtcalsys = MTCalsys(domain=self.domain, log=self.log)
            await self.mtcalsys.start_task

        else:
            self.log.debug("MTCalsys already defined, skipping.")

        self.exposure_metadata["note"] = getattr(self.config, "note", None)
        self.exposure_metadata["reason"] = getattr(self.config, "reason", None)
        self.exposure_metadata["program"] = getattr(self.config, "program", None)

        self.config_data = self.mtcalsys.get_calibration_configuration(
            self.config.sequence_name
        )
        self.log.debug(f"Config data: {self.config_data}")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""

        if self.mtcamera is None:
            self.log.debug("Creating Camera.")
            self.mtcamera = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
            )
            await self.mtcamera.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return "LSSTCam"

    def get_instrument_filter(self) -> str:
        """Get instrument filter configuration.

        Returns
        -------
        instrument_filter: `string`
        """
        return f"{self.config_data['mtcamera_filter']}"

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""
        n_flats = self.config.n_flat

        # Initialize estimate flat exposure time
        self.log.debug(self.config_data)
        target_flat_exptime = sum(self.config_data["exposure_times"])

        # Setup time for the camera (readout and shutter time)
        setup_time_per_image = self.lsstcam.read_out_time + self.lsstcam.shutter_time

        # Total duration calculation
        total_duration = (
            self.instrument_setup_time  # Initial setup time for the instrument
            + target_flat_exptime * (n_flats)  # Time for taking all flats
            + setup_time_per_image * (n_flats)  # Setup time p/image
        )

        metadata.duration = total_duration
        metadata.calib_type = self.config_data["calib_type"]
        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    async def prepare_summary_table(self):
        """Prepare final summary table.

        Checks writing is possible and that s3 bucket can be made
        """

        # Take a copy as the starting point for the summary
        self.sequence_summary = {}

        # Add metadata from this script
        date_begin = utils.astropy_time_from_tai_unix(utils.current_tai()).isot
        self.sequence_summary["date_begin_tai"] = date_begin
        self.sequence_summary["script_index"] = self.salinfo.index

    async def publish_sequence_summary(self):
        """Write sequence summary to LFA as a json file"""

        try:
            sequence_summary_payload = json.dumps(self.sequence_summary).encode()
            file_object = io.BytesIO()
            byte_size = file_object.write(sequence_summary_payload)
            file_object.seek(0)

            s3bucket = get_s3_bucket()

            key = s3bucket.make_key(
                salname=self.salinfo.name,
                salindexname=self.salinfo.index,
                generator="publish_sequence_summary",
                date=utils.astropy_time_from_tai_unix(utils.current_tai()),
                other=self.obs_id,
                suffix=".json",
            )

            await s3bucket.upload(fileobj=file_object, key=key)

            url = f"{s3bucket.service_resource.meta.client.meta.endpoint_url}/{s3bucket.name}/{key}"

            md5 = hashlib.md5()
            md5.update(sequence_summary_payload)

            await self.evt_largeFileObjectAvailable.set_write(
                id=self.obs_id,
                url=url,
                generator="publish_sequence_summary",
                mimeType="JSON",
                byteSize=byte_size,
                checkSum=md5.hexdigest(),
                version=1,
            )

        except Exception:
            msg = "Failed to save summary table."
            self.log.exception(msg)
            raise RuntimeError(msg)

    async def take_dome_flat(self):
        """Method to setup the flatfield projector for flats and then take
        the flat images, including fiber spectrograph and electrometer
        """

        self.exposure_metadata["group_id"] = (
            self.group_id if self.obs_id is None else self.obs_id
        )
        self.mtcalsys.prepare_for_flat(self.config.sequence_name)
        for n in range(self.config.n_flat):
            sequence_summary = self.mtcalsys.run_calibration_sequence(
                sequence_name=self.config.sequence_name,
                exposure_metadata=self.exposure_metadata,
            )
            self.sequence_summary.update(sequence_summary)

        await self.publish_sequence_summary()
