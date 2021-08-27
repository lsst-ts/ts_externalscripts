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

__all__ = ["BaseMakeCalibrations"]

import yaml
import abc
import json
import asyncio
import collections

from lsst.ts import salobj
from lsst.ts.observatory.control import RemoteGroup


class BaseMakeCalibrations(salobj.BaseScript, metaclass=abc.ABCMeta):
    """ Base class for taking images, and constructing, verifying, and
        certifying master calibrations.

    Parameters
    ----------
    index : `int`
        SAL index of this script
    """
    def __init__(self, index, descr):
        super().__init__(index=index, descr=descr)
        # cpCombine + ISR per image with -j 1 at the summit [sec]
        # See DM-30483
        # 45 sec: Bias.
        self.estimated_process_time = 45*3
        # Define the OCPS Remote Group (base class) to be able to check
        # that the OCPS is enabled in `arun` before running the script.
        self.ocps_group = RemoteGroup(domain=self.domain, components=["OCPS"], log=self.log)

        # Callback so that the archiver queue does not overflow.
        self.image_in_oods_received_all_expected = asyncio.Event()
        self.image_in_oods_received_all_expected.clear()

        self.number_of_images_expected = None
        self.number_of_images_taken = 0
        self.image_in_oods_samples = dict(BIAS=[], DARK=[], FLAT=[])

        self.number_total_images = None

        self.current_image_type = None

    @property
    def ocps(self):
        self.ocps_group.remp.ocps

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_configuration(self):
        """Get instrument configuration

        Returns
        -------
        instrument_configuration: `dict`
            Dictionary with instrument configuration.
        """
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def instrument_name(self):
        """String with instrument name for pipeline task"""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def image_in_oods(self):
        """Archiver"""
        raise NotImplementedError()

    @classmethod
    def get_schema(cls):
        schema = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/blob/master/python/lsst/ts/\
            externalscripts/maintel/make_comcam_calibrations.py
        title: BaseMakeCalibrations v1
        description: Configuration for BaseMakeCalibrations.
        type: object
        properties:
            script_mode:
                description: Type of images to make. If "BIAS", only biases will be taken \
                        and a master bias produced, verified, and certified. If "BIAS_AND_DARK", \
                        the process will include bias and dark images. Note that a bias is needed \
                        to produce a dark. If "ALL" (default), biases, darks, and flats will be
                        produced.
                type: string
                enum: ["BIAS", "BIAS_AND_DARK", "ALL"]
                default: "ALL"
            n_bias:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 1
                description: Number of biases to take.
            n_dark:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 1
                description: Number of darks to take.
            exp_times_dark:
                description: The exposure time of each dark image (sec). If a single value,
                  then the same exposure time is used for each exposure.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: number
                      minimum: 0
                  - type: number
                    minimum: 0
                default: 0
            n_flat:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 1
                description: Number of flats to take.
            exp_times_flat:
                description: The exposure time of each flat image (sec). If a single value,
                  then the same exposure time is used for each exposure.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: number
                      minimum: 0
                  - type: number
                    minimum: 0
                default: 0
            detectors:
                type: string
                default: "(0)"
                descriptor: Detector IDs.
            config_options_bias:
                type: string
                descriptor: Options to be passed to the command-line bias pipetask. They will overwrite \
                    the values in cpBias.yaml.
                default: "-c isr:doDefect=False -c isr:doLinearize=False -c isr:doCrosstalk=False \
                          -c isr:overscan.fitType='MEDIAN_PER_ROW'"
            config_options_dark:
                type: string
                descriptor: Options to be passed to the command-line dark pipetask. They will overwrite \
                    the values in cpDark.yaml.
                default: "-c isr:doDefect=False -c isr:doLinearize=False -c isr:doCrosstalk=False"
            config_options_flat:
                type: string
                descriptor: Options to be passed to the command-line flat pipetask. They will overwrite \
                    the values in cpFlat.yaml.
                default: "-c isr:doDefect=False -c isr:doLinearize=False -c isr:doCrosstalk=False \
                          -c cpFlatMeasure:doVignette=False "
            n_processes:
                type: integer
                default: 8
                descriptor: Number of processes that the pipetasks will use.
            certify_calib_begin_date:
                type: string
                default: "1950-01-01"
                descriptor: ISO-8601 datetime (TAI) of the beginning of the \
                    validity range for the certified calibrations.
            certify_calib_end_date:
                type: string
                default: "2050-01-01"
                descriptor: ISO-8601 datetime (TAI) of the end of the \
                    validity range for the certified calibrations.
            max_counter_archiver_check:
                type: integer
                default: 1000
                descriptor: Maximum number of loops to wait for confirmation that \
                    images taken were archived and available to butler.
            oods_timeout:
                type: integer
                default: 60
                descriptor: Timeout value, in seconds, for OODS.
        additionalProperties: false
        """
        return yaml.safe_load(schema)

    async def set_exp_times_per_im_type(self, image_type):
        """Define exp_times and n_images according to image type.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].
        """

        if image_type == "BIAS":
            n_images = self.config.n_bias
            exp_times = 0.
        elif image_type == "DARK":
            n_images = self.config.n_dark
            exp_times = self.config.exp_times_dark
        else:
            n_images = self.config.n_flat
            exp_times = self.config.exp_times_flat

        if isinstance(exp_times, collections.abc.Iterable):
            if n_images is not None:
                if len(exp_times) != n_images:
                    raise ValueError(
                        "n_images_" + f"{image_type}".lower() + f"={n_images} specified and "
                        "exp_times_" + f"{image_type}".lower() + f"={exp_times} is an array, "
                        f"but the length does not match the number of images."
                    )
        else:
            # exp_times is a scalar; if n_images is specified then
            # take that many images, else take 1 image
            if n_images is None:
                n_images = 1
            exp_times = [exp_times] * n_images

        return exp_times

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        # Log information about the configuration

        self.log.debug(
            f"n_bias: {config.n_bias}, detectors: {config.detectors}, "
            f"n_dark: {config.n_dark}, "
            f"n_flat: {config.n_flat}, "
            f"instrument: {self.instrument_name} "
        )

        self.config = config

    def set_metadata(self, metadata):
        """Set estimated duration of the script.
        """
        metadata.duration = self.config.n_bias*(self.camera.read_out_time + self.estimated_process_time)

    async def take_image_type(self, image_type, exp_times):
        """Take exposures and build exposure set.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        exp_times: `list`
            List of exposure times.

        Returns
        -------
            Tuple with exposure IDs.
        """

        return tuple(
            [
                await self.camera.take_imgtype(image_type, exp_time, 1)
                for exp_time in exp_times
            ]
        )

    async def image_in_oods_callback(self, data):
        """Callback function to check images are in archiver"""
        self.image_in_oods_samples[self.current_image_type].append(data)
        self.number_of_images_taken += 1
        if self.number_of_images_taken == self.number_of_images_expected:
            self.image_in_oods_received_all_expected.set()

    async def take_images(self, image_type):
        """Take images with instrument.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        Returns
        -------
        exposures : `tuple`
             Tuple with the IDs of the exposures taken.
        """

        exp_times = await self.set_exp_times_per_im_type(image_type)

        self.image_in_oods.flush()

        n_detectors = len(tuple(map(int, self.config.detectors[1:-1].split(','))))

        self.number_of_images_expected = len(exp_times)*n_detectors
        self.number_of_images_taken = 0
        self.image_in_oods_received_all_expected.clear()
        self.current_image_type = image_type

        # callback
        self.image_in_oods.callback = self.image_in_oods_callback

        exposures = await self.take_image_type(image_type, exp_times)

        await asyncio.wait_for(self.image_in_oods_received_all_expected, timeout=self.config.oods_timeout)

        self.ocps.evt_job_result.flush()

        return exposures

    async def call_pipetask(self, image_type, exposure_ids):
        """Call pipetasks via the OCPS.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        exposure_ids: `tuple` [`int`]
            Tuple with exposure IDs.

        Returns
        -------
        response : `dict`
             Dictionary with the final OCPS status.
        """

        # Run the pipetask via the OCPS
        if image_type == "BIAS":
            pipe_yaml = "cpBias.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_bias} "
                             "--register-dataset-types  "
                             f"{self.config.config_options_bias}")
        elif image_type == "DARK":
            pipe_yaml = "cpDark.yaml"
            # Add calib collection to input collections with bias
            # from bias step.
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_dark} "
                             f"-i {self.config.calib_collection} "
                             "--register-dataset-types "
                             f"{self.config.config_options_dark}")
        else:
            pipe_yaml = "cpFlat.yaml"
            # Add calib collection to input collections with bias,
            # and dark from bias and dark steps.
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_flat} "
                             f"-i {self.config.calib_collection}"
                             "--register-dataset-types "
                             f"{self.config.config_options_flat}")

        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False, pipeline="${CP_PIPE_DIR}/pipelines/"+f"{pipe_yaml}", version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
                       f" detector IN {self.config.detectors} AND exposure IN {exposure_ids}"
        )
        if ack.ack != salobj.SalRetCode.CMD_ACK:
            ack.print_vars()

        # Wait for the in-progress acknowledgement with the job identifier.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack, wait_done=False)
        self.log.debug(f'Received acknowledgement of ocps command for making {image_type}')

        ack.print_vars()
        job_id = json.loads(ack.result)["job_id"]

        # Wait for the command completion acknowledgement.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(f'Received command completion acknowledgement from ocps for {image_type}')
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            ack.print_vars()
        # Wait for the job result message that matches the job id we're
        # interested in ignoring any others (from other remotes).
        # This obviously needs to follow the first acknowledgement
        # (that returns the, job id) but might as well wait for the second.
        while True:
            msg = await self.ocps.evt_job_result.next(flush=False, timeout=self.config.oods_timeout)
            response = json.loads(msg.result)
            if response["jobId"] == job_id:
                break

        self.log.info(f"Final status ({image_type}): {response}")

        return response

    async def verify_calib(self, image_type, job_id_calib, exposures):
        """Verify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        jod_id_calib : `str`
            Job ID returned by OCPS during previous pipetask call.

        Notes
        -----
        The verification step runs tests in `cp_verify`
        that check the metrics in DMTN-101.
        """
        if image_type == "BIAS":
            pipe_yaml = "VerifyBias.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_verify_bias} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types ")
        elif image_type == "DARK":
            pipe_yaml = "VerifyDark.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_verify_dark} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types ")
        else:
            pipe_yaml = "VerifyFlat.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_verify_flat} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types ")

        # Verify the master calibration
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False, pipeline="${CP_VERIFY_DIR}/pipelines/" + f"{pipe_yaml}", version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
                       f" detector IN {self.config.detectors} AND exposure IN {exposures}"
        )

        if ack.ack != salobj.SalRetCode.CMD_ACK:
            ack.print_vars()

        ack = await self.ocps.cmd_execute.next_ackcmd(ack, wait_done=False)
        self.log.debug('Received acknowledgement of ocps command for bias verification.')

        ack.print_vars()
        job_id_verify = json.loads(ack.result)["job_id"]

        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(f"Received command completion acknowledgement from ocps ({image_type})")
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            ack.print_vars()

        while True:
            msg = await self.ocps.evt_job_result.next(flush=False, timeout=self.config.oods_timeout)
            response = json.loads(msg.result)
            if response["jobId"] == job_id_verify:
                break

        self.log.info(f"Final status from {image_type} verification: {response}")

        return response

    async def certify_calib(self, image_type, job_id_verify):
        """Certify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        jod_id_verify : `str`
            Job ID returned by OCPS during previous verification
            pipetask call.

        Notes
        -----
        The calibration will certified for use with a timespan that indicates
        its vailidy range.
        """
        # Certify the calibration, if the verification job
        # completed successfully
        self.log.info(f"Certifying {image_type} ")
        REPO = self.config.repo
        # This is the output collection from the verification step
        CALIB_PRODUCT_COL = f"u/ocps/{job_id_verify}"
        CALIB_COL = self.config.calib_collection
        cmd = (f"butler certify-calibrations {REPO} {CALIB_PRODUCT_COL} {CALIB_COL} "
               f"--begin-date {self.config.certify_calib_begin_date} "
               f"--end-date {self.config.certify_calib_end_date}" + f" {image_type}".lower())
        self.log.info(cmd)

        process = await asyncio.create_subprocess_shell(cmd)
        stdout, stderr = await process.communicate()
        self.log.debug(f"Process returned: {process.returncode}")
        if process.returncode != 0:
            self.log.debug(stdout)
            self.log.error(stderr)
            raise RuntimeError(f"Error running command for certifying {image_type}.")

    async def arun(self, checkpoint=False):

        # Check that the camera is enabled
        await self.camera.assert_all_enabled("All camera components need to be enabled to run this script.")

        # Check that the OCPS is enabled
        await self.ocps_group.assert_all_enabled("All OCPS components need to be enabled to run this script.")

        if checkpoint:
            await self.checkpoint("setup instrument")
            await self.camera.setup_instrument(**self.get_instrument_configuration())

        mode = self.config.script_mode
        if mode == "BIAS":
            image_types = ["BIAS"]
        elif mode == "BIAS_AND_DARK":
            image_types = ["BIAS", "DARK"]
        elif mode == "ALL":
            image_types == ["BIAS", "DARK", "FLAT"]
        else:
            raise RuntimeError("Enter a valid 'script_mode' parameter: 'BIAS', 'BIAS_AND_DARK', or 'ALL'.")

        for im_type in image_types:
            # 1. Take images with the instrument
            if checkpoint:
                if im_type == "BIAS":
                    await self.checkpoint(f"Taking {self.config.n_bias} biases.")
                elif im_type == "DARK":
                    await self.checkpoint(f"Taking {self.config.n_dark} darks.")
                else:
                    await self.checkpoint(f"Taking {self.config.n_flat} flats.")

            # TODO: Before taking flats with LATISS (and also with LSSTComCam),
            # check that the telescope is in position to do so. See DM-31496,
            # DM-31497
            exposure_ids = await self.take_images(im_type)

            if checkpoint:
                # Image IDs
                await self.checkpoint(f"Images taken: {exposure_ids}")

            # 2. Call the calibration pipetask via the OCPS to make a master
            response_ocps_calib_pipetask = await self.call_pipetask(im_type, exposure_ids)

            # 3. Verify the calibration
            if not response_ocps_calib_pipetask['phase'] == 'completed':
                raise RuntimeError(f"{im_type} generation not completed successfully: "
                                   f"{response_ocps_calib_pipetask['phase']}"
                                   f"{im_type} verification could not be performed.")
            else:
                job_id_calib = response_ocps_calib_pipetask['jobId']
                response_ocps_verify_pipetask = await self.verify_calib(im_type, job_id_calib, exposure_ids)

            # 4. Certify the calibration
            if not response_ocps_verify_pipetask['phase'] == 'completed':
                raise RuntimeError(f"{im_type} verification not completed successfully: "
                                   f"{response_ocps_verify_pipetask['phase']}"
                                   f"{im_type} certification could not be performed.")
            else:
                job_id_verify = response_ocps_verify_pipetask['jobId']
                await self.certify_calib(im_type, job_id_verify)

    async def run(self):
        """"""
        await self.arun(checkpoint=True)
