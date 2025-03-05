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

# import asyncio

from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys

from ..base_take_dome_flats import BaseTakeDomeFlats


class TakeWhiteLightFlatsLSSTCam(BaseTakeDomeFlats):
    """Specialized script for taking Whitelight flats with LSSTCam."""

    def __init__(self, index):
        super().__init__(index=index, descr="Take Whitelight flats with LSSTCam.")

        self.mtcalsys = None
        self.mtcamera = None
        self.config_data = None

        self.instrument_setup_time = 30

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
                # tcs_ready_to_take_data=self.tcs.ready_to_take_data,
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
        return f"{self.config_data.mtcamera_filter}"

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""
        n_flats = self.config.n_flat

        # Initialize estimate flat exposure time
        self.log.debug(self.config_data)
        target_flat_exptime = sum(self.config_data.exposure_times)

        # Setup time for the camera (readout and shutter time)
        setup_time_per_image = self.lsstcam.read_out_time + self.lsstcam.shutter_time

        # Total duration calculation
        total_duration = (
            self.instrument_setup_time  # Initial setup time for the instrument
            + target_flat_exptime * (n_flats)  # Time for taking all flats
            + setup_time_per_image * (n_flats)  # Setup time p/image
        )

        metadata.duration = total_duration
        metadata.calib_type = self.config_data.calib_type
        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    async def take_dome_flat(self):
        """Method to setup the flatfield projector for flats and then take
        the flat images, including fiber specgtrograph and electrometer
        """
        self.mtcalsys.prepare_for_flat(self.config.sequence_name)
        self.mtcalsys.run_calibration_sequence(
            self.config.sequence_name,
        )
