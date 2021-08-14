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


class BaseMakeCalibrations(salobj.BaseScript, metaclass=abc.ABCMeta):
    """ Base class for taking images,and constructing, verifying, and
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
        self.ocps = salobj.Remote(domain=self.domain, name="OCPS")

    @property
    @abc.abstractmethod
    def camera(self):
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
            n_bias:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: null
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
                descriptor: Detector IDs
            input_collections_bias:
                type: string
                descriptor: Comma-separarted input collections to pass to the bias pipetask.
            input_collections_verify_bias:
                type: string
                descriptor: Comma-separarted input collections to pass to the verify (bias) pipetask.
            config_options_bias:
                type: string
                descriptor: Options to be passed to the command-line bias pipetask. They will overwrite \
                    the values in cpBias.yaml.
                default: "-c isr:doDefect=False -c isr:doLinearize=False -c isr:doCrosstalk=False \
                          -c isr:overscan.fitType='MEDIAN_PER_ROW'"
            input_collections_dark:
                type: string
                descriptor: Comma-separarted input collections to pass to the dark pipetask.
            input_collections_verify_dark:
                type: string
                descriptor: Comma-separarted input collections to pass to the verify (dark) pipetask.
            config_options_dark:
                type: string
                descriptor: Options to be passed to the command-line dark pipetask. They will overwrite \
                    the values in cpDark.yaml.
                default: "-c isr:doDefect=False -c isr:doLinearize=False -c isr:doCrosstalk=False"
            calib_collection:
                type: string
                descriptor: Calibration collection where master calibrations will be certified into.
            repo:
                type: string
                descriptor: Butler repository.
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
                default: 600
                descriptor: Timeout value, in seconds, for OODS.
        additionalProperties: false
        required: [input_collections_bias, input_collections_verify_bias, calib_collection,\
                   [input_collections_dark, input_collections_verify_dark, repo]
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
            n_images = self.config.n_images_bias
            exp_times = 0.
        elif image_type == "DARK":
            n_images = self.config.n_images_dark
            exp_times = self.config.exp_times_dark
        else:
            n_images = self.config.n_images_flat
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

    def take_images(self, image_type):
        """Take images wiht instrument.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        Returns
        -------
        exposures : `tuple`
             Tuple with the IDs of the exposures taken.
        """

        exp_times = self.set_exp_times_per_im_type(image_type)

        self.image_in_oods.flush()

        # Take images and return a list of IDs
        exposures = ()
        for i, exp_time in enumerate(exp_times):
            exp = tuple(await self.camera.take_imgtype(image_type, exp_time, 1))
            exposures += exp

        # did the images get archived and are they available to the butler?
        n_detectors = len(tuple(map(int, self.config.detectors[1:-1].split(','))))
        # exps are of the form, e.g., 2021070800019
        exposure_set = set()
        for exp in exposures:
            obs_day = f"{exp}"[:8]
            temp = int(f"{exp}"[8:])
            # See example of ack.obsid below
            seq_num = f"{temp:06}"
            obs_id = obs_day + "_" + seq_num
            exposure_set.add(obs_id)

        images_remaining = len(exposure_set)*n_detectors
        max_counter = self.config.max_counter_archiver_check
        counter = 0
        while images_remaining > 0:
            ack = await self.image_in_oods.next(flush=False, timeout=self.config.oods_timeout)
            # ack.obsid is of the form, e.g., CC_O_20210708_000019
            if f"{ack.obsid[-15:]}" in exposure_set:
                images_remaining -= 1
                counter = 0
            if counter == max_counter:
                self.log.warning(f"Maximum number of loops ({max_counter}) reached while waiting "
                                 "for image in archiver")
                break
            counter += 1

        self.ocps.evt_job_result.flush()

        return exposures

    def call_pipetask(self, image_type, exposure_ids):
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
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_dark} "
                             "--register-dataset-types "
                             f"{self.config.config_options_dark}")
        elif:
            pipe_yaml = "cpFlat.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_flat} "
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

    def verify_calib(self, image_type, job_id_calib, exposures):
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
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_bias_verify} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types "
                             f"{self.config.config_options_verify_bias}")
        elif image_type == "DARK":
            pipe_yaml = "VerifyDark.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_dark_verify} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types "
                             f"{self.config.config_options_verify_dark}")
        else:
            pipe_yaml = "VerifyFlat.yaml"
            config_string = (f"-j {self.config.n_processes} -i {self.config.input_collections_flat_verify} "
                             f"-i u/ocps/{job_id_calib} "
                             "--register-dataset-types "
                             f"{self.config.config_options_verify_flat}")


        # Verify the master calibration
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False, pipeline="${CP_VERIFY_DIR}/pipelines/" + f"${pipe_yaml}", version="",
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

    def certify_calib(self, image_type, job_id_verify):
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
        # Certify the bias, if the verification job completed successfully
        self.log.info(f"Certifying {image_type} ")
        # certify the master calibration
        REPO = self.config.repo
        # This is the output collection from the verification step
        CALIB_PRODUCT_COL = f"u/ocps/{job_id_verify}"
        CALIB_COL = self.config.calib_collection
        cmd = (f"butler certify-calibrations {REPO} {CALIB_PRODUCT_COL} {CALIB_COL} "
               f"--begin-date {self.config.certify_calib_begin_date} "
               f"--end-date {self.config.certify_calib_end_date}" + f"{image_type}".lower())
        self.log.info(cmd)

        process = await asyncio.create_subprocess_shell(cmd)
        stdout, stderr = await process.communicate()
        self.log.debug(f"Process returned: {process.returncode}")
        if process.returncode != 0:
            self.log.debug(stdout)
            self.log.error(stderr)
            raise RuntimeError(f"Error running command for certifying {image_type}.")

    async def arun(self, checkpoint=False):
        image_types = ["BIAS", "DARK", "FLAT"]
        for im_type in image_types:
            # 1. Take images with the instrument
            if checkpoint:
                if im_type == "BIAS":
                    await self.checkpoint(f"Taking {self.config.n_bias} biases.")
                elif im_type == "DARK":
                    await self.checkpoint(f"Taking {self.config.n_dark} darks.")
                else:
                    await self.checkpoint(f"Taking {self.config.n_flat} flats.")

            exposure_ids = self.take_images(im_type)

            if checkpoint:
                # Image IDs
                await self.checkpoint(f"Images taken: {exposure_ids}")

            # 2. Call the calibration pipetask via the OCPS to make a master
            response_ocps_calib_pipetask = self.call_pipetask(im_type, exposure_ids)

            # 3. Verify the calibration
            if not response_ocps_calib_pipetask['phase'] == 'completed':
                raise RuntimeError(f"{im_type} generation not completed successfully: "
                                   f"{response_ocps_calib_pipetask['phase']}"
                                   f"{im_type} verification could not be performed.")
            else:
                job_id_calib = response_ocps_calib_pipetask['job_ib']
                response_ocps_verify_pipetask = self.verify_calib(im_type, job_id_calib, exposure_ids)

            # 4. Certify the calibration
            if not response_ocps_verify_pipetask['phase'] == 'completed':
                raise RuntimeError(f"{im_type} verification not completed successfully: "
                                   f"{response_ocps_verify_pipetask['phase']}"
                                   f"{im_type} certification could not be performed.")
            else:
                job_id_verify = response_ocps_verify_pipetask['job_id']
                self.certify_calib(im_type, job_id_verify)
