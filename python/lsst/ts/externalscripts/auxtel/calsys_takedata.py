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

__all__ = ["CalSysTakeData"]

import asyncio
import collections
import pathlib
import datetime
import os
import csv
import requests

import numpy as np
import yaml

from lsst.ts import salobj
from lsst.ts.idl.enums import ATMonochromator


def is_sequence(value):
    """Return True if value is a sequence that is not a `str` or `bytes`.
    """
    if isinstance(value, str) or isinstance(value, bytes):
        return False
    return isinstance(value, collections.abc.Sequence)


def as_array(value, dtype, nelt):
    """Return a scalar or sequence as a 1-d array of specified type and length.

    Parameters
    ----------
    value : ``any`` or `list` [``any``]
        Value to convert to a list
    dtype : `type`
        Type of data for output
    nelt : `int`
        Required number of elements

    Returns
    -------
    array : `numpy.ndarray`
        ``value`` as a 1-dimensional array with the specified type and length.

    Raises
    ------
    ValueError
        If ``value`` is a sequence of the wrong length
    TypeError
        If ``value`` (if a scalar) or any of its elements (if a sequence)
        cannot be cast to ``dtype``.
    """
    if is_sequence(value):
        if len(value) != nelt:
            raise ValueError(f"len={len(value)} != {nelt}")
        return np.array(value, dtype=dtype)
    return np.array([value] * nelt, dtype=dtype)


