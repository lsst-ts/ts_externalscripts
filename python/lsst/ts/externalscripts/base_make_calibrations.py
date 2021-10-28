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
import os
from lsst.utils import getPackageDir
from lsst.ts import salobj
import lsst.daf.butler as dafButler


class BaseMakeCalibrations(salobj.BaseScript, metaclass=abc.ABCMeta):
    """Base class for taking images, and constructing, verifying, and
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
        self.estimated_process_time = 600

        # Callback so that the archiver queue does not overflow.
        self.image_in_oods_received_all_expected = asyncio.Event()
        self.image_in_oods_received_all_expected.clear()

        self.number_of_images_expected = None
        self.number_of_images_taken = 0
        self.image_in_oods_samples = dict(BIAS=[], DARK=[], FLAT=[])

        self.number_of_images_total = None

        self.current_image_type = None

    @property
    @abc.abstractmethod
    def ocps_group(self):
        """Define the OCPS Remote Group.

        Define the OCPS Remote Group (base class) to be able to check
        that the OCPS is enabled in `arun` before running the script.
        make it abstract since each instrument has different OCPS.
        """
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def ocps(self):
        return NotImplementedError()

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
        """Archiver imageInOODS event"""
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
                        and a master bias produced, verified, and certified. If "BIAS_DARK", \
                        the process will include bias and dark images. Note that a bias is needed \
                        to produce a dark. If "BIAS_DARK_FLAT" (default), biases, darks, and flats will be
                        produced.
                type: string
                enum: ["BIAS", "BIAS_DARK", "BIAS_DARK_FLAT"]
                default: "BIAS_DARK_FLAT"
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
            do_verify:
                type: boolean
                descriptor: Should the master calibrations be verified? (c.f., cp_verify)
                default: true
            number_verification_tests_threshold:
                type: integer
                descriptor: Minimum number of verification tests per detector per exposure per \
                    test type that should pass to certify the master calibration.
                default: 8
            config_options_bias:
                type: string
                descriptor: Options to be passed to the command-line bias pipetask. They will overwrite \
                    the values in cpBias.yaml.
                default: "-c isr:doDefect=False"
            config_options_dark:
                type: string
                descriptor: Options to be passed to the command-line dark pipetask. They will overwrite \
                    the values in cpDark.yaml.
                default: "-c isr:doDefect=False "
            config_options_flat:
                type: string
                descriptor: Options to be passed to the command-line flat pipetask. They will overwrite \
                    the values in cpFlat.yaml.
                default: "-c isr:doDefect=False "
            do_defects:
                type: boolean
                descriptor: Should defects be built using darks and flats?
                default: false
            config_options_defects:
                type: string
                descriptor: Options to be passed to the command-line defects pipetask. They will overwrite \
                    the values in findDefects.yaml.
                default: "-c isr:doDefect=False "
            do_ptc:
                type: boolean
                descriptor: Should a Photon Transfer Curve be constructed from the flats taken?
                default: false
            config_options_ptc:
                type: string
                descriptor: Options to be passed to the command-line PTC pipetask. They will overwrite \
                    the values in measurePhotonTransferCurve.yaml.
                default: "-c ptcSolve:ptcFitType=EXPAPPROXIMATION "
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
            oods_timeout:
                type: integer
                default: 120
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
            exp_times = 0.0
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
                        "n_images_"
                        + f"{image_type}".lower()
                        + f"={n_images} specified and "
                        "exp_times_"
                        + f"{image_type}".lower()
                        + f"={exp_times} is an array, "
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
        """Set estimated duration of the script."""
        n_images = self.config.n_bias + self.config.n_dark + self.config.n_flat
        metadata.duration = n_images * (
            self.camera.read_out_time + self.estimated_process_time
        )

    async def take_image_type(self, image_type, exp_times):
        """Take exposures and build exposure set.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].

        exp_times : `list`
            List of exposure times.

        Returns
        -------
            Tuple with exposure IDs.
        """

        return tuple(
            [
                (await self.camera.take_imgtype(image_type, exp_time, 1))[0]
                for exp_time in exp_times
            ]
        )

    async def image_in_oods_callback(self, data):
        """Callback function to check images are in archiver

        Parameters
        ----------
        data : `evt_imageInOODS.DataType`
            Archiver, imageInOODS event sample.
        """

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

        n_detectors = len(tuple(map(int, self.config.detectors[1:-1].split(","))))

        self.number_of_images_expected = len(exp_times) * n_detectors
        self.number_of_images_taken = 0
        self.image_in_oods_received_all_expected.clear()
        self.current_image_type = image_type

        # callback
        self.image_in_oods.callback = self.image_in_oods_callback

        exposures = await self.take_image_type(image_type, exp_times)

        await asyncio.wait_for(
            self.image_in_oods_received_all_expected.wait(),
            timeout=self.config.oods_timeout,
        )

        self.ocps.evt_job_result.flush()

        return exposures

    async def call_pipetask(self, image_type, exposure_ids_dict):
        """Call pipetasks via the OCPS.

        Parameters
        ----------
        image_type : `str`
            Image or calibration type. One of ["BIAS", "DARK",
            "FLAT", "DEFECTS", "PTC"].

        exposure_ids_dict: `dict` [`str`]
            Dictionary with tuple with exposure IDs for "BIAS",
            "DARK", or "FLAT".

        Returns
        -------
        response : `dict`
             Dictionary with the final OCPS status.
        """

        # Run the pipetask via the OCPS

        if image_type == "BIAS":
            pipe_yaml = "cpBias.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i {self.config.input_collections_bias} "
                "--register-dataset-types  "
                f"{self.config.config_options_bias}"
            )
            exposure_ids = exposure_ids_dict["BIAS"]
        elif image_type == "DARK":
            pipe_yaml = "cpDark.yaml"
            # Add calib collection to input collections with bias
            # from bias step.
            config_string = (
                f"-j {self.config.n_processes} -i {self.config.input_collections_dark} "
                f"-i {self.config.calib_collection} "
                "--register-dataset-types "
                f"{self.config.config_options_dark}"
            )
            exposure_ids = exposure_ids_dict["DARK"]
        elif image_type == "FLAT":
            pipe_yaml = "cpFlat.yaml"
            # Add calib collection to input collections with bias,
            # and dark from bias and dark steps.
            config_string = (
                f"-j {self.config.n_processes} -i {self.config.input_collections_flat} "
                f"-i {self.config.calib_collection} "
                "--register-dataset-types "
                f"{self.config.config_options_flat}"
            )
            exposure_ids = exposure_ids_dict["FLAT"]
        elif image_type == "DEFECTS":
            pipe_yaml = "findDefects.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i {self.config.input_collections_defects} "
                f"-i {self.config.calib_collection} "
                "--register-dataset-types "
                f"{self.config.config_options_defects}"
            )
            exposure_ids = exposure_ids_dict["DARK"] + exposure_ids_dict["FLAT"]
        elif image_type == "PTC":
            pipe_yaml = "cpPtc.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i {self.config.input_collections_ptc} "
                f"-i {self.config.calib_collection} "
                "--register-dataset-types "
                f"{self.config.config_options_ptc}"
            )
            exposure_ids = exposure_ids_dict["FLAT"]
        else:
            raise RuntimeError(
                "Invalid image or calib type {image_type} in 'call_pipetask' function. "
                "Valid options: ['BIAS', 'DARK', 'FLAT', 'DEFECTS', 'PTC']"
            )

        if self.instrument_name == "LATISS":
            pipeline_instrument = "Latiss"
        elif self.instrument_name == "LSSTComCam":
            pipeline_instrument = "LsstComCam"
        else:
            raise RuntimeError("Nonvalid instrument name: {self.instrument_name")

        # Use the camera-agnostic yaml file if the camera-specific
        # file does not exist.
        cp_pipe_dir = getPackageDir("cp_pipe")
        pipeline_yaml_file = os.path.join(
            cp_pipe_dir, "pipelines", pipeline_instrument, pipe_yaml
        )
        file_exists = os.path.exists(pipeline_yaml_file)
        if file_exists:
            pipeline_yaml_file = (
                "${CP_PIPE_DIR}/pipelines/" + f"{pipeline_instrument}/{pipe_yaml}"
            )
        else:
            pipeline_yaml_file = "${CP_PIPE_DIR}/pipelines/" + f"{pipe_yaml}"

        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False,
            pipeline=f"{pipeline_yaml_file}",
            version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
            f" detector IN {self.config.detectors} AND exposure IN {exposure_ids}",
        )
        if ack.ack != salobj.SalRetCode.CMD_ACK:
            ack.print_vars()

        # Wait for the in-progress acknowledgement with the job identifier.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack, wait_done=False)
        self.log.debug(
            f"Received acknowledgement of ocps command for making {image_type}"
        )

        ack.print_vars()
        job_id = json.loads(ack.result)["job_id"]

        # Wait for the command completion acknowledgement.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(
            f"Received command completion acknowledgement from ocps for {image_type}"
        )
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            ack.print_vars()
        # Wait for the job result message that matches the job id we're
        # interested in ignoring any others (from other remotes).
        # This obviously needs to follow the first acknowledgement
        # (that returns the, job id) but might as well wait for the second.
        while True:
            msg = await self.ocps.evt_job_result.next(
                flush=False, timeout=self.config.oods_timeout
            )
            response = json.loads(msg.result)
            if response["jobId"] == job_id:
                break

        self.log.info(f"Final status ({image_type}): {response}")

        return response

    async def verify_calib(self, image_type, job_id_calib, exposure_ids_dict):
        """Verify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image type. Verification currently only implemented for ["BIAS",
            "DARK", "FLAT"].

        jod_id_calib : `str`
            Job ID returned by OCPS during previous pipetask call.

        exposure_ids_dict: `dict` [`str`]
            Dictionary with tuple with exposure IDs for "BIAS",
            "DARK", or "FLAT".
        Notes
        -----
        The verification step runs tests in `cp_verify`
        that check the metrics in DMTN-101.
        """
        if image_type == "BIAS":
            pipe_yaml = "VerifyBias.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i u/ocps/{job_id_calib} "
                f"-i {self.config.input_collections_verify_bias} "
                "--register-dataset-types "
            )
            exposure_ids = exposure_ids_dict["BIAS"]
        elif image_type == "DARK":
            pipe_yaml = "VerifyDark.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i u/ocps/{job_id_calib} "
                f"-i {self.config.input_collections_verify_dark} "
                "--register-dataset-types "
            )
            exposure_ids = exposure_ids_dict["DARK"]
        elif image_type == "FLAT":
            pipe_yaml = "VerifyFlat.yaml"
            config_string = (
                f"-j {self.config.n_processes} -i u/ocps/{job_id_calib} "
                f"-i {self.config.input_collections_verify_flat} "
                "--register-dataset-types "
            )
            exposure_ids = exposure_ids_dict["FLAT"]
        else:
            raise RuntimeError(
                f"Verification is not currently implemented for {image_type}"
            )

        # Verify the master calibration
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False,
            pipeline="${CP_VERIFY_DIR}/pipelines/" + f"{pipe_yaml}",
            version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
            f" detector IN {self.config.detectors} AND exposure IN {exposure_ids}",
        )

        if ack.ack != salobj.SalRetCode.CMD_ACK:
            ack.print_vars()

        ack = await self.ocps.cmd_execute.next_ackcmd(ack, wait_done=False)
        self.log.debug(
            f"Received acknowledgement of ocps command for {image_type} verification."
        )

        ack.print_vars()
        job_id_verify = json.loads(ack.result)["job_id"]

        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(
            f"Received command completion acknowledgement from ocps ({image_type})"
        )
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            ack.print_vars()

        while True:
            msg = await self.ocps.evt_job_result.next(
                flush=False, timeout=self.config.oods_timeout
            )
            response = json.loads(msg.result)
            if response["jobId"] == job_id_verify:
                break

        self.log.info(f"Final status from {image_type} verification: {response}")

        return response

    async def check_verification_stats(self, image_type, job_id_calib, job_id_verify):
        """Check verification statistics.

        Parameters
        ----------
        image_type:
            Image type. Verification currently only implemented for ["BIAS",
            "DARK", "FLAT"].

        jod_id_calib : `str`
            Job ID returned by OCPS during previous calibration
            generation pipetask call.

        job_idverify : `str`
            Job ID returned by OCPS during previous calibration
            verification pipetask call.

        Returns
        -------
        certify_calib : `bool`
            Booolean indicating if the calibration should be certified or not.

        numStatErrors : `dict`[`str`][`str`]
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.

        thresholds : `dict`[`str`][`int`]
            Dictionary reporting the different thresholds used to decide
            whether a calibration should be certified or not (see `Notes`
            below). If there are not any tests that failed,
            `None` will be returned.

        verify_stats : `dict`
            Statistics from cp_verify.
        """
        # Collection name containing the verification outputs.
        verifyCollection = f"u/ocps/{job_id_verify}"
        # Collection that the calibration was constructed in.
        genCollection = f"u/ocps/{job_id_calib}"
        if image_type == "BIAS":
            verify_stats_string = "verifyBiasStats"
        elif image_type == "DARK":
            verify_stats_string = "verifyDarkStats"
        elif image_type == "FLAT":
            verify_stats_string = "verifyFlatStats"
        else:
            raise RuntimeError(
                f"Verification is not currently implemented for {image_type}"
            )
        butler = dafButler.Butler(
            self.config.repo, collections=[verifyCollection, genCollection]
        )
        # verify_stats is a dictionary with the verification
        # tests that failed, if any. See `cp_verify`.
        verify_stats = butler.get(verify_stats_string, instrument=self.instrument_name)

        if "FAILURES" in verify_stats:
            (
                certify_calib,
                numStatErrors,
                failure_thresholds,
            ) = await self.count_failed_verification_tests(verify_stats)

            return certify_calib, numStatErrors, failure_thresholds, verify_stats
        else:
            # Nothing failed
            return True, None, None, verify_stats

    async def count_failed_verification_tests(self, verify_stats):
        """Count number of tests that failed cp_verify.

        Parameters
        ----------
        verify_stats : `dict`
            Statistics from cp_verify.

        Returns
        -------
        certify_calib : `bool`
            Boolean assessing whether the calibration should be certified.

        total_counter_failed_tests : `dict`[`str`][`str`]
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.

        thresholds : `dict`[`str`][`int`]
            Dictionary reporting the different thresholds used to decide
            whether a calibration shoudl be certified or not (see `Notes`
            below).

        Notes
        -----
        For at least one type of test, if the majority of tests fail in
        the majority of detectors and the majority of exposures,
        then don't certify the calibration.
        """
        certify_calib = True

        # Thresholds

        min_number_failures_per_detector_per_test = (
            self.config.number_verification_tests_threshold
        )
        # Main key of verify_stats is exposure IDs
        min_number_failed_exposures = int(len(verify_stats) / 2) + 1  # majority of exps

        first_exp = list(verify_stats.keys())[0]
        # "stg" is of the form "detector_amp_test", and "detector" is
        # of the form "raft_det".
        detectors = set(
            [stg.split(" ")[0] for stg in verify_stats[first_exp]["FAILURES"]]
        )
        min_number_failed_detectors = (
            int(len(detectors) / 2) + 1
        )  # majority of detectors

        # Define failure threshold per exposure
        failure_threshold_exposure = (
            min_number_failures_per_detector_per_test * min_number_failed_detectors
        )

        # Count the number of failures per test per exposure.
        total_counter_failed_tests = {}
        # Pop this key so that we are left with
        # exposure ID's as keys only.
        verify_stats.pop("SUCCESS")
        for exposure in verify_stats:
            if "FAILURES" in verify_stats[exposure]:
                fail_count = [
                    stg.split(" ")[2] for stg in verify_stats[exposure]["FAILURES"]
                ]
                counter = {}
                for test in fail_count:
                    if test in counter:
                        counter[test] += 1
                    else:
                        counter[test] = 1
                total_counter_failed_tests[exposure] = counter
            else:
                continue

        # If there are not exposures with tests that failed.
        if len(total_counter_failed_tests) == 0:
            return certify_calib, None

        # Count the number of exposures where a given test fails
        # in the majority of detectors.
        failed_exposures_counter = 0
        for exposure in total_counter_failed_tests:
            for test in total_counter_failed_tests[exposure]:
                if (
                    total_counter_failed_tests[exposure][test]
                    >= failure_threshold_exposure
                ):
                    failed_exposures_counter += 1
                    # Exit the inner loop over tests: just need
                    # the condition to be satisfied for
                    # at least one type of test
                    break

        # For at least one type of test, if the majority of tests fail in
        # the majority of detectors and the majority of exposures,
        # then don't certify the calibration
        if failed_exposures_counter >= min_number_failed_exposures:
            certify_calib = False

        # Return a dictionary with the thresholds to report
        # them if verification fails.
        thresholds = {
            "MIN_FAILURES_PER_DETECTOR_PER_TEST_TYPE_THRESHOLD": min_number_failures_per_detector_per_test,
            "MIN_FAILED_DETECTORS_THRESHOLD": min_number_failed_detectors,
            "MIN_FAILED_TESTS_PER_EXPOSURE_THRESHOLD": failure_threshold_exposure,
            "MIN_FAILED_EXPOSURES_THRESHOLD": min_number_failed_exposures,
            "FINAL_NUMBER_OF_FAILED_EXPOSURES": failed_exposures_counter,
        }

        return certify_calib, total_counter_failed_tests, thresholds

    async def certify_calib(self, image_type, job_id_calib):
        """Certify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT", "DEFECTS", "PTC"].

        jod_id_calib : `str`
            Job ID returned by OCPS during previous calibration
            generation pipetask call.

        Notes
        -----
        The calibration will certified for use with a timespan that indicates
        its validity range.
        """
        # Certify the calibration, if the verification job
        # completed successfully
        self.log.info(f"Certifying {image_type} ")
        REPO = self.config.repo
        # This is the output collection from the verification step
        CALIB_PRODUCT_COL = f"u/ocps/{job_id_calib}"
        CALIB_COL = self.config.calib_collection
        cmd = (
            f"butler certify-calibrations {REPO} {CALIB_PRODUCT_COL} {CALIB_COL} "
            f"--begin-date {self.config.certify_calib_begin_date} "
            f"--end-date {self.config.certify_calib_end_date}"
            + f" {image_type}".lower()
        )
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
        await self.camera.assert_all_enabled(
            "All camera components need to be enabled to run this script."
        )

        # Check that the OCPS is enabled
        await self.ocps_group.assert_all_enabled(
            "All OCPS components need to be enabled to run this script."
        )

        if checkpoint:
            await self.checkpoint("setup instrument")
            await self.camera.setup_instrument(**self.get_instrument_configuration())

        mode = self.config.script_mode
        if mode == "BIAS":
            image_types = ["BIAS"]
        elif mode == "BIAS_DARK":
            image_types = ["BIAS", "DARK"]
        elif mode == "BIAS_DARK_FLAT":
            image_types = ["BIAS", "DARK", "FLAT"]
        else:
            raise RuntimeError(
                "Enter a valid 'script_mode' parameter: 'BIAS', 'BIAS_DARK', or "
                "'BIAS_DARK_FLAT'."
            )

        if self.config.do_defects and mode == "BIAS_DARK_FLAT":
            image_types.append("DEFECTS")
        if self.config.do_ptc and mode == "BIAS_DARK_FLAT":
            image_types.append("PTC")

        exposure_ids_dict = {"BIAS": (), "DARK": (), "FLAT": ()}
        for im_type in image_types:
            # 1. Take images with the instrument, only for "BIAS,
            # "DARK", or "FLAT".
            if im_type in ["BIAS", "DARK", "FLAT"]:
                if checkpoint:
                    if im_type == "BIAS":
                        await self.checkpoint(f"Taking {self.config.n_bias} biases.")
                    elif im_type == "DARK":
                        await self.checkpoint(f"Taking {self.config.n_dark} darks.")
                    elif im_type == "FLAT":
                        await self.checkpoint(f"Taking {self.config.n_flat} flats.")

                # TODO: Before taking flats with LATISS (and also
                # with LSSTComCam), check that the telescope is in
                # position to do so. See DM-31496, DM-31497.
                exposure_ids = await self.take_images(im_type)
                exposure_ids_dict[im_type] = exposure_ids

                if checkpoint:
                    # Image IDs
                    await self.checkpoint(
                        f"Images taken: {exposure_ids}; type: {im_type}"
                    )

            # 2. Call the calibration pipetask via the OCPS to make a master
            response_ocps_calib_pipetask = await self.call_pipetask(
                im_type, exposure_ids_dict
            )

            # 3. Verify the calibration (implemented so far for bias,
            # dark, and flat).
            job_id_calib = response_ocps_calib_pipetask["jobId"]
            if self.config.do_verify and im_type in ["BIAS", "DARK", "FLAT"]:
                if not response_ocps_calib_pipetask["phase"] == "completed":
                    raise RuntimeError(
                        f"{im_type} generation not completed successfully: "
                        f"Status: {response_ocps_calib_pipetask['phase']}. "
                        f"{im_type} verification could not be performed."
                    )
                else:
                    response_ocps_verify_pipetask = await self.verify_calib(
                        im_type, job_id_calib, exposure_ids_dict
                    )
                    previous_step = "verification"
            else:
                self.log.info(f"Skipping verification for {im_type}. ")
                response_ocps_verify_pipetask = response_ocps_calib_pipetask
                previous_step = "generation"

            # 4. Certify the calibration if the verification tests passed
            if not response_ocps_verify_pipetask["phase"] == "completed":
                raise RuntimeError(
                    f"{im_type} {previous_step} not completed successfully: "
                    f"Status: {response_ocps_verify_pipetask['phase']}. "
                    f"{im_type} certification could not be performed."
                )
            else:
                # Check the verification statistics and decide whether
                # the master calibration gets certified or not.
                job_id_verify = response_ocps_verify_pipetask["jobId"]
                (
                    verify_tests_pass,
                    verify_report,
                    thresholds_report,
                    verify_stats,
                ) = await self.check_verification_stats(
                    im_type, job_id_calib, job_id_verify
                )
                if verify_tests_pass:
                    await self.certify_calib(im_type, job_id_calib)
                elif verify_tests_pass and verify_report is not None:
                    await self.certify_calib(im_type, job_id_calib)
                    self.log.warning(
                        f"{im_type} calibration passed the overall verification "
                        " criteria and was certified, but the following tests did not pass: "
                        f" {verify_report} \n "
                        f" {verify_stats}"
                    )
                else:
                    raise RuntimeError(
                        f"{im_type} calibration was not certified. \n"
                        "The number of tests that did not pass per test type per exposure is: "
                        f"{verify_report} \n"
                        "Thresholds used to decide whether a calibration should be certified or not: "
                        f"{thresholds_report} \n"
                        "MIN_FAILURES_PER_DETECTOR_PER_TEST_TYPE_THRESHOLD is given by the config parameter: "
                        "'number_verification_tests_threshold' \n"
                        "For at least one type of test, if the majority of tests fail in the majority of "
                        "detectors and the majority of exposures, the calibration will not be certified "
                        "(if FINAL_NUMBER_OF_FAILED_EXPOSURES >= MIN_FAILED_EXPOSURES_THRESHOLD). \n"
                        f"Statistics returned by `cp_verify`: {verify_stats}"
                    )

    async def run(self):
        """"""
        await self.arun(checkpoint=True)
