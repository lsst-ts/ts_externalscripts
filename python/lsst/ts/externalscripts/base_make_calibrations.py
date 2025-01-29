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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["BaseMakeCalibrations"]

import abc
import asyncio
import collections
import json
import os

import lsst.daf.butler as dafButler
import numpy as np
import yaml
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.utils import getPackageDir


class BaseMakeCalibrations(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base class for taking images, and constructing, verifying, and
        certifying combined calibrations.

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

        # Callback so that the oods queue does not overflow.
        self.image_in_oods_received_all_expected = asyncio.Event()
        self.image_in_oods_received_all_expected.clear()

        self.number_of_images_expected = None
        self.number_of_images_taken = 0
        self.image_in_oods_samples = dict(BIAS=[], DARK=[], FLAT=[])

        self.number_of_images_total = None

        self.current_image_type = None

        # Supported calibrations types
        self.supported_calibrations_certification = [
            "BIAS",
            "DARK",
            "FLAT",
            "DEFECTS",
            "PTC",
        ]

        self.background_tasks = []

        # Pipetask methods to get parameters for calibrations generation
        self.pipetask_parameters = dict(
            BIAS=self.get_pipetask_parameters_bias,
            DARK=self.get_pipetask_parameters_dark,
            FLAT=self.get_pipetask_parameters_flat,
            DEFECTS=self.get_pipetask_parameters_defects,
            PTC=self.get_pipetask_parameters_ptc,
            GAIN=self.get_pipetask_parameters_ptc,
        )

        # Pipetask methods to get parameters for calibrations verification
        self.pipetask_parameters_verification = dict(
            BIAS=self.get_pipetask_parameters_verification_bias,
            DARK=self.get_pipetask_parameters_verification_dark,
            FLAT=self.get_pipetask_parameters_verification_flat,
        )

        # List of exposure IDs
        self.exposure_ids = dict(BIAS=[], DARK=[], FLAT=[])

        # Number of first exposures taken to discard in pipetasks
        self.n_images_discard = dict(
            BIAS=0,
            DARK=0,
            FLAT=0,
        )

        self.config = None

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
        """String with instrument name for pipeline tasks"""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def pipeline_instrument(self):
        """String with instrument name for pipeline yaml file"""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def detectors(self):
        """String with detector IDs for pipeline tasks"""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def n_detectors(self):
        """Number of detectors for pipeline tasks"""
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def image_in_oods(self):
        """OODS imageInOODS event"""
        raise NotImplementedError()

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/externalscripts/"
            "/base_make_calibrations.py"
        )
        schema = f"""
        $schema: http://json-schema.org/draft-07/schema#
        $id: {url}/{path}
        title: BaseMakeCalibrations v1
        description: Configuration for BaseMakeCalibrations.
        type: object
        properties:
            script_mode:
                description: Type of images to make. If "BIAS", only biases will be taken \
                        and a combined bias produced, verified, and certified. If "BIAS_DARK", \
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
                default: 20
                description: Number of biases to take.
            n_discard_bias:
                anyOf:
                  - type: integer
                    minimum: 0
                  - type: "null"
                default: 1
                description: Additional number of bias images to take and discard before starting
                    the sequence.
            n_dark:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 22
                description: Number of darks to take.
            n_discard_dark:
                anyOf:
                  - type: integer
                    minimum: 0
                  - type: "null"
                default: 1
                description: Additional number of dark images to take and discard before starting
                    the sequence.
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
                default: [5,
                    5, 5, 5, 5,
                    15, 15,
                    30, 30, 30, 30,
                    30, 30, 30, 30,
                    30, 30, 30, 30,
                    30, 30, 30, 30]
            n_flat:
                anyOf:
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: 20
                description: Number of flats to take.
            n_discard_flat:
                anyOf:
                  - type: integer
                    minimum: 0
                  - type: "null"
                default: 1
                description: Additional number of flat images to take and discard before starting
                    the sequence.
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
                default: 5
            generate_calibrations:
                type: boolean
                descriptor: Should the combined calibrations be generated from the images taken? \
                    If False, and do_verify = True, reference calibrations should be provided in the \
                    input collections for the verification pipetasks.
                default: False
            do_verify:
                type: boolean
                descriptor: Should the combined calibrations be verified? (c.f., cp_verify)
                default: true
            number_verification_tests_threshold_bias:
                type: integer
                descriptor: Minimum number of verification tests per detector per exposure per \
                    test type that should pass to certify the bias combined calibration.
                default: 8
            number_verification_tests_threshold_dark:
                type: integer
                descriptor: Minimum number of verification tests per detector per exposure per \
                    test type that should pass to certify the dark combined calibration.
                default: 8
            number_verification_tests_threshold_flat:
                type: integer
                descriptor: Minimum number of verification tests per detector per exposure per \
                    test type that should pass to certify the flat combined calibration.
                default: 8
            config_options_bias:
                type: string
                descriptor: Options to be passed to the command-line bias pipetask. They will overwrite \
                    the values in cpBias.yaml.
                default: " "
            config_options_dark:
                type: string
                descriptor: Options to be passed to the command-line dark pipetask. They will overwrite \
                    the values in cpDark.yaml.
                default: " "
            config_options_flat:
                type: string
                descriptor: Options to be passed to the command-line flat pipetask. They will overwrite \
                    the values in cpFlat.yaml.
                default: " "
            do_defects:
                type: boolean
                descriptor: Should defects be built using darks and flats? This configuration will \
                    only be in effect if script_mode = BIAS_DARK_FLAT.
                default: false
            config_options_defects:
                type: string
                descriptor: Options to be passed to the command-line defects pipetask. They will overwrite \
                    the values in findDefects.yaml.
                default: " "
            do_ptc:
                type: boolean
                descriptor: Should a Photon Transfer Curve be constructed from the flats taken? This \
                    configuration will only be in effect if script_mode = BIAS_DARK_FLAT.
                default: false
            config_options_ptc:
                type: string
                descriptor: Options to be passed to the command-line PTC pipetask. They will overwrite \
                    the values in cpPtc.yaml.
                default: " "
            do_gain_from_flat_pairs:
                type: boolean
                descriptor: Should the gain be estimated from each pair of flats
                    taken at the same exposure time? Runs the cpPtc.yaml#cpPtcGainFromFlatPairs \
                    pipeline. Use the 'config_options_ptc' parameter to pass options to the ISR and \
                    cpExtract tasks. This configuration will only be in effect if \
                    script_mode = BIAS_DARK_FLAT.
                default: true
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
            background_task_timeout:
                type: integer
                default: 30
                descriptor: Timeout value, in seconds, for background tasks
            note:
                description: A descriptive note about the images being taken.
                type: string
        additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def set_exp_times_per_im_type(self, image_type):
        """Define exp_times and n_images according to image type.

        Parameters
        ----------
        image_type : `str`
            Image type. One of ["BIAS", "DARK", "FLAT"].
        """

        if image_type == "BIAS":
            n_images = self.config.n_bias + self.config.n_discard_bias
            exp_times = 0.0
        elif image_type == "DARK":
            n_images = self.config.n_dark + self.config.n_discard_dark
            exp_times = self.config.exp_times_dark
        else:
            n_images = self.config.n_flat + self.config.n_discard_flat
            exp_times = self.config.exp_times_flat

        if isinstance(exp_times, collections.abc.Iterable):
            if n_images is not None:
                if len(exp_times) != n_images:
                    raise ValueError(
                        f"n_images_{image_type.lower()}={n_images} specified and "
                        f"exp_times_{image_type.lower()}={exp_times} is an array, "
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
            f"n_bias: {config.n_bias}, detectors: {self.detectors}, "
            f"n_dark: {config.n_dark}, "
            f"n_flat: {config.n_flat}, "
            f"instrument: {self.instrument_name}, "
            f"script_mode: {config.script_mode}, "
            f"generate_calibrations: {config.generate_calibrations}, "
            f"do_verify: {config.do_verify}, "
            f"do_defects: {config.do_defects}, "
            f"do_ptc: {config.do_ptc}, "
            f"do_gain_from_flat_pairs: {config.do_gain_from_flat_pairs} "
        )

        self.config = config
        self.detectors_string = self.get_detectors_string(self.detectors)
        self.n_images_discard["BIAS"] = config.n_discard_bias
        self.n_images_discard["DARK"] = config.n_discard_dark
        self.n_images_discard["FLAT"] = config.n_discard_flat

        await super().configure(config=config)

    def set_metadata(self, metadata):
        """Set estimated duration of the script."""
        n_images = self.config.n_bias + self.config.n_dark + self.config.n_flat
        n_discarded = (
            self.n_images_discard["BIAS"]
            + self.n_images_discard["DARK"]
            + self.n_images_discard["FLAT"]
        )
        n_images += n_discarded

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

        self.note = getattr(self.config, "note", None)
        group_id = self.group_id if not self.obs_id else self.obs_id

        return tuple(
            [
                (
                    await self.camera.take_imgtype(
                        image_type,
                        exp_time,
                        1,
                        reason=self.reason,
                        program=self.program,
                        note=self.note,
                        group_id=group_id,
                    )
                )[0]
                for exp_time in exp_times
            ]
        )

    async def image_in_oods_callback(self, data):
        """Callback function to check images are in oods

        Parameters
        ----------
        data : `evt_imageInOODS.DataType`
            OODS, imageInOODS event sample.
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

        self.number_of_images_expected = len(exp_times) * self.n_detectors
        self.number_of_images_taken = 0
        self.image_in_oods_received_all_expected.clear()
        self.current_image_type = image_type

        # callback
        self.image_in_oods.callback = self.image_in_oods_callback

        exposures = await self.take_image_type(image_type, exp_times)

        try:
            await asyncio.wait_for(
                self.image_in_oods_received_all_expected.wait(),
                timeout=self.config.oods_timeout,
            )
        except asyncio.TimeoutError:
            expected_ids = set(exposures)
            received_ids = set()
            try:
                received_ids = set(
                    [
                        self.get_exposure_id(image_in_oods.obsid)
                        for image_in_oods in self.image_in_oods_samples[image_type]
                    ]
                )
            except ValueError:
                obs_ids = [
                    image_in_oods.obsid
                    for image_in_oods in self.image_in_oods_samples[image_type]
                ]
                self.log.error(f"Could not parse list of received_ids. Got {obs_ids}.")
            missing_image_ids = expected_ids - received_ids

            self.log.error(
                "Timeout waiting for images to ingest in the OODS, "
                f"expected: {self.number_of_images_expected}, "
                f"received: {len(self.image_in_oods_samples[image_type])}. "
                f"Missing image ids: {missing_image_ids}"
            )

        self.ocps.evt_job_result.flush()

        return exposures

    def get_pipetask_parameters_bias(self):
        """Get necessary information to run the bias generation pipetask.

        Returns
        -------
        cpBias.yaml : `str`
            cp_pipe bias pipeline.

        config_string : `str`
            Bias pipetask configuration for OCPS.

        exposure_ids_bias : `list`[`int`]
            List of bias exposure IDs.
        """

        return (
            "cpBias.yaml",
            (
                f"-j {self.config.n_processes} -i {self.config.input_collections_bias} "
                "--register-dataset-types  "
                f"{self.config.config_options_bias}"
            ),
            self.exposure_ids["BIAS"],
        )

    def get_pipetask_parameters_dark(self):
        """Get necessary information to run the dark generation pipetask.

        Returns
        -------
        cpDark.yaml : `str`
            cp_pipe dark pipeline.

        config_string : `str`
            Dark pipetask configuration for OCPS.

        exposure_ids_dark : `list`[`int`]
            List of dark exposure IDs.
        """
        if self.config.generate_calibrations:
            input_collections_dark = (
                f"{self.config.calib_collection},"
                f"{self.config.input_collections_dark}"
            )
        else:
            input_collections_dark = f"{self.config.input_collections_dark}"

        return (
            "cpDark.yaml",
            (
                f"-j {self.config.n_processes} -i {input_collections_dark} "
                "--register-dataset-types "
                f"{self.config.config_options_dark}"
            ),
            self.exposure_ids["DARK"],
        )

    def get_pipetask_parameters_flat(self):
        """Get necessary information to run the flat generation pipetask.

        Returns
        -------
        cpFlat.yaml : `str`
            cp_pipe flat pipeline.

        config_string : `str`
            Flat pipetask configuration for OCPS.

        exposure_ids_flat : `list`[`int`]
            List of flat exposure IDs.
        """
        if self.config.generate_calibrations:
            input_collections_flat = (
                f"{self.config.calib_collection},"
                f"{self.config.input_collections_flat}"
            )
        else:
            input_collections_flat = f"{self.config.input_collections_flat}"

        return (
            "cpFlat.yaml",
            (
                f"-j {self.config.n_processes} -i {input_collections_flat} "
                "--register-dataset-types "
                f"{self.config.config_options_flat}"
            ),
            self.exposure_ids["FLAT"],
        )

    def get_pipetask_parameters_defects(self):
        """Get necessary information to run the defects generation pipetask.

        Returns
        -------
        findDefects.yaml : `str`
            cp_pipe defects pipeline.

        config_string : `str`
            Defects pipetask configuration for OCPS.

        exposure_ids_defects : `list`[`int`]
            List of dark and flat exposure IDs.
        """
        if self.config.generate_calibrations:
            input_collections_defects = (
                f"{self.config.calib_collection},"
                f"{self.config.input_collections_defects}"
            )
        else:
            input_collections_defects = f"{self.config.input_collections_defects}"

        return (
            "cpDefects.yaml",
            (
                f"-j {self.config.n_processes} -i {input_collections_defects} "
                "--register-dataset-types "
                f"{self.config.config_options_defects}"
            ),
            self.exposure_ids["DARK"] + self.exposure_ids["FLAT"],
        )

    def get_pipetask_parameters_ptc(self):
        """Get necessary information to run the ptc generation pipetask.

        Returns
        -------
        cpPtc.yaml or cpPtc.yaml#cpPtcGainFromFlatPairs : `str`
            cp_pipe PTC or gain from pairs pipeline.

        config_string : `str`
            PTC or gain from pairs pipetask configuration for OCPS.

        exposure_ids_ptc : `list`[`int`]
            List of flat exposure IDs for PTC or gain estimation.
        """
        if self.config.generate_calibrations:
            input_collections_ptc = (
                f"{self.config.calib_collection},"
                f"{self.config.input_collections_ptc}"
            )
        else:
            input_collections_ptc = f"{self.config.input_collections_ptc}"

        if (self.config.do_ptc is False) and (
            self.config.do_gain_from_flat_pairs is True
        ):
            pipeline_yaml_file = "cpPtc.yaml#cpPtcGainFromFlatPairs"
        else:
            pipeline_yaml_file = "cpPtc.yaml"

        return (
            pipeline_yaml_file,
            (
                f"-j {self.config.n_processes} -i {input_collections_ptc} "
                "--register-dataset-types "
                f"{self.config.config_options_ptc}"
            ),
            self.exposure_ids["FLAT"],
        )

    async def call_pipetask(self, image_type):
        """Call pipetasks via the OCPS.

        Parameters
        ----------
        image_type : `str`
            Image or calibration type.

        Returns
        -------
        response : `dict`
             Dictionary with the final OCPS status.

        Notes
        -----
        Suported calibrations: see `self.pipetask_parameters`
        """

        # Run the pipetasks via the OCPS.
        # By default, config.generate_calibrations is 'false'
        # and the necessary calibrations are assumed to be
        # in the input collections.
        if image_type in self.pipetask_parameters:
            pipe_yaml, config_string, exposure_ids = self.pipetask_parameters[
                image_type
            ]()
        else:
            self.log.error(
                "Invalid image or calib type {image_type} in 'call_pipetask' function. "
                f"Valid options: {self.pipetask_parameters.keys()}"
            )

        # Use the camera-agnostic yaml file if the camera-specific
        # file does not exist.
        cp_pipe_dir = getPackageDir("cp_pipe")

        on_disk_yaml = pipe_yaml
        if "#" in on_disk_yaml:
            # We are using a subset from this yaml, and so must remove
            # the subset before checking for file existence.
            on_disk_yaml = on_disk_yaml.split("#", 1)[0]

        pipeline_yaml_file = os.path.join(
            cp_pipe_dir, "pipelines", self.pipeline_instrument, on_disk_yaml
        )
        file_exists = os.path.exists(pipeline_yaml_file)
        if file_exists:
            pipeline_yaml_file = (
                f"${{CP_PIPE_DIR}}/pipelines/{self.pipeline_instrument}/{pipe_yaml}"
            )
        else:
            pipeline_yaml_file = f"${{CP_PIPE_DIR}}/pipelines/_ingredients/{pipe_yaml}"

        # This returns the in-progress acknowledgement with the job identifier
        exposure_id_string = (
            str(exposure_ids) if len(exposure_ids) > 1 else f"({exposure_ids[0]})"
        )
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False,
            pipeline=f"{pipeline_yaml_file}",
            version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
            f" detector IN {self.detectors_string} AND exposure IN {exposure_id_string}",
        )
        self.log.debug(
            f"Received acknowledgement of ocps command for {image_type} pipetask."
        )

        job_id = json.loads(ack.result)["job_id"]

        # Wait for the command completion acknowledgement.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(
            f"Received command completion acknowledgement from ocps for {image_type}."
        )
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            self.log.debug(
                f"OCPS job not complete, received {ack}. Continuing to wait for job result."
            )
        # Wait for the job result message that matches the job id we're
        # interested in ignoring any others (from other remotes).
        # This needs to follow the first acknowledgement
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

    def get_pipetask_parameters_verification_bias(self, job_id_calib):
        """Get necessary information to run the bias verification pipetask

        Parameters
        ----------
        jod_id_calib : `str`
            Job ID returned by OCPS during calibration generation
            pipetask call. If `None`, the calibrations will be sought
            at the input collections.

        Returns
        -------
        pipe_yaml : `str`
            cp_verify bias pipeline.

        config_string : `str`
            Bias verification pipetask configuration for OCPS.

        exposure_ids_bias : `list`[`int`]
            List of bias exposure IDs.
        """

        pipe_yaml = "verifyBias.yaml"
        # If the combined calibration was not generated with the images
        # taken at the beginning of the script, the verification
        # pipetask will use the calibrations provided as input
        # collections in the configuration file.
        if job_id_calib is None:
            input_col_verify_bias_string = (
                f"-i {self.config.input_collections_verify_bias}"
            )
        else:
            input_col_verify_bias_string = (
                f"-i u/ocps/{job_id_calib},"
                f"{self.config.input_collections_verify_bias}"
            )
        config_string = (
            f"-j {self.config.n_processes} "
            f"{input_col_verify_bias_string} "
            "--register-dataset-types "
        )
        exposure_ids = self.exposure_ids["BIAS"]

        return pipe_yaml, config_string, exposure_ids

    def get_pipetask_parameters_verification_dark(self, job_id_calib):
        """Get necessary information to run the dark verification pipetask

        Parameters
        ----------
        jod_id_calib : `str`
            Job ID returned by OCPS during calibration generation
            pipetask call. If `None`, the calibrations will be sought
            at the input collections.

        Returns
        -------
        pipe_yaml : `str`
            cp_verify dark pipeline.

        config_string : `str`
            Dark verification pipetask configuration for OCPS.

        exposure_ids_dark : `list`[`int`]
            List of dark exposure IDs.
        """
        pipe_yaml = "verifyDark.yaml"
        # If the combined calibration was not generated with the images
        # taken at the beginning of the script, the verification
        # pipetask will use the calibrations provided as input
        # collections in the configuration file.
        if job_id_calib is None:
            input_col_verify_dark_string = (
                f"-i {self.config.input_collections_verify_dark}"
            )
        else:
            input_col_verify_dark_string = (
                f"-i u/ocps/{job_id_calib},"
                f"{self.config.input_collections_verify_dark}"
            )
        config_string = (
            f"-j {self.config.n_processes} "
            f"{input_col_verify_dark_string} "
            "--register-dataset-types "
        )
        exposure_ids = self.exposure_ids["DARK"]

        return pipe_yaml, config_string, exposure_ids

    def get_pipetask_parameters_verification_flat(self, job_id_calib):
        """Get necessary information to run the flat verification pipetask.

        Parameters
        ----------
        jod_id_calib : `str`
            Job ID returned by OCPS during calibration generation
            pipetask call. If `None`, the calibrations will be sought
            at the input collections.

        Returns
        -------
        pipe_yaml : `str`
            cp_verify flat pipeline.

        config_string : `str`
            Flat verification pipetask configuration for OCPS.

        exposure_ids_flat : `list`[`int`]
            List of flat exposure IDs.
        """

        pipe_yaml = "verifyFlat.yaml"
        # If the combined calibration was not generated with the images
        # taken at the beginning of the script, the verification
        # pipetask will use the calibrations provided as input
        # collections in the configuration file.
        if job_id_calib is None:
            input_col_verify_flat_string = (
                f"-i {self.config.input_collections_verify_flat}"
            )
        else:
            input_col_verify_flat_string = (
                f"-i u/ocps/{job_id_calib},"
                f"{self.config.input_collections_verify_flat}"
            )
        config_string = (
            f"-j {self.config.n_processes} "
            f"{input_col_verify_flat_string} "
            "--register-dataset-types "
        )
        exposure_ids = self.exposure_ids["FLAT"]

        return pipe_yaml, config_string, exposure_ids

    async def verify_calib(self, image_type, job_id_calib):
        """Verify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image type.

        jod_id_calib : `str`
            Job ID returned by OCPS during calibration generation
            pipetask call. If `None`, the calibrations will be sought
            at the input collections.

        Notes
        -----
        The verification step runs tests in `cp_verify`
        that check the metrics in DMTN-101.

        Suported calibrations: see `self.pipetask_parameters_verification`.
        """

        if image_type in self.pipetask_parameters_verification:
            (
                pipe_yaml,
                config_string,
                exposure_ids,
            ) = self.pipetask_parameters_verification[image_type](job_id_calib)
        else:
            self.log.error(
                f"Verification is not yet supported in this script for {image_type}. "
                f"Valid options: {self.pipetask_parameters_verification.keys()}"
            )

        # Use the camera-agnostic yaml file if the camera-specific
        # file does not exist.
        cp_verify_dir = getPackageDir("cp_verify")
        pipeline_yaml_file = os.path.join(
            cp_verify_dir, "pipelines", self.pipeline_instrument, pipe_yaml
        )
        file_exists = os.path.exists(pipeline_yaml_file)
        if file_exists:
            pipeline_yaml_file = (
                f"${{CP_VERIFY_DIR}}/pipelines/{self.pipeline_instrument}/{pipe_yaml}"
            )
        else:
            pipeline_yaml_file = f"${{CP_VERIFY_DIR}}/pipelines/{pipe_yaml}"

        # Verify the combined calibration
        exposure_id_string = (
            str(exposure_ids) if len(exposure_ids) > 1 else f"({exposure_ids[0]})"
        )
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False,
            pipeline=f"{pipeline_yaml_file}",
            version="",
            config=f"{config_string}",
            data_query=f"instrument='{self.instrument_name}' AND"
            f" detector IN {self.detectors_string} AND exposure IN {exposure_id_string}",
        )
        self.log.debug(
            f"Received acknowledgement of ocps command for {image_type} verification."
        )

        job_id_verify = json.loads(ack.result)["job_id"]

        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug(
            f"Received command completion acknowledgement from ocps ({image_type})"
        )

        while True:
            msg = await self.ocps.evt_job_result.next(
                flush=False, timeout=self.config.oods_timeout
            )
            response = json.loads(msg.result)
            if response["jobId"] == job_id_verify:
                break

        self.log.info(f"Final status from {image_type} verification: {response}")

        return response

    async def check_verification_stats(
        self, image_type, job_id_verify, job_id_calib=None
    ):
        """Check verification statistics.

        Parameters
        ----------
        image_type:
            Image or calibration type.

        jod_id_calib : `str`, optional
            Job ID returned by OCPS during previous calibration
            generation pipetask call.

        job_id_verify : `str`
            Job ID returned by OCPS during previous calibration
            verification pipetask call.

        Returns
        -------
        report_check_verify_stats : `dict`
            Dictionary with results:

        certify_calib : `bool`
            Booolean indicating if the calibration should be certified
            or not.

        num_stat_errors : `dict`[`str`][`str`] or `None`
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.

        failure_thresholds : `dict`[`str`][`int`] or `None`
            Dictionary reporting the different thresholds used to decide
            whether a calibration should be certified or not (see `Notes`
            below). If there are not any tests that failed,
            `None` will be returned.

        verify_stats : `dict`
            Statistics from cp_verify.

        Notes
        -----
        When `generate_calibrations=False`, verification will be performed
        using the combined calibrations in
        `self.config.input_collections_verify_bias`,
        `self.config.input_collections_verify_dark`, and/or
        `self.config.input_collections_verify_bias`, and this script won't
        have generated any combined calibrations from the images taken.
        Therefore, `job_id_calib` can be `None`.

        Suported calibrations: see `self.pipetask_parameters_verification`.
        """
        if image_type == "BIAS":
            verify_stats_string = "verifyBiasStats"
            max_number_failures_per_detector_per_test = (
                self.config.number_verification_tests_threshold_bias
            )
        elif image_type == "DARK":
            verify_stats_string = "verifyDarkStats"
            max_number_failures_per_detector_per_test = (
                self.config.number_verification_tests_threshold_dark
            )
        elif image_type == "FLAT":
            verify_stats_string = "verifyFlatStats"
            max_number_failures_per_detector_per_test = (
                self.config.number_verification_tests_threshold_flat
            )
        else:
            self.log.error(
                f"Verification is not currently implemented for {image_type}."
            )

        # Collection name containing the verification outputs.
        verify_collection = f"u/ocps/{job_id_verify}"
        if job_id_calib:
            # Collection that the calibration was constructed in.
            gen_collection = f"u/ocps/{job_id_calib}"
            collections_butler = [verify_collection, gen_collection]
        else:
            collections_butler = [verify_collection]
        butler = dafButler.Butler(self.config.repo, collections=collections_butler)
        # verify_stats is a dictionary with the verification
        # tests that failed, if any. See `cp_verify`.
        verify_stats = butler.get(verify_stats_string, instrument=self.instrument_name)

        if verify_stats["SUCCESS"] is False:
            (
                certify_calib,
                num_stat_errors,
                failure_thresholds,
            ) = await self.count_failed_verification_tests(
                verify_stats, max_number_failures_per_detector_per_test
            )
        else:
            # Nothing failed
            certify_calib, num_stat_errors, failure_thresholds, verify_stats = (
                True,
                None,
                None,
                verify_stats,
            )

        report_check_verify_stats = {
            "CERTIFY_CALIB": certify_calib,
            "NUM_STAT_ERRORS": num_stat_errors,
            "FAILURE_THRESHOLDS": failure_thresholds,
            "VERIFY_STATS": verify_stats,
        }

        return report_check_verify_stats

    async def count_failed_verification_tests(
        self, verify_stats, max_number_failures_per_detector_per_test
    ):
        """Count number of tests that failed cp_verify.

        Parameters
        ----------
        verify_stats : `dict`
            Statistics from cp_verify.

        max_number_failures_per_detector_per_test : `int`
            Minimum number of verification tests per detector per
            exposure per test type that should pass to certify the
            combined calibration.

        Returns
        -------
        certify_calib : `bool`
            Boolean assessing whether the calibration should be certified.

        total_counter_failed_tests : `dict`[`str`][`str`] or `None`.
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.

        thresholds : `dict`[`str`][`int`] or `None`
            Dictionary reporting the different thresholds used to decide
            whether a calibration should be certified or not (see `Notes`
            below). If there are not any tests that failed,
            `None` will be returned.

        Notes
        -----
        For at least one type of test, if the majority of tests fail in
        the majority of detectors and the majority of exposures,
        then don't certify the calibration.

        Suported calibrations: see `self.pipetask_parameters_verification`.
        """
        certify_calib = True

        # Thresholds
        # Main key of verify_stats is exposure IDs
        max_number_failed_exposures = int(len(verify_stats) / 2) + 1  # majority of exps

        max_number_failed_detectors = (
            int(self.n_detectors / 2) + 1
        )  # majority of detectors

        # Define failure threshold per exposure
        failure_threshold_exposure = (
            max_number_failures_per_detector_per_test * max_number_failed_detectors
        )

        # Count the number of failures per test per exposure.
        total_counter_failed_tests = {}
        for exposure in [key for key in verify_stats if key != "SUCCESS"]:
            if "FAILURES" in verify_stats[exposure]:
                # Gather the names of the types of tests that failed.
                # 'stg' is of the form e.g., 'R22_S21 C17 NOISE' or
                # 'R22_S22 SCATTER', so we retreive the name of the test from
                # the last element after splitting it.
                fail_count = [
                    stg.split(" ")[-1] for stg in verify_stats[exposure]["FAILURES"]
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
            return certify_calib, None, None

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
        if failed_exposures_counter >= max_number_failed_exposures:
            certify_calib = False

        # Return a dictionary with the thresholds to report
        # them if verification fails.
        thresholds = {
            "MAX_FAILURES_PER_DETECTOR_PER_TEST_TYPE_THRESHOLD": max_number_failures_per_detector_per_test,
            "MAX_FAILED_DETECTORS_THRESHOLD": max_number_failed_detectors,
            "MAX_FAILED_TESTS_PER_EXPOSURE_THRESHOLD": failure_threshold_exposure,
            "MAX_FAILED_EXPOSURES_THRESHOLD": max_number_failed_exposures,
            "FINAL_NUMBER_OF_FAILED_EXPOSURES": failed_exposures_counter,
        }

        return certify_calib, total_counter_failed_tests, thresholds

    async def build_verification_report_summary(self, report_check_verify_stats):
        """Helper function to print verification results.

        Parameters
        ----------
        report_check_verify_stats : `dict`
            Dictionary with verification results:

        certify_calib : `bool`
            Booolean indicating if the calibration should be certified
            or not.

        num_stat_errors : `dict`[`str`][`str`] or `None`
            Dictionary with the total number of tests failed per exposure and
            per cp_verify test type. If there are not any tests that failed,
            `None` will be returned.

        failure_thresholds : `dict`[`str`][`int`] or `None`
            Dictionary reporting the different thresholds used to decide
            whether a calibration should be certified or not (see `Notes`
            below). If there are not any tests that failed,
            `None` will be returned.

        verify_stats : `dict`
            Statistics from cp_verify.

        Returns
        -------
        final_report_string : `str`
            String with full report.
        """

        verify_report = report_check_verify_stats["NUM_STAT_ERRORS"]
        thresholds_report = report_check_verify_stats["FAILURE_THRESHOLDS"]
        verify_stats = report_check_verify_stats["VERIFY_STATS"]

        final_report_string = ""
        # List exposure IDs that have tests that failed
        final_report_string += "Exposures with verification tests that failed:\n"
        for exposure in verify_report:
            final_report_string += f"{exposure}  "

        # verify_report
        final_report_string += "\n Number of tests that failed per test type:\n"
        for exposure in verify_report:
            final_report_string += f"\t Exposure ID: {exposure}\n"
            for test_type in verify_report[exposure]:
                final_report_string += (
                    f"\t {test_type}: {verify_report[exposure][test_type]}\n"
                )

        # verify_stats
        final_report_string += "Test types that failed verification per exposure,\n"
        final_report_string += "detector, and amplifier:\n"

        for exposure in [key for key in verify_stats if key != "SUCCESS"]:
            final_report_string += f"\t Exposure ID: {exposure}\n"
            if "FAILURES" in verify_stats[exposure]:
                # det name | amp | test type
                for info in verify_stats[exposure]["FAILURES"]:
                    final_report_string += f"\t \t {info}\n"
            else:
                final_report_string += (
                    "No failures in 'verify_stats' for this exposure. \n"
                )

        # thresholds_report
        final_report_string += "Threshold values:\n"
        final_report_string += (
            "\t Acceptable maximum number of failures per detector per test type: "
        )
        final_report_string += f"{thresholds_report['MAX_FAILURES_PER_DETECTOR_PER_TEST_TYPE_THRESHOLD']}\n"

        final_report_string += (
            "\t This value is controlled by the configuration parameter: "
        )
        final_report_string += "'number_verification_tests_threshold_<IMGTYPE>'\n"

        final_report_string += "\t Acceptable maximum number of failed detectors: "
        final_report_string += (
            f"{thresholds_report['MAX_FAILED_DETECTORS_THRESHOLD']}\n"
        )

        final_report_string += (
            "\t Acceptable maximum number of failed tests per exposure: "
        )
        final_report_string += (
            f"{thresholds_report['MAX_FAILED_TESTS_PER_EXPOSURE_THRESHOLD']}\n"
        )

        final_report_string += "\t Acceptable maximum number of failed exposures: "
        final_report_string += (
            f"{thresholds_report['MAX_FAILED_EXPOSURES_THRESHOLD']}\n"
        )
        final_report_string += "\t Final number of exposures that failed verification: "
        final_report_string += (
            f"{thresholds_report['FINAL_NUMBER_OF_FAILED_EXPOSURES']}\n"
        )

        final_report_string += (
            "Verification failure criterium: if, for at least une type of test,\n"
        )
        final_report_string += (
            "the majority of tests fail in the majority of detectors and the\n"
        )
        final_report_string += (
            "the majority of exposures, verification will fail and the calibration\n"
        )
        final_report_string += "will not be certified. "

        final_report_string += (
            "In terms of the threshold values, this amounts for the condition that\n"
        )
        final_report_string += (
            "the final number of exposures that failed verification is greater than\n"
        )
        final_report_string += (
            "or equal to the acceptable maximum number of failed exposures. \n"
        )

        return final_report_string

    async def certify_calib(self, image_type, job_id_calib):
        """Certify the calibration.

        Parameters
        ----------
        image_type : `str`
            Image or calibration type.

        jod_id_calib : `str`
            Job ID returned by OCPS during previous calibration
            generation pipetask call.

        Raises
        ------
            RuntimeError : Error in running the butler certification command.

        Notes
        -----
        The calibration will certified for use with a timespan that indicates
        its validity range.

        Suported calibrations: see `self.supported_calibrations_certification`.
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
            f"--end-date {self.config.certify_calib_end_date} {image_type.lower()}"
        )
        self.log.info(cmd)

        process = await asyncio.create_subprocess_shell(cmd)
        stdout, stderr = await process.communicate()
        self.log.debug(f"Process returned: {process.returncode}")

        if process.returncode != 0:
            self.log.debug(stdout)
            self.log.error(stderr)

    async def analyze_report_check_verify_stats(
        self, im_type, report_check_verify_stats, job_id_verify, job_id_calib
    ):
        """Report the results from `check_verification_stats`

        Parameters
        ----------
        im_type : `str`
            Image or calibration type.

        report_check_verify_stats : `dict`
            Dictionary returned by `check_verification_stats`.

        job_id_verify : `str`
            Job ID returned by OCPS during previous calibration
            verification pipetask call.

        job_id_calib : `str`
            Job ID returned by OCPS during previous calibration
            generation pipetask call. If "generate_calibrations"
            is False, this variable is "None".

        Notes
        -----
        Suported calibrations: see `self.pipetask_parameters_verification`.
        """
        if job_id_calib:
            gen_collection = f"u/ocps/{job_id_calib}"
        else:
            gen_collection = (
                f"None. 'generate_calibrations' is {self.config.generate_calibrations}."
            )
        verify_collection = f"u/ocps/{job_id_verify}"

        verify_tests_pass = report_check_verify_stats["CERTIFY_CALIB"]

        if verify_tests_pass and report_check_verify_stats["NUM_STAT_ERRORS"] is None:
            self.log.info(
                f"{im_type} calibration passed verification criteria "
                f"and will be certified. \n Generation collection: {gen_collection} \n"
                f"Verification collection: {verify_collection}"
            )
        elif (
            verify_tests_pass
            and report_check_verify_stats["NUM_STAT_ERRORS"] is not None
        ):
            self.log.warning(
                f"{im_type} calibration passed the overall verification "
                " criteria and will be certified, but the are tests that did not pass: "
            )
            final_report_string = await self.build_verification_report_summary(
                report_check_verify_stats
            )
            self.log.warning(
                final_report_string + f"\n Generation collection: "
                f"{gen_collection} \n Verification collection: "
                f"{verify_collection}"
            )
        else:
            final_report_string = await self.build_verification_report_summary(
                report_check_verify_stats
            )
            self.log.warning(
                final_report_string + f"\n Generation collection: "
                f"{gen_collection} \n Verification "
                f"collection: {verify_collection}"
            )
            self.log.warning(
                f"{im_type} calibration failed verification and will not be certified."
            )

    async def report_gains_from_flat_pairs(self, job_id_calib):
        """Print gains estimated form flat pairs.

        Parameters
        ----------
        jod_id_calib : `str`
            Job ID returned by the OCPS after running the "GAIN" or
            "PTC" pipetasks

        Notes
        -----
        The "PTC" and "GAIN" tasks are defined by the "cp_pipe" pipelines
        "cpPtc.yaml" and "cpPtc.yaml#genGainsFromFlatPairs", respectively.
        """
        gen_collection = f"u/ocps/{job_id_calib}"
        butler = dafButler.Butler(self.config.repo, collections=[gen_collection])

        final_report_string = "Gains estimated from flats pairs: \n "

        detector_ids = np.arange(0, self.n_detectors)
        for exp_id in self.exposure_ids["FLAT"]:
            final_report_string += f"{exp_id}: \n"
            for det_id in detector_ids:
                final_report_string += f"\t Detector {det_id}: \n"
                try:
                    cp_ptc_extract = butler.get(
                        "cpPtcExtract",
                        instrument=self.instrument_name,
                        detector=det_id,
                        exposure=exp_id,
                    )
                    for amp_name in cp_ptc_extract.gain:
                        final_report_string += (
                            f"\t {amp_name}: {cp_ptc_extract.gain[amp_name]}\n"
                        )
                except RuntimeError:
                    continue
        self.log.info(final_report_string)

    async def run_block(self):
        # Check that the camera is enabled
        await self.camera.assert_all_enabled(
            "All camera components need to be enabled to run this script."
        )

        # Check that the OCPS is enabled
        await self.ocps_group.assert_all_enabled(
            "All OCPS components need to be enabled to run this script."
        )

        await self.checkpoint("Setup instrument.")
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

        # Basic sets of calibrations first : biases, darks, and flats.
        # After the loop is done, do defects and PTC.
        for im_type in image_types:

            # 1. Take images with the instrument, only for "BIAS,
            # "DARK", or "FLAT".
            if im_type == "BIAS":
                await self.checkpoint(f"Taking {self.config.n_bias} biases.")
            elif im_type == "DARK":
                await self.checkpoint(f"Taking {self.config.n_dark} darks.")
            elif im_type == "FLAT":
                await self.checkpoint(f"Taking {self.config.n_flat} flats.")

            # TODO: Before taking flats with LATISS (and also
            #  with LSSTComCam), check that the telescope is in
            #  position to do so. See DM-31496, DM-31497.
            exposure_ids_list = await self.take_images(im_type)

            # Discard the first N exposures taken (DM-36422)
            n_discard = self.n_images_discard[im_type]
            self.exposure_ids[im_type] = exposure_ids_list[n_discard:]

            # Image IDs
            await self.checkpoint(
                f"Images taken: {self.exposure_ids[im_type]}; type: {im_type}"
            )

            # Create a task that processes calibration and verification
            task = asyncio.create_task(self.process_images(im_type))
            self.background_tasks.append(task)

        # After taking the basic images (biases, darks, and flats) do
        # defects and PTC if requested.
        calib_types = []
        if mode == "BIAS_DARK_FLAT":
            if self.config.do_defects:
                calib_types.append("DEFECTS")
            if self.config.do_ptc:
                calib_types.append("PTC")
            if self.config.do_gain_from_flat_pairs:
                calib_types.append("GAIN")

        # The 'gainFromFlatPairs' ("GAIN") pipeline is a subset of
        # the 'cpPtc' pipeline ("PTC")
        if "PTC" in calib_types and "GAIN" in calib_types:
            calib_types.remove("GAIN")

        if len(calib_types):
            for calib_type in calib_types:
                task = asyncio.create_task(self.process_calibration(calib_type))
                self.background_tasks.append(task)

        await self.checkpoint("Data-taking part completed.")

        await self.wait_for_background_tasks()

    async def process_images(self, im_type):
        """
        Generate and optionally verify and certify calibrations for a
        given image type.

        Parameters
        ----------
        im_type : `str`
            The type of image or calibration to process. One of
            ["BIAS", "DARK", "FLAT"].

        Raises
        ------
        Exception
            If an error occurs during verification, it is logged and
            ignored.

        Notes
        -----
        - If `generate_calibrations` is set to `True`, the method
          will generate combined calibrations using the
          `call_pipetask` method.
        - If `do_verify` is `True`, the method will initiate
          verification of the generated calibrations.
        - If `do_verify` is `False` and calibrations are generated,
          the calibration will be automatically certified without
          verification.
        - If an error occurs during verification, it is logged and
          ignored.
        """

        if self.config.generate_calibrations:
            self.log.info(
                "Generating calibration from the images taken "
                "as part of this script."
            )
            response_ocps_calib_pipetask = await self.call_pipetask(im_type)
            job_id_calib = response_ocps_calib_pipetask["jobId"]
        else:
            self.log.info(
                f"A combined {im_type} will not be generated from the "
                "images taken as part of this script. Any needed input "
                "calibrations by the verification pipetasks will be "
                "sought in their input calibrations."
            )
            job_id_calib = None

        if self.config.do_verify:
            try:
                await self.process_verification(im_type, job_id_calib)
            except Exception:
                self.log.exception("Error in do_verify. Ignoring...")
        else:
            if self.config.generate_calibrations:
                self.log.info(
                    "'do_verify' is set to 'False' and "
                    "'generate_calibrations' to 'True'. "
                    f"{im_type} will be automatically certified."
                )

                await self.certify_calib(im_type, job_id_calib)

    async def process_verification(self, im_type, job_id_calib):
        """
        Verify and certify the generated calibration for a given
        image type.

        Parameters
        ----------
        im_type : `str`
            The type of image or calibration to verify. One of
            ["BIAS", "DARK", "FLAT"].

        job_id_calib : `str` or `None`
            The job ID returned by OCPS during the calibration
            generation pipetask call.
            If `None`, the verification will use reference
            calibrations from input collections.

        Returns
        -------
        report_check_verify_stats : `dict`
            Dictionary containing the results of the verification
            checks, including whether the calibration should be
            certified, any statistical errors, failure thresholds,
            and the raw verification statistics.

        Raises
        ------
        Exception
            Logs and handles any exceptions that occur during the
            verification process.

        Notes
        -----
        - Verification involves running the `verify_calib` method
          to execute the verification pipetask.
        - The method analyzes verification statistics to determine
          if the calibration meets the certification criteria.
        """
        try:
            self.log.info(f"Starting verification for {im_type}.")

            response_ocps_verify_pipetask = await self.verify_calib(
                im_type, job_id_calib
            )
            # Check that the task running cp_verify
            # did not fail.
            job_id_verify = response_ocps_verify_pipetask["jobId"]

            report_check_verify_stats = await self.check_verification_stats(
                im_type, job_id_verify, job_id_calib
            )
            # Inform the user about the results from
            # running cp_verify.
            # TODO: If verification failed, issue an
            #  alarm in the watcher: DM-33898.
            await self.analyze_report_check_verify_stats(
                im_type,
                report_check_verify_stats,
                job_id_verify,
                job_id_calib,
            )

            if job_id_calib is not None and report_check_verify_stats["CERTIFY_CALIB"]:
                await self.certify_calib(im_type, job_id_calib)

            return report_check_verify_stats
            # Note: Since we are not generating calibrations, we don't certify
        except Exception as e:
            self.log.exception(f"Error in processing verification for {im_type}: {e}")

    async def process_calibration(self, calib_type):
        """
        Generate and certify a specific type of calibration.

        This method handles the generation of a specific calibration
        type using the `call_pipetask` method. After generating the
        calibration, it automatically certifies the calibration unless
        the calibration type is "GAIN", which does not require
        certification. Additionally, it reports the estimated gains
        from flat pairs for applicable calibration types.

        Parameters
        ----------
        calib_type : `str`
            The type of calibration to process. Supported types are:
            - "DEFECTS"
            - "PTC"
            - "GAIN"

        Raises
        ------
        Exception
            If an error occurs during the calibration generation or
            certification process.

        Notes
        -----
        - The "GAIN" calibration type does not require certification.
        - Gain estimation from flat pairs is performed for "GAIN" and
         "PTC" calibration types.
        - Verification for calibrations is not implemented in this
          method and thus not required.
        """
        try:
            self.log.info(f"Starting calibration processing for {calib_type}.")
            response_ocps_calib_pipetask = await self.call_pipetask(calib_type)
            job_id_calib = response_ocps_calib_pipetask["jobId"]
            # Certify the calibrations in self.config.calib_collection
            # The quick gain estimation does not need to be certified.
            self.log.info(
                f"Verification for {calib_type} is not implemented yet "
                f"in this script. {calib_type} will be automatically certified."
            )
            if calib_type != "GAIN":
                await self.certify_calib(calib_type, job_id_calib)

            self.log.info(f"{calib_type} generation job ID: {job_id_calib}")

            # Report the estimated gain from each pair of flats
            if calib_type in ["GAIN", "PTC"]:
                await self.report_gains_from_flat_pairs(job_id_calib)
        except Exception as e:
            self.log.exception(f"Error processing {calib_type}: {e}")

    async def wait_for_background_tasks(self):
        """
        Await the completion of all background calibration and
        verification tasks.

        This method waits for all background tasks (calibration and
        verification processes) to complete within a specified
        timeout. If the tasks do not complete within the timeout
        period, it attempts to cancel any remaining unfinished tasks.

        Raises
        ------
        asyncio.TimeoutError
            If the background tasks do not complete within the
            allotted timeout.
        Exception
            Logs and handles any other exceptions that occur while
            waiting for tasks.

        Notes
        -----
        - The timeout is calculated based on the
          `background_task_timeout` configuration parameter multiplied
           by the number of background tasks.
        - Upon a timeout, the method logs a warning and cancels any
          tasks that are still pending.
        - After handling timeouts or exceptions, the list of
          background tasks is cleared.
        """
        self.log.info("Waiting for background tasks to complete.")
        try:
            # Note that when aysncio.wait_for times out, it cancels the task
            # it's waiting on. If the task being waited on is an asyncio.gather
            # instance, it propagates the cancellation to all the tasks it has
            # gathered.
            await asyncio.wait_for(
                asyncio.gather(*self.background_tasks, return_exceptions=True),
                timeout=self.config.background_task_timeout
                * len(self.background_tasks),
            )
            self.log.info("All background tasks have completed.")
        except asyncio.TimeoutError:
            self.log.warning("Background tasks did not complete before timeout.")
            for task in self.background_tasks:
                # all tasks should be done/cancelled at this point
                if not task.done():
                    # this code should never be reached.
                    self.log.warning(f"Cancelling task {task}")
                    task.cancel()
        except Exception as e:
            self.log.exception(f"Error in background tasks: {e}")
        finally:
            self.background_tasks = []

    @staticmethod
    def get_exposure_id(obsid):
        """Parse obsid into an exposure id.
        Convert string in the format ??_?_YYYYMMDD_012345 into an integer like
        YYYYMMDD12345.

        Parameters
        ----------
        obsid : `str`
            Observation id in the format ??_?_YYYYMMDD_012345, e.g.,
            AT_O_20220406_000007.

        Returns
        -------
        int
            Exposure id in the format YYYYMMDD12345, e.g., 2022040600007.
        """
        _, _, i_prefix, i_suffix = obsid.split("_")

        return int((i_prefix + i_suffix[1:]))

    def get_detectors_string(self, detector_array):
        """Get a detector string from a detector array.
        Convert a detector array of the form [0, 1, 2, ...] into a
        string of the form "(0, 1, 2, ...)" to be used by pipetasks.

        Parameters
        ----------
        detector_array : `array`
            Array with the detector IDs

        Returns
        -------
        detectors_string : `str`
            Detector IDs list in the form "(0, 1, 2..)"
        """

        if len(detector_array):
            d = "("
            for x in detector_array:
                d += f"{x},"
            detectors_string = d[:-1] + ")"
        else:
            # Default value is an empty array: use all detectors.
            n_det = self.n_detectors - 1
            detectors_string = f"(0..{n_det})"

        return detectors_string
