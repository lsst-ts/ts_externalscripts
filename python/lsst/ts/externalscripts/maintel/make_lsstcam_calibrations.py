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

__all__ = ["MakeLSSTCamCalibrations"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control import RemoteGroup
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

from ..base_make_calibrations import BaseMakeCalibrations


class MakeLSSTCamCalibrations(BaseMakeCalibrations):
    """Class for taking images, constructing, verifying, and
    certifying combined calibrations with LSSTCam.

    This class takes bias, darks, and flat exposures with LSSTCam,
    constructs a combined calibration for each image type by calling
    the appropiate pipetask via OCPS, and then verifies and certifies
    each combined calibration. It also optionally produces defects and
    Photon Transfer Curves.
    """

    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="Takes series of bias, darks and flat-field exposures"
            "with LSSTCam, and constructs combined "
            "calibrations, verify and certify the results.",
        )
        self._lsstcam = None
        self._ocps_group = None
        self.mtcs = None

    @property
    def camera(self):
        return self._lsstcam

    @property
    def ocps_group(self):
        """Access the Remote OCPS Groups in the constructor.

        The OCPS index will be 3 for LSSTCam: OCPS:3.
        """
        return self._ocps_group

    @property
    def ocps(self):
        return self.ocps_group.rem.ocps_3

    @property
    def instrument_name(self):
        """String with instrument name for pipeline task"""
        return "LSSTCam"

    @property
    def pipeline_instrument(self):
        """String with instrument name for pipeline yaml file"""
        return "LSSTCam"

    @property
    def detectors(self):
        """Array with detector IDs"""
        return self.config.detectors if self.config is not None else []

    @property
    def n_detectors(self):
        """Number of detectors"""
        return (
            len(self.config.detectors)
            if self.config is not None and self.config.detectors
            else 197
        )

    @property
    def image_in_oods(self):
        """OODS imageInOODS event."""
        return self.camera.rem.mtoods.evt_imageInOODS

    async def start_remotes(self):
        if self._lsstcam is None:
            self._lsstcam = LSSTCam(domain=self.domain, log=self.log)
            await self._lsstcam.start_task

        if self._ocps_group is None:
            self._ocps_group = RemoteGroup(
                domain=self.domain, components=["OCPS:3"], log=self.log
            )
            await self._ocps_group.start_task

        if not hasattr(self, "_mtcs") or self.mtcs is None:
            self.mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.Slew
            )
            await self.mtcs.start_task

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await super().configure(config)

        # Start remotes if not already started
        await self.start_remotes()

        # Handle ignore functionality
        if hasattr(self.config, "ignore") and self.config.ignore:
            self.mtcs.disable_checks_for_components(components=self.config.ignore)

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/externalscripts/"
            "/make_lsstcam_calibrations.py"
        )
        schema = f"""
        $schema: http://json-schema.org/draft-07/schema#
        $id: {url}/{path}
        title: MakeLSSTCamCalibrations v1
        description: Configuration for making a LSSTCam combined calibrations SAL Script.
        type: object
        properties:
            detectors:
                description: Detector IDs. If omitted, all 197 (wavefronts are 2, without guiders) \
                    LSSTCam detectors will be used.
                type: array
                items:
                  - type: integer
                minContains: 0
                maxContains: 204
                minItems: 0
                maxItems: 205
                uniqueItems: true
                default: []
            filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
            input_collections_bias:
                type: string
                descriptor: Additional comma-separated input collections to pass to the bias pipetask.
                default: "LSSTCam/calib"
            input_collections_verify_bias:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (bias) pipetask.
                default: "LSSTCam/calib"
            input_collections_dark:
                type: string
                descriptor: Additional comma-separarted input collections to pass to the dark pipetask.
                default: "LSSTCam/calib"
            input_collections_verify_dark:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (dark) pipetask.
                default: "LSSTCam/calib"
            input_collections_flat:
                type: string
                descriptor: Additional comma-separated input collections to pass to the flat pipetask.
                default: "LSSTCam/calib"
            input_collections_verify_flat:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (flat) pipetask.
                default: "LSSTCam/calib"
            input_collections_defects:
                type: string
                descriptor: Additional comma-separated input collections to pass to the defects pipetask.
                default: "LSSTCam/calib"
            input_collections_ptc:
                type: string
                descriptor: Additional comma-separated input collections to pass to the \
                    Photon Transfer Curve pipetask.
                default: "LSSTCam/calib"
            calib_collection:
                type: string
                descriptor: Calibration collection where combined calibrations will be certified into.
                default: "LSSTCam/calib/daily"
            repo:
                type: string
                descriptor: Butler repository.
                default: "/repo/LSSTCam/butler+sasquatch.yaml"
            ignore:
                description: >-
                  CSCs from the MTCS group to ignore in status check. Name must
                  match those in self._mtcs.components_attr, e.g.; mtmount, mtptg.
                type: array
                items:
                  type: string
        additionalProperties: false
        required:
            - script_mode
        """
        schema_dict = yaml.safe_load(schema)
        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    def get_instrument_configuration(self):
        return dict(filter=self.config.filter)

    async def assert_feasibility(self, image_type):
        """Ensure dome components are in the required state before flats."""
        if image_type != "FLAT":
            return None

        mtdometrajectory_ignored = not self.mtcs.check.mtdometrajectory
        mtdome_ignored = not self.mtcs.check.mtdome

        if not mtdometrajectory_ignored:
            dome_trajectory_evt = (
                await self.mtcs.rem.mtdometrajectory.evt_summaryState.aget(
                    timeout=self.mtcs.long_timeout
                )
            )
            dome_trajectory_summary_state = salobj.State(
                dome_trajectory_evt.summaryState
            )

            if dome_trajectory_summary_state != salobj.State.ENABLED:
                raise RuntimeError(
                    "MTDomeTrajectory must be ENABLED before taking flats to ensure "
                    "vignetting state is published. "
                    f"Current state {dome_trajectory_summary_state.name}."
                )

        if not mtdome_ignored:
            dome_evt = await self.mtcs.rem.mtdome.evt_summaryState.aget(
                timeout=self.mtcs.long_timeout
            )
            dome_summary_state = salobj.State(dome_evt.summaryState)

            acceptable_mtdome_state = {salobj.State.DISABLED, salobj.State.ENABLED}

            if dome_summary_state not in acceptable_mtdome_state:
                raise RuntimeError(
                    f"MTDome must be in {acceptable_mtdome_state} before taking flats, "
                    f"current state {dome_summary_state.name}."
                )
