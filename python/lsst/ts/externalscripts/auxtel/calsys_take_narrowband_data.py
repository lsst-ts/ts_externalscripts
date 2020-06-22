# This file is part of ts_externalscripts
#
# Developed for the LSST Data Management System.
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

__all__ = ["CalSysTakeNarrowbandData"]

import asyncio

import numpy as np
import yaml

from lsst.ts import salobj
from .calsys_takedata import is_sequence, as_array

from lsst.ts.idl.enums import ATMonochromator
import csv
import datetime
import os
import pathlib
import requests


class CalSysTakeNarrowbandData(salobj.BaseScript):
    """
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Configure and take LATISS data using the"
            "auxiliary telescope CalSystem.",
        )
        self.cmd_timeout = 60
        self.change_grating_time = 60
        self.electrometer = salobj.Remote(
            domain=self.domain, name="Electrometer", index=1
        )
        self.monochromator = salobj.Remote(domain=self.domain, name="ATMonochromator")
        self.fiber_spectrograph = salobj.Remote(
            domain=self.domain, name="FiberSpectrograph"
        )
        self.atcamera = salobj.Remote(domain=self.domain, name="ATCamera")
        self.atspectrograph = salobj.Remote(domain=self.domain, name="ATSpectrograph")
        self.atarchiver = salobj.Remote(domain=self.domain, name="ATArchiver")

    @classmethod
    def get_schema(cls):
        yaml_schema = """
            $schema: http://json-schema/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/CalSysTakeNarrowbandData.yaml
            title: CalSysTakeNarrowbandData v1
            description: Configuration for CalSysTakeNarrowbandData.
            type: object
            properties:
              wavelengths:
                type: array
                items:
                  type: number
                  minItems: 1
              integration_times:
                type: array
                items:
                  type: number
                  minItems: 1
              fiber_spectrograph_integration_times:
                type: array
                items:
                  type: number
                  minItems: 1
              mono_grating_types:
                type: integer
                minimum: 1
                maximum: 3
                default: [1]
              mono_entrance_slit_widths:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [2]
              mono_exit_slit_widths:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [4]
              image_types:
                type: array
                items:
                  type: string
                  minItems: 1
                default: ["Kilos"]
              lamps:
                type: array
                items:
                  type: string
                  minItems: 1
                default: ["lamps"]
              fiber_spectrometer_delays:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [1]
              latiss_filter:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [0]
              latiss_grating:
                type: array
                items:
                  type: integer
                  minItems: 1
                default: [0]
              latiss_stage_pos:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [60]
              nimages_per_wavelength:
                type: array
                items:
                  type: integer
                  minItems: 1
                default: [1]
              shutter:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [1]
              image_sequence_name:
                type: array
                items:
                  type: string
                  minItems: 1
                default: ["test"]
              take_image:
                type: boolean
                default: true
              setup_spectrograph:
                type: boolean
                default: true
              file_location:
                type: string
                default: "~/develop"
              script_type:
                type: string
                default: "narrowband"
            required: [wavelengths, integration_times, fiber_spectrograph_integration_times]
            additionalProperties: false
            """
        return yaml.safe_load(yaml_schema)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        wavelengths : `float` or `list` [`float`]
            Wavelength for each image (nm).
        integration_times :  : `float` or `list` [`float`]
            Integration time for each image (sec).
        mono_grating_types : `int` or `list` [`int`]
            Grating type for each image. The choices are:

            * 1: red
            * 2: blue
            * 3: mirror
        mono_entrance_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer entrance slit for each image (mm).
        mono_exit_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer exit slit for each image (mm).
        image_types : `str` or `list` [`str`]
            Type of each image.
        lamps : `str` or `list` [`str`]
            Name of lamp for each image.
        fiber_spectrometer_delays : `float` or `list` [`float`]
            Delay before taking each image (sec).

        Raises
        ------
        salobj.ExpectedError :
            If the lengths of all arguments that are sequences do not match.

        Notes
        -----
        Arguments can be scalars or sequences. All sequences must have the
        same length, which is the number of images taken. If no argument
        is a sequence then one image is taken.
        """
        self.log.setLevel(10)
        self.log.info("Configure started")

        nelt = 1
        for argname in (
            "wavelengths",
            "integration_times",
            "mono_grating_types",
            "mono_entrance_slit_widths",
            "mono_exit_slit_widths",
            "image_types",
            "lamps",
            "fiber_spectrometer_delays",
            "latiss_filter",
            "latiss_grating",
            "latiss_stage_pos",
            "nimages_per_wavelength",
            "shutter",
            "image_sequence_name",
            "fiber_spectrograph_integration_times",
        ):
            value = getattr(config, argname)
            if is_sequence(value):
                nelt = len(value)
                break
        self.file_location = os.path.expanduser(self.config.file_location)
        self.setup_spectrograph = self.config.setup_spectrograph
        self.take_image = self.config.take_image
        self.script_type = self.config.script_type
        # Monochromator Setup
        self.wavelengths = as_array(self.config.wavelengths, dtype=float, nelt=nelt)
        self.integration_times = as_array(
            self.config.integration_times, dtype=float, nelt=nelt
        )
        self.mono_grating_types = as_array(
            self.config.mono_grating_types, dtype=int, nelt=nelt
        )
        self.mono_entrance_slit_widths = as_array(
            self.config.mono_entrance_slit_widths, dtype=float, nelt=nelt
        )
        self.mono_exit_slit_widths = as_array(
            self.config.mono_exit_slit_widths, dtype=float, nelt=nelt
        )
        self.image_types = as_array(self.config.image_types, dtype=str, nelt=nelt)
        self.lamps = as_array(self.config.lamps, dtype=str, nelt=nelt)
        # Fiber spectrograph
        self.fiber_spectrometer_delays = as_array(
            self.config.fiber_spectrometer_delays, dtype=float, nelt=nelt
        )
        self.fiber_spectrograph_integration_times = as_array(
            self.config.fiber_spectrograph_integration_times, dtype=float, nelt=nelt
        )
        # ATSpectrograph Setup
        self.latiss_filter = as_array(self.config.latiss_filter, dtype=int, nelt=nelt)
        self.latiss_grating = as_array(self.config.latiss_grating, dtype=int, nelt=nelt)
        self.latiss_stage_pos = as_array(
            self.config.latiss_stage_pos, dtype=int, nelt=nelt
        )
        # ATCamera
        self.image_sequence_name = as_array(
            self.config.image_sequence_name, dtype=str, nelt=nelt
        )
        self.shutter = as_array(self.config.shutter, dtype=int, nelt=nelt)
        self.nimages_per_wavelength = as_array(
            self.config.nimages_per_wavelength, dtype=int, nelt=nelt
        )
        self.log.info("Configure completed")
        # note that the ATCamera exposure time
        # uses self.integration_times for this version

    def set_metadata(self, metadata):
        """Compute estimated duration.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """
        nimages = len(self.lamps)
        metadata.duration = self.change_grating_time * nimages + np.sum(
            (self.integration_times + 2) * self.nimages_per_wavelength
        )

    async def run(self):
        """Run script."""

        await self.checkpoint("start")

        path = pathlib.Path(f"{self.file_location}")
        csv_filename = (
            f"calsys_take_{self.script_type}_data_{datetime.date.today()}.csv"
        )
        file_exists = pathlib.Path(f"{path}/{csv_filename}").is_file()
        fieldnames = []
        if self.take_image:
            fieldnames.append("ATArchiver Image Name")
            fieldnames.append("ATArchiver Image Sequence Name")
        if self.setup_spectrograph:
            fieldnames.append("ATSpectrograph Filter")
            fieldnames.append("ATSpectrograph Grating")
            fieldnames.append("ATSpectrograph Linear Stage Position")
        fieldnames.append("Exposure Time")
        fieldnames.append("Fiber Spectrograph Exposure Time")
        fieldnames.append("Monochromator Grating")
        fieldnames.append("Monochromator Wavelength")
        fieldnames.append("Monochromator Entrance Slit Size")
        fieldnames.append("Monochromator Exit Slit Size")
        fieldnames.append("Fiber Spectrograph Fits File")
        fieldnames.append("Electrometer Fits File")

        with open(f"{path}/{csv_filename}", "a", newline="") as csvfile:
            data_writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                data_writer.writeheader()

            nelt = len(self.wavelengths)
            for i in range(nelt):
                self.log.info(f"take image {i} of {nelt}")

                await self.checkpoint("setup")

                self.monochromator.cmd_changeWavelength.set(
                    wavelength=self.wavelengths[i]
                )
                await self.monochromator.cmd_changeWavelength.start(
                    timeout=self.cmd_timeout
                )
                self.log.debug(
                    f"Changed monochromator wavelength to {self.wavelengths[i]}"
                )

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=ATMonochromator.Slit.FRONTEXIT,
                    slitWidth=self.mono_exit_slit_widths[i],
                )
                await self.monochromator.cmd_changeSlitWidth.start(
                    timeout=self.cmd_timeout
                )
                self.log.debug(
                    f"Changed monochromator exit slit width to {self.mono_exit_slit_widths[i]}"
                )

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=ATMonochromator.Slit.FRONTENTRANCE,
                    slitWidth=self.mono_entrance_slit_widths[i],
                )
                await self.monochromator.cmd_changeSlitWidth.start(
                    timeout=self.cmd_timeout
                )
                self.log.debug(
                    f"Changed monochromator entrance slit width to {self.mono_entrance_slit_widths[i]}"
                )

                self.monochromator.cmd_selectGrating.set(
                    gratingType=self.mono_grating_types[i]
                )
                await self.monochromator.cmd_selectGrating.start(
                    timeout=self.cmd_timeout + self.change_grating_time
                )
                self.log.debug(
                    f"Changed monochromator grating to {self.mono_grating_types[i]}"
                )

                # Setup ATSpectrograph
                if self.setup_spectrograph:
                    self.atspectrograph.cmd_changeDisperser.set(
                        disperser=self.latiss_grating[i]
                    )
                    try:
                        await self.atspectrograph.cmd_changeDisperser.start(
                            timeout=self.cmd_timeout
                        )
                    except salobj.AckError as e:
                        self.log.error(f"{e.ack.result}")

                    self.atspectrograph.cmd_changeFilter.set(
                        filter=self.latiss_filter[i]
                    )
                    await self.atspectrograph.cmd_changeFilter.start(
                        timeout=self.cmd_timeout
                    )

                    self.atspectrograph.cmd_moveLinearStage.set(
                        distanceFromHome=self.latiss_stage_pos[i]
                    )
                    await self.atspectrograph.cmd_moveLinearStage.start(
                        timeout=self.cmd_timeout
                    )

                # setup ATCamera
                # Because we take ancillary data at the same time as the image,
                # we can only take 1 image at a time.
                # Thus numImages is hardcoded to be 1.

                await self.checkpoint("expose")

                # The electrometer startScanDt command is not reported as done
                # until the scan is done, so start the scan and then start
                # taking the image data
                coro1 = self.start_electrometer_scan(i)
                coro2 = self.start_take_spectrum(i)
                if self.take_image:
                    coro3 = self.start_camera_take_image(i)
                if self.take_image:
                    results = await asyncio.gather(coro1, coro2, coro3)
                else:
                    results = await asyncio.gather(coro1, coro2)
                await self.checkpoint("Write data to csv file")
                electrometer_lfo_url = results[0].url
                fiber_spectrograph_lfo_url = results[1].url
                if self.take_image:
                    atcamera_ps_description = results[2].description
                    atcamera_image_name_list = atcamera_ps_description.split(" ")
                    atcamera_image_name = atcamera_image_name_list[1]
                self.log.debug("Writing csv file")
                row_dict = {}
                for fieldname in fieldnames:
                    row_dict[fieldname] = None
                row_dict["Exposure Time"] = self.integration_times[i]
                row_dict[
                    "Fiber Spectrograph Exposure Time"
                ] = self.fiber_spectrograph_integration_times[i]
                row_dict["Monochromator Grating"] = self.mono_grating_types[i]
                row_dict["Monochromator Wavelength"] = self.wavelengths[i]
                row_dict[
                    "Monochromator Entrance Slit Size"
                ] = self.mono_entrance_slit_widths[i]
                row_dict["Monochromator Exit Slit Size"] = self.mono_exit_slit_widths[i]
                row_dict["Fiber Spectrograph Fits File"] = fiber_spectrograph_lfo_url
                row_dict["Electrometer Fits File"] = electrometer_lfo_url
                if self.take_image:
                    row_dict["ATArchiver Image Name"] = atcamera_image_name
                    row_dict[
                        "ATArchiver Image Sequence Name"
                    ] = self.image_sequence_name[i]
                if self.setup_spectrograph:
                    row_dict["ATSpectrograph Filter"] = self.latiss_filter[i]
                    row_dict["ATSpectrograph Grating"] = self.latiss_grating[i]
                    row_dict[
                        "ATSpectrograph Linear Stage Position"
                    ] = self.latiss_stage_pos[i]
                data_writer.writerow(row_dict)
        with open(f"{path}/{csv_filename}", newline="") as csvfile:
            data_reader = csv.DictReader(csvfile)
            self.log.debug("Reading CSV file")
            for row in data_reader:
                fiber_spectrograph_url = row["Fiber Spectrograph Fits File"]
                electrometer_url = row["Electrometer Fits File"]
                electrometer_url += ".fits"
                electrometer_url = electrometer_url.replace(
                    "https://127.0.0.1", "http://10.0.100.133:8000"
                )
                self.log.debug("Fixed electrometer url")
                electrometer_url_name = electrometer_url.split("/")[-1]
                fiber_spectrograph_url_name = fiber_spectrograph_url.split("/")[-1]
                fiber_spectrograph_fits_request = requests.get(fiber_spectrograph_url)
                electrometer_fits_request = requests.get(electrometer_url)
                fiber_spectrograph_file = (
                    f"{self.file_location}/fiber_spectrograph_fits_files/"
                    f"{fiber_spectrograph_url_name}"
                )
                with open(fiber_spectrograph_file, "wb") as file:
                    file.write(fiber_spectrograph_fits_request.content)
                    self.log.debug("Download Fiber Spectrograph fits file")
                electrometer_file = f"{self.file_location}/electrometer_fits_files/{electrometer_url_name}"
                with open(electrometer_file, "wb") as file:
                    file.write(electrometer_fits_request.content)
                    self.log.debug("Downloaded Electrometer fits file")
            self.log.info("Fits Files downloaded")
        await self.checkpoint("Done")

    async def start_electrometer_scan(self, index):
        self.electrometer.cmd_startScanDt.set(
            scanDuration=self.integration_times[index]
            + self.fiber_spectrometer_delays[index] * 2
        )
        electrometer_lfo_coro = self.electrometer.evt_largeFileObjectAvailable.next(
            timeout=self.cmd_timeout, flush=True
        )
        await self.electrometer.cmd_startScanDt.start(timeout=self.cmd_timeout)
        self.log.debug("Electrometer finished scan")
        return await electrometer_lfo_coro

    async def start_take_spectrum(self, index):
        """Wait for `self.fiber_spectrometer_delays` then take
        a spectral image.

        Parameters
        ----------
        index : int
            Index of image to take.

        Returns
        -------
        cmd_captureSpectImage.start : coro
        """
        await self.electrometer.evt_detailedState.next(
            flush=True, timeout=self.cmd_timeout
        )
        await asyncio.sleep(self.fiber_spectrometer_delays[index])

        timeout = self.integration_times[index] + self.cmd_timeout
        fiber_spectrograph_lfo_coro = self.fiber_spectrograph.evt_largeFileObjectAvailable.next(
            timeout=self.cmd_timeout, flush=True
        )
        self.fiber_spectrograph.cmd_captureSpectImage.set(
            imageType=self.image_types[index],
            integrationTime=self.fiber_spectrograph_integration_times[index],
            lamp=self.lamps[index],
        )
        self.log.info(f"take a {self.integration_times[index]} second exposure")
        await self.fiber_spectrograph.cmd_captureSpectImage.start(timeout=timeout)
        self.log.debug("Fiber Spectrograph captured spectrum image")
        return await fiber_spectrograph_lfo_coro

    async def start_camera_take_image(self, index):
        self.atcamera.cmd_takeImages.set(
            shutter=self.shutter[index],
            numImages=1,
            expTime=self.integration_times[index],
            imageSequenceName=self.image_sequence_name[index],
        )
        atarchiver_lfo_coro = self.atarchiver.evt_processingStatus.next(
            flush=True, timeout=(self.cmd_timeout * 2) + self.integration_times[index]
        )
        await self.atcamera.cmd_takeImages.start(
            timeout=self.cmd_timeout + self.integration_times[index]
        )
        self.log.debug("Camera took image")
        return await atarchiver_lfo_coro