class CalSysTakeData(salobj.BaseScript):
    """
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Configure and take data from the auxiliary telescope CalSystem.",
        )
        self.cmd_timeout = 10
        self.change_grating_time = 60
        self.electrometer = salobj.Remote(
            domain=self.domain, name="Electrometer", index=1
        )
        self.monochromator = salobj.Remote(domain=self.domain, name="ATMonochromator")
        self.fiber_spectrograph = salobj.Remote(
            domain=self.domain, name="FiberSpectrograph"
        )

    @classmethod
    def get_schema(cls):
        yaml_schema = """
            $schema: http://json-schema/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/CalSysTakeData.yaml
            title: CalSysTakeData v1
            description: Configuration for CalSysTakeData.
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
              grating_types:
                type: integer
                minimum: 1
                maximum: 3
                default: [1]
              entrance_slit_widths:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [2]
              exit_slit_widths:
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
                default: ["test"]
              lamps:
                type: array
                items:
                  type: string
                  minItems: 1
                default: ["lamps"]
              spectrometer_delays:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [1]
              fiber_spectrograph_times:
                type: array
                items:
                  type: number
                  minItems: 1
                default: [1]
              file_location:
                type: string
                default: "~/develop/calsys_take_data_fits_files"
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
        grating_types : `int` or `list` [`int`]
            Grating type for each image. The choices are:

            * 1: red
            * 2: blue
            * 3: mirror
        entrance_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer entrance slit for each image (mm).
        exit_slit_widths : `float` or `list` [`float`]
            Width of the monochrometer exit slit for each image (mm).
        image_types : `str` or `list` [`str`]
            Type of each image.
        lamps : `str` or `list` [`str`]
            Name of lamp for each image.
        spectrometer_delays : `float` or `list` [`float`]
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
        self.log.info("Configure started")

        nelt = 1
        kwargs = locals()
        for argname in (
            "wavelengths",
            "integration_times",
            "grating_types",
            "entrance_slit_widths",
            "exit_slit_widths",
            "image_types",
            "lamps",
            "spectrometer_delays",
        ):
            value = kwargs[argname]
            if is_sequence(value):
                nelt = len(value)
                break

        self.wavelengths = as_array(self.config.wavelengths, dtype=float, nelt=nelt)
        self.integration_times = as_array(
            self.config.integration_times, dtype=float, nelt=nelt
        )
        self.grating_types = as_array(self.config.grating_types, dtype=int, nelt=nelt)
        self.entrance_slit_widths = as_array(
            self.config.entrance_slit_widths, dtype=float, nelt=nelt
        )
        self.exit_slit_widths = as_array(
            self.config.exit_slit_widths, dtype=float, nelt=nelt
        )
        self.image_types = as_array(self.config.image_types, dtype=str, nelt=nelt)
        self.fiber_spectrograph_integration_times = as_array(
            self.config.fiber_spectrograph_integration_times, dtype=float, nelt=nelt
        )
        self.lamps = as_array(self.config.lamps, dtype=str, nelt=nelt)
        self.spectrometer_delays = as_array(
            self.config.spectrometer_delays, dtype=float, nelt=nelt
        )
        self.file_location = os.path.expanduser(self.config.file_location)

        self.log.info("Configure completed")

    def set_metadata(self, metadata):
        """Compute estimated duration.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """
        nimages = len(self.lamps)
        metadata.duration = self.change_grating_time * nimages + np.sum(
            self.integration_times
        )

    async def run(self):
        """Run script."""

        await self.checkpoint("start")

        csvdir = pathlib.Path(f"{self.file_location}")
        csvpath = csvdir / f"calsys_take_data_{datetime.date.today()}.csv"
        file_exists = csvpath.is_file()

        with open(csvpath, "a", newline="") as csvfile:
            fieldnames = [
                "Exposure Time",
                "Monochromator Grating",
                "Monochromator Wavelength",
                "Monochromator Entrance Slit Size",
                "Monochromator Exit Slit Size",
                "Fiber Spectrograph Fits File",
                "Electrometer Fits File",
            ]
            data_writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if not file_exists:
                data_writer.writeheader()

            nelt = len(self.wavelengths)
            for i in range(nelt):
                self.log.info(
                    f"collecting electrometer and fiber_spectrograph scan {i} of {nelt}"
                )

                await self.checkpoint("setup")

                self.monochromator.cmd_changeWavelength.set(
                    wavelength=self.wavelengths[i]
                )
                await self.monochromator.cmd_changeWavelength.start(
                    timeout=self.cmd_timeout
                )

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=ATMonochromator.Slit.FRONTEXIT,
                    slitWidth=self.exit_slit_widths[i],
                )
                await self.monochromator.cmd_changeSlitWidth.start(
                    timeout=self.cmd_timeout
                )

                self.monochromator.cmd_changeSlitWidth.set(
                    slit=ATMonochromator.Slit.FRONTENTRANCE,
                    slitWidth=self.entrance_slit_widths[i],
                )
                await self.monochromator.cmd_changeSlitWidth.start(
                    timeout=self.cmd_timeout
                )

                self.monochromator.cmd_selectGrating.set(
                    gratingType=self.grating_types[i]
                )
                await self.monochromator.cmd_selectGrating.start(
                    timeout=self.cmd_timeout + self.change_grating_time
                )

                await self.checkpoint("expose")

                # The electrometer startScanDt command is not reported as done
                # until the scan is done, so start the scan and then start
                # taking the image data
                coro1 = self.start_electrometer_scan(i)
                coro2 = self.start_take_spectrum(i)
                results = await asyncio.gather(coro1, coro2)
                await self.checkpoint("Write data to csv file")
                electrometer_lfo_url = results[0].url
                fiber_spectrograph_lfo_url = results[1].url
                self.log.debug("Writing csv file")
                data_writer.writerow(
                    {
                        fieldnames[0]: self.integration_times[i],
                        fieldnames[1]: self.grating_types[i],
                        fieldnames[2]: self.wavelengths[i],
                        fieldnames[3]: self.entrance_slit_widths[i],
                        fieldnames[4]: self.exit_slit_widths[i],
                        fieldnames[5]: fiber_spectrograph_lfo_url,
                        fieldnames[6]: electrometer_lfo_url,
                    }
                )
        with open(csvpath, newline="") as csvfile:
            data_reader = csv.DictReader(csvfile)
            self.log.debug("Reading CSV file")

            for row in data_reader:
                fiber_spectrograph_url = row["Fiber Spectrograph Fits File"]
                electrometer_url = row["Electrometer Fits File"]
                electrometer_url += ".fits"
                electrometer_url = electrometer_url.replace(
                    "https://127.0.0.1", "http://10.0.100.133:8000"
                )
                electrometer_url_name = electrometer_url.split("/")[-1]
                fiber_spectrograph_url_name = fiber_spectrograph_url.split("/")[-1]
                fiber_spectrograph_fits_request = requests.get(fiber_spectrograph_url)
                electrometer_fits_request = requests.get(electrometer_url)
                fiber_spectrograph_fits_path = (
                    self.file_location
                    / "fiber_spectrograph_fits_files"
                    / fiber_spectrograph_url_name
                )
                with open(fiber_spectrograph_fits_path, "wb") as file:
                    file.write(fiber_spectrograph_fits_request.content)
                    self.log.debug(
                        f"Wrote Fiber Spectrograph fits file to {fiber_spectrograph_fits_path}"
                    )
                electrometer_fits_path = (
                    self.file_location
                    / "electrometer_fits_files"
                    / electrometer_url_name
                )
                with open(electrometer_fits_path, "wb") as file:
                    file.write(electrometer_fits_request.content)
                    self.log.debug(
                        f"Wrote Electrometer fits file to {electrometer_fits_path}"
                    )
            self.log.info("Fits Files downloaded")
        await self.checkpoint("Done")

    async def start_take_spectrum(self, index):
        """Wait for `self.spectrometer_delays` then take a spectral image.

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
        await asyncio.sleep(self.spectrometer_delays[index])

        timeout = self.integration_times[index] + self.cmd_timeout
        fiber_spectrograph_lfo_coro = self.fiber_spectrograph.evt_largeFileObjectAvailable.next(
            timeout=self.cmd_timeout, flush=True
        )
        self.fiber_spectrograph.cmd_captureSpectImage.set(
            imageType=self.image_types[index],
            integrationTime=self.integration_times[index],
            lamp=self.lamps[index],
        )
        self.log.info(f"take a {self.integration_times[index]} second exposure")
        await self.fiber_spectrograph.cmd_captureSpectImage.start(timeout=timeout)
        return await fiber_spectrograph_lfo_coro

    async def start_electrometer_scan(self, index):
        self.electrometer.cmd_startScanDt.set(
            scanDuration=self.integration_times[index]
            + self.spectrometer_delays[index] * 2
        )
        electrometer_lfo_coro = self.electrometer.evt_largeFileObjectAvailable.next(
            timeout=self.cmd_timeout, flush=True
        )
        await self.electrometer.cmd_startScanDt.start(timeout=self.cmd_timeout)
        self.log.debug("Electrometer finished scan")
        return await electrometer_lfo_coro
