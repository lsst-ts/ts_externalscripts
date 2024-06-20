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

__all__ = ["MakeLatissCalibrations"]

import yaml
from lsst.ts.observatory.control import RemoteGroup
from lsst.ts.observatory.control.auxtel.latiss import LATISS

from ..base_make_calibrations import BaseMakeCalibrations


class MakeLatissCalibrations(BaseMakeCalibrations):
    """Class for taking images, constructing, verifying, and
    certifying combined calibrations with LATISS.

    This class takes bias, dark, and flat exposureswith Auxtel-LATISS,
    constructs a combined calibration for each image type by calling
    the appropriate pipetask via OCPS, and then verifies and certifies
    each combined calibration. It also optionally produces defects and
    Photon Transfer Curves.
    """

    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="Takes series of bias, darks and flat-field exposures with "
            "LATISS/AuxTel, and constructs combined calibrations, verify and "
            "certify the results.",
        )
        self._latiss = LATISS(domain=self.domain, log=self.log)
        self._ocps_group = RemoteGroup(
            domain=self.domain, components=["OCPS:1"], log=self.log
        )

    @property
    def camera(self):
        return self._latiss

    @property
    def ocps_group(self):
        """Access the Remote OCPS Groups in the constructor.

        The OCPS index will be 1 for LATISS: OCPS:1.
        """
        return self._ocps_group

    @property
    def ocps(self):
        return self.ocps_group.rem.ocps_1

    @property
    def instrument_name(self):
        """String with instrument name for pipeline task"""
        return "LATISS"

    @property
    def pipeline_instrument(self):
        """String with instrument name for pipeline yaml file"""
        return "LATISS"

    @property
    def detectors(self):
        """Array with detector IDs"""
        return [0]

    @property
    def n_detectors(self):
        """Number of detectors"""
        return 1

    @property
    def image_in_oods(self):
        """OODS imageInOODS event."""
        return self.camera.rem.atoods.evt_imageInOODS

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/externalscripts/"
            "auxtel/make_latiss_calibrations.py"
        )
        schema = f"""
        $schema: http://json-schema.org/draft-07/schema#
        $id: {url}{path}
        title: MakeLatissCalibrations v1
        description: Configuration for making a LATISS calibrations SAL Script.
        type: object
        properties:
            filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
            grating:
                description: Grating name; if omitted the grating is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
                default: null
            input_collections_bias:
                type: string
                descriptor: Additional comma-separated input collections to pass to the bias pipetask.
                default: "LATISS/calib"
            input_collections_verify_bias:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (bias) pipetask.
                default: "LATISS/calib"
            input_collections_dark:
                type: string
                descriptor: Additional comma-separarted input collections to pass to the dark pipetask.
                default: "LATISS/calib"
            input_collections_verify_dark:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (dark) pipetask.
                default: "LATISS/calib"
            input_collections_flat:
                type: string
                descriptor: Additional comma-separated input collections to pass to the flat pipetask.
                default: "LATISS/calib"
            input_collections_verify_flat:
                type: string
                descriptor: Additional comma-separated input collections to pass to \
                    the verify (flat) pipetask.
                default: "LATISS/calib"
            input_collections_defects:
                type: string
                descriptor: Additional comma-separated input collections to pass to the defects pipetask.
                default: "LATISS/calib"
            input_collections_ptc:
                type: string
                descriptor: Additional comma-separated input collections to pass to the \
                    Photon Transfer Curve pipetask.
                default: "LATISS/calib"
            calib_collection:
                type: string
                descriptor: Calibration collection where combined calibrations will be certified into.
                default: "LATISS/calib/daily"
            repo:
                type: string
                descriptor: Butler repository.
                default: "/repo/LATISS"
        additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema)
        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    def get_instrument_configuration(self):
        return dict(filter=self.config.filter, grating=self.config.grating)
