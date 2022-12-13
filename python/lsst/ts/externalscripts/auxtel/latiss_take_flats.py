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

__all__ = [
    "LatissTakeFlats",
]

import asyncio

# import pathlib
import io
import json
import yaml

from lsst.ts import salobj, utils

# from lsst.ts.idl import enums
from lsst.ts.observatory.control.auxtel import LATISS, LATISSUsages
from lsst.ts.salobj import BaseScript


class LatissTakeFlats(BaseScript):
    """Take LATISS flats with the AuxTel calibration Ilumination System

    This SAL Script is being designed to take flat fields.
    It will also be used to take the datasets required to determine the
    proper way to determine instrument setup.
    """

    def __init__(
        self, index: int, remotes: bool = True, simulation_mode: int = 0
    ) -> None:

        # valid_simulation_modes = (0, 1)

        super().__init__(
            index=index,
            descr="Take LATISS flats with the calibration Illumination System",
        )

        if remotes:
            self.latiss = LATISS(domain=self.domain, log=self.log)
            self.electrometer = salobj.Remote(
                domain=self.domain, name="Electrometer", index=201
            )
            self.atmonochromator = salobj.Remote(
                domain=self.domain, name="ATMonochromator"
            )
            self.fiberspectrograph = salobj.Remote(
                domain=self.domain, name="FiberSpectrograph", index=3
            )
        else:
            self.latiss = LATISS(
                domain=self.domain, log=self.log, intended_usage=LATISSUsages.DryTest
            )

        self.config = None
        self.step = None
        self.sequence = None
        self.sequence_summary = None
        self.bucket = None
        self.s3instance = None
        self.simulation_mode = simulation_mode
        # self.filename = None

        self.image_in_oods_timeout = 15.0
        self.get_image_timeout = 10.0

    async def run(self, simulation_mode: int = 0):

        await self.arun(checkpoint_active=True, simulation_mode=simulation_mode)

    @classmethod
    def get_schema(cls):
        yaml_schema = """
$schema: http://json-schema/draft-07/schema#
$id: https://github.com/lsst-ts/ts_externalscripts/auxtel/LatissTakeFlats.yaml
title: LatissTakeFlats v1
description: Configuration for LatissTakeFlats.
type: object
properties:
    latiss_filter:
        type: string
        default: 'empty_1'
    latiss_grating:
        type: string
        default: 'empty_1'
    sequences:
        type: string
    s3instance:
        type: string
        default: 'cp'

required: [latiss_filter, latiss_grating]
additionalProperties: false
            """
        return yaml.safe_load(yaml_schema)

    def set_metadata(self, metadata):

        self.log.debug("In set_metadata")
        metadata.nimages = 3
        metadata.duration = 600  # set arbitrarily

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.log.debug(f"Configuration: {config}")

        self.config = config
        self.s3instance = config.s3instance
        self.sequence = config.sequences
        

    async def handle_checkpoint(self, checkpoint_active, checkpoint_message):

        if checkpoint_active:
            await self.checkpoint(checkpoint_message)
        else:
            self.log.info(checkpoint_message)

    def get_flat_sequence(self, latiss_filter: str, latiss_grating: str):
        """Return the pre-determined flat field sequences for a given
        LATISS filter and grating.

               Parameters:
               -----------

               filt : `string`
                   LATISS filter.

               grating : `string`
                   LATISS grating.

               Returns
               -------

               sequence : `list`
                   A list of sequences (dicts) for a given LATISS filter
                  and grating combination.

        """
        self.log.debug(
            f"Running get_flat_sequence with {latiss_filter=} and {latiss_grating=}"
        )

        # Check that the LATISS filter/grating combination is valid
        if latiss_filter == "SDSSr_65mm" and latiss_grating == "empty_1":
            # Returns a dictionary of sequences
            step1 = {
                "wavelength": 580,
                "grating": 1,  # enums.ATMonochromator.Grating.RED,  --> Enums are wrong!
                "spec_res": 7,
                "exit_slit_width": 4.5,
                "entrance_slit_width": 4.5,
                "exp_time": 3,
                "n_exp": 3,
                "fs_exp_time": 1,
                "fs_n_exp": 1,
                "em_exp_time": 5,
                "em_n_exp": 1,
            }
            step2 = {
                "wavelength": 620,
                "grating": 1,  # enums.ATMonochromator.Grating.RED,
                "spec_res": 8,
                "exit_slit_width": 4.5,
                "entrance_slit_width": 4.5,
                "exp_time": 4,
                "n_exp": 3,
                "fs_exp_time": 1,
                "fs_n_exp": 1,
                "em_exp_time": 5,
                "em_n_exp": 1,
            }

            sequence = [step1, step2]  # , step3]
        else:
            raise RuntimeError(
                f"The combination of {latiss_filter} and grating {latiss_grating} "
                "do not have an established flat sequence. Exiting."
            )

        return sequence

    def get_atmonochromator_setup(self, wavelength: float, spec_res: float):
        """Derive the atmonochromator based on the desired wavelength and
        spectral resolution.
        Slit width values, grating, and relative throughput with
        respect to 700 nm is returned.

        Parameters
        ----------
        config : `float`
            Wavelength in nanometers

        Returns:
        --------

        exit_slit_width : `float`
            Width of exit slit in mm

        entrance_slit_width : `float`
             Width of entrance slit width in mm

        attenuation : `float`
            Relative throughput with respect to 700 nm and R=10nm

        """

        return NotImplementedError

    async def setup_atmonochromator_axes(
        self,
        wavelength: float,
        grating: str,
        entrance_slit_width: float,
        exit_slit_width: float,
    ):
        """Setup the atmonochromator based on the desired wavelength and
        spectral resolution.

        Parameters
        ----------
        config : `float`
            Wavelength in nanometers


        """

        # this method will go in an atcalsys class?

        # Can be made asynchronous later once more robust
        await self.atmonochromator.cmd_selectGrating.set_start(
            gratingType=int(grating), timeout=180
        )
        await self.atmonochromator.cmd_changeWavelength.set_start(wavelength=wavelength)
        await self.atmonochromator.cmd_changeSlitWidth.set_start(
            slit=1, slitWidth=entrance_slit_width
        )
        await self.atmonochromator.cmd_changeSlitWidth.set_start(
            slit=2, slitWidth=exit_slit_width
        )

    async def setup_electrometer(self):
        """Makes sure electrometer is configured correctly"""

        # Need to set mode and integration time etc, using defaults for now.
        await self.electrometer.cmd_performZeroCalib.set_start(timeout=10)
        await self.electrometer.cmd_setDigitalFilter.set_start(
            activateFilter=False,
            activateAvgFilter=False,
            activateMedFilter=False,
            timeout=10,
        )

    async def take_fs_exposures(self, exp_time, n):
        """Takes exposures with the fiber spectrograph

        Parameters
        ----------

        exp_time : `float`
            Exposure time in seconds

        n : `int`
            Number of exposures

        Returns
        -------

        lfa_urls : `list`
            List of LF urls

        """
        self.log.debug("Starting FS exposures")
        lfa_urls = []
        for i in range(n):
            self.fiberspectrograph.evt_largeFileObjectAvailable.flush()
            await self.fiberspectrograph.cmd_expose.set_start(
                duration=exp_time, numExposures=1
            )
            lfa_obj = await self.fiberspectrograph.evt_largeFileObjectAvailable.next(
                flush=False, timeout=10
            )
            lfa_urls.append(lfa_obj.url)

        return lfa_urls

    async def take_em_exposures(self, exp_time: float, n: int):
        """Takes exposure with the electrometer

        The readout time must be included in determining the number
        of exposures. Using n=1 is recommended when possible.

        Parameters
        ----------

        exp_time : `float`
            Exposure time in seconds

        n : `int`
            Number of exposures

        Returns
        -------

        lfa_urls : `list`
            List of LFA objects to get files in the LFA

        """
        self.log.debug("Starting Electrometer exposures")
        lfa_urls = []
        for i in range(n):
            await self.electrometer.cmd_startScanDt.set_start(scanDuration=exp_time)
            lfa_obj = await self.electrometer.evt_largeFileObjectAvailable.next(
                flush=False, timeout=30
            )
            lfa_urls.append(lfa_obj.url)

        return lfa_urls

        # @property
        # def estimated_atmonochromator_setup_time(self):
        #     """The estimated time to setup the atmonochromator
        #     """
        #     return 50

    async def prepare_summary_table(self):
        """Prepares final summary table.
        Checks writing is possible and that s3 bucket can be made
        """

        # file_output_dir = "/tmp/LatissTakeFlats/"
        # write folder if required
        # pathlib.Path().mkdir(parents=True, exist_ok=True)
        # self.filename =
        # f"LatissTakeFlats_sequence_summary_{self.group_id}.json"

        # Take a copy as the starting point for the summary
        self.sequence_summary = {}

        # Add metadata from this script
        date_begin = utils.astropy_time_from_tai_unix(utils.current_tai()).isot
        self.sequence_summary["date_begin_tai"] = date_begin
        self.sequence_summary["script_index"] = self.salinfo.index
        # Create and empty list for the steps
        self.sequence_summary["steps"] = []

        # Check to see if in simulations mode, if so provide a mock.
        if self.bucket is None:
            self.bucket = salobj.AsyncS3Bucket(
                salobj.AsyncS3Bucket.make_bucket_name(s3instance=self.s3instance),
                create=True,
                domock=self.simulation_mode != 0,
            )

        # Generate a bucket key
        self.s3_key_name = self.bucket.make_key(
            salname="LatissTakeFlats",
            salindexname=self.salinfo.index,
            generator="json",
            date=date_begin,
            suffix=".json",
        )

    async def arun(self, checkpoint_active=False, simulation_mode: bool = 0):

        await self.handle_checkpoint(
            checkpoint_active=checkpoint_active,
            checkpoint_message="Setting up LATISS",
        )

        await self._setup_latiss()

        # setup electrometer
        await self.setup_electrometer()

        # Get sequences for the given setup if not defined explicitly
        if self.sequence is None:
            self.sequence = self.get_flat_sequence(
                self.config.latiss_filter, self.config.latiss_grating
            )

        # Prepare summary table for writing
        await self.prepare_summary_table()

        for i, self.step in enumerate(self.sequence):

            await self.handle_checkpoint(
                checkpoint_active=checkpoint_active,
                checkpoint_message=f"Setting up atmonochromator for sequence {i+1} of {len(self.sequence)}.",
            )

            # will be replaced by setup_atmonochromator in the future?
            await self.setup_atmonochromator_axes(
                self.step["wavelength"],
                self.step["grating"],
                self.step["exit_slit_width"],
                self.step["entrance_slit_width"],
            )

            await self.handle_checkpoint(
                checkpoint_active=checkpoint_active,
                checkpoint_message=f"Performing exposure {i+1} of {self.step['n_exp']}.",
            )

            for n in range(self.step["n_exp"]):
                task1 = asyncio.create_task(
                    self.latiss.take_flats(
                        self.step["exp_time"],
                        nflats=1,
                        group_id=self.group_id,
                        program="AT_flats",
                        # reason=f"flats_{self.config.latiss_filter}_{self.config.latiss_grating}",
                        # note=f"sequence_lfa_key={self.s3_key_name}",
                    )
                )

                task2 = asyncio.create_task(
                    self.take_fs_exposures(
                        self.step["fs_exp_time"], self.step["fs_n_exp"]
                    )
                )

                task3 = asyncio.create_task(
                    self.take_em_exposures(
                        self.step["em_exp_time"], self.step["fs_n_exp"]
                    )
                )

                # Placeholders for fiberspectrograph and electrometer
                # task2 = asyncio.sleep(1)
                # task3 = asyncio.sleep(2)

                latiss_results, fs_results, em_results = await asyncio.gather(
                    task1, task2, task3
                )
                self.step["electrometer_lfa_urls"] = em_results
                self.step["fiberspectrograph_lfa_urls"] = fs_results
                self.step["latiss_ids"] = latiss_results

                # Add info to the sequence summary
                (self.sequence_summary["steps"]).append(self.step)

                # Augment sequence dictionary
            await self.handle_checkpoint(
                checkpoint_active=checkpoint_active,
                checkpoint_message="Writing script summary to LFA.",
            )

            # write the final result to the LFA
            date_end = utils.astropy_time_from_tai_unix(utils.current_tai()).isot
            self.sequence_summary["date_end_tai"] = date_end

            await self.publish_sequence_summary()

            self.log.info("LatissTakeFlats complete")

    async def _setup_latiss(self):
        """Setup latiss.

        Set filter and grating to empty_1.
        """
        await self.latiss.setup_instrument(
            filter=self.config.latiss_filter,
            grating=self.config.latiss_grating,
        )

    async def publish_sequence_summary(self):
        """Write sequence summary to LFA as a json file"""

        # try:

        #     with open(self.filename, "w") as fp:
        #         json.dump(self.sequence_summary, fp)
        #     self.log.info(f"Sequence Summary file
        # written: {self.filename}\n")
        # except Exception as e:
        #     msg = f"Writing sequence summary file to local
        #  disk failed: {repr(e)}"
        #     self.log.error(msg)
        #     raise RuntimeError(msg)

        try:
            file_object = io.BytesIO()
            file_object.write(json.dumps(self.sequence_summary).encode())
            file_object.seek(
                0
            )  # brings the cursor back to the top of the file for the data stream

            await self.bucket.upload(fileobj=file_object, key=self.s3_key_name)

            url = (
                f"{self.bucket.service_resource.meta.client.meta.endpoint_url}/"
                f"{self.bucket.name}/{self.s3_key_name}"
            )

            await self.evt_largeFileObjectAvailable.set_write(
                url=url, generator=f"{self.salinfo.name}:{self.salinfo.index}"
            )
        except Exception as e:
            msg = f"File upload to s3 bucket failed: {e}"
            self.log.exception(msg)
            raise RuntimeError(msg)