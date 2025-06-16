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

import yaml
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.standardscripts.utils import get_s3_bucket


class TakeWhiteLightFlatsLSSTCam(BaseBlockScript):
    """Specialized script for taking Whitelight flats with LSSTCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Whitelight flats with LSSTCam.")

        self.mtcalsys = None
        self.mtcs = None
        self.lsstcam = None

        self.instrument_setup_time = 30
        self.long_timeout = 30
        self.sequence_summary = dict()
        self.exposure_metadata = dict()
        self.latest_exposure_id = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/take_whitelight_flats_lsstcam.yaml
            title: TakeWhiteLightFlatsLSSTCam v1
            description: Configuration for TakeWhiteLightFlatsLSSTCam.
            type: object
            properties:
              sequence_names:
                description: List of sequence names to run flats for. If "daily",
                             then it polls all available filters.
                type: array
                default: ["daily"]
              config_tcs:
                description: Specifies whether an instance of MTCS should be created.
                             If True then it will be used to take the steps
                             required to set it up the telescope for changing
                             the filter.
                             If False, the filter change operation will be
                             attempted without any prior telescope setup,
                             which may result in failure.
                type: boolean
                default: True
              use_camera:
                description: Will you use the camera during these flats
                type: boolean
                default: True

            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config) -> None:

        self.use_camera = config.use_camera
        self.log.debug(f"Use camera: {self.use_camera}")
        self.config_tcs = config.config_tcs

        """Handle creating the camera object and waiting remote to start."""

        if self.config_tcs and self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
                log=self.log,
            )
            await self.mtcs.start_task
        elif self.config_tcs:
            self.log.debug("MTCS already defined, skipping.")

        if self.use_camera and self.lsstcam is None:
            self.log.debug("Creating Camera.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.All,
                log=self.log,
                mtcs=self.mtcs,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

        """Handle creating the MTCalsys object and waiting remote to start."""
        if self.mtcalsys is None:
            self.log.debug("Creating MTCalsys.")
            if self.use_camera:
                self.mtcalsys = MTCalsys(
                    domain=self.domain, log=self.log, mtcamera=self.lsstcam
                )
            else:
                self.mtcalsys = MTCalsys(domain=self.domain, log=self.log)
            await self.mtcalsys.start_task

        else:
            self.log.debug("MTCalsys already defined, skipping.")

        self.exposure_metadata["note"] = getattr(config, "note", None)
        self.exposure_metadata["reason"] = getattr(config, "reason", None)
        self.exposure_metadata["program"] = getattr(config, "program", None)

        self.use_camera = config.use_camera
        self.sequence_names = config.sequence_names
        if self.sequence_names[0] == "daily":
            self.sequence_names = await self.get_avail_filters()

        self.log.debug(f"Sequences: {self.sequence_names}")

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""
        # Initialize estimate flat exposure time

        total_duration = 0
        self.log.debug(f"Sequence Names: {self.sequence_names}")
        for sequence_name in self.sequence_names:
            config_data = self.mtcalsys.get_calibration_configuration(sequence_name)

            self.log.debug(config_data)
            target_flat_exptime = (
                sum(config_data["exposure_times"]) * config_data["n_flat"]
            )

            # Setup time for the camera (readout and shutter time)
            setup_time_per_image = (
                self.lsstcam.read_out_time + self.lsstcam.shutter_time
            )

            # Total duration calculation
            total_duration += (
                self.instrument_setup_time  # Initial setup time for the instrument
                + target_flat_exptime  # Time for taking all flats
                + setup_time_per_image  # Setup time p/image
            )

        metadata.instrument = "LSSTCam"
        metadata.duration = total_duration

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

    async def get_avail_filters(self):
        """If sequence_names in daily, poll for all installed filters
        and produce a list of sequence names
        Returns
        -------
        `list` of `str`
            The set of sequence names to run based on what filters
            are available.
        """
        avail_filters = await self.lsstcam.get_available_filters()
        self.log.debug(avail_filters)
        avail_filters = avail_filters[0].split(",")
        if "NONE" in avail_filters:
            avail_filters.remove("NONE")
        sequence_names = [f"whitelight_{filter_}_daily" for filter_ in avail_filters]
        return sequence_names

    async def run_block(self):
        """Run to setup the flatfield projector for flats and then take
        the flat images, including fiber spectrograph and electrometer
        """
        for i, sequence_name in enumerate(self.sequence_names):
            self.log.debug(f"GroupID: {self.group_id}")
            self.log.debug(f"ObsID: {self.obs_id}")
            self.exposure_metadata["group_id"] = (
                self.group_id
                if not self.obs_id
                else self.obs_id + f"_{self.salinfo.index}_{i:03}"
            )
            await self.mtcalsys.prepare_for_flat(sequence_name)
            self.log.info("Running calibration sequence")
            sequence_summary = await self.mtcalsys.run_calibration_sequence(
                sequence_name=sequence_name,
                exposure_metadata=self.exposure_metadata,
            )
            self.sequence_summary.update(sequence_summary)

            await self.publish_sequence_summary()
