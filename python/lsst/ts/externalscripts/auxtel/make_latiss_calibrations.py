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

from lsst.ts.observatory.control.auxtel.latiss import LATISS
from ..base_make_calibrations import BaseMakeCalibrations


class MakeLatissCalibrations(BaseMakeCalibrations):
    """Class for taking images, constructing, verifying, and
       certifying master calibrations with LATISS.
    """

    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="This class takes biases, darks, and flats  with Auxtel-LATISS, "
                  "constructs a master calibration for each image type by calling "
                  "the appropriate pipetask via OCPS, and then veres and certifies "
                  "each master calibration. ",
        )
        self._latiss = LATISS(domain=self.domain, log=self.log)

    @property
    def camera(self):
        return self._latiss

    @property
    def instrument_name(self):
        """String with instrument name for pipeline task"""
        return "LATISS"

    @property
    def image_in_oods(self):
        """Archiver"""
        return self.camera.rem.atarchiver.evt_imageInOODS

    @classmethod
    def get_schema(cls):
        schema = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/python/lsst/ts/\
                externalscripts/auxtel/make_latiss_calibrations.py
        title: MakeLatissCalibrations v1
        description: Configuration for making a LATISS calibrations SAL Script.
        type: object
        properties:
            filter:
                description: Filter name or ID; if omitted the filter is not changed.
                anyOf:
                  - type: string
                  - type: integer
                    minimun: 1
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
            calib_collection:
                type: string
                descriptor: Calibration collection where master calibrations will be certified into.
                default: "LATISS/calib/daily"
            repo:
                type: string
                descriptor: Butler repository.
                default: "/repo/LATISS"
        additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema)
        schema_dict["properties"] = {}
        base_schema_dict = super(MakeLatissCalibrations, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    def get_instrument_configuration(self):
        return dict(filter=self.config.filter)
