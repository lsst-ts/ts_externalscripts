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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["TakeComCamGuiderImage"]

import yaml
from lsst.ts.observatory.control.maintel.comcam import ComCam
from lsst.ts.observatory.control.utils.roi_spec import ROISpec
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


class TakeComCamGuiderImage(BaseBlockScript):
    """Script to test taking data with ComCam with guider mode on.

    Parameters
    ----------
    index : `int`
        Index od Script SAL component.
    """

    def __init__(self, index):
        super().__init__(
            index=index, descr="Take data with comcam and handle guider mode."
        )

        self.comcam = None
        self.roi_spec = None
        self.exposure_time = 0.0
        self.note = None

    def set_metadata(self, metadata):
        metadata.duration = self.exposure_time

    async def configure(self, config):
        if self.comcam is None:
            self.comcam = ComCam(self.domain, log=self.log)
            await self.comcam.start_task

        self.roi_spec = ROISpec.parse_obj(config.roi_spec)
        self.exposure_time = config.exposure_time
        self.note = getattr(config, "note", None)

        await super().configure(config=config)

    @classmethod
    def get_schema(cls):
        schema_yaml = """
$schema: http://json-schema.org/draft-07/schema#
$id: https://github.com/lsst-ts/ts_externalscripts/maintel/take_comcam_guider_image.py
title: TakeComCamGuiderImage v1
description: Configuration for TakeComCamGuiderImage.
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
  exposure_time:
    type: number
    minimum: 1
    description: Exposure time in seconds.
  note:
    description: A descriptive note about the image being taken.
    type: string
  roi_spec:
    description: Definition of the ROI Specification.
    type: object
    additionalProperties: false
    required:
      - common
      - roi
    properties:
      common:
        description: Common properties to all ROIs.
        type: object
        additionalProperties: false
        required:
          - rows
          - cols
          - integration_time_millis
        properties:
          rows:
            description: Number of rows for each ROI.
            type: number
            minimum: 10
            maximum: 400
          cols:
            description: Number of columns for each ROI.
            type: number
            minimum: 10
            maximum: 400
          integration_time_millis:
            description: Guider exposure integration time in milliseconds.
            type: number
            minimum: 5
            maximum: 200
      roi:
        description: Definition of the ROIs regions.
        minProperties: 1
        additionalProperties: false
        patternProperties:
          "^[a-zA-Z0-9]+$":
            type: object
            additionalProperties: false
            required:
              - segment
              - start_row
              - start_col
            properties:
              segment:
                type: number
                description: Segment of the CCD where the center of the ROI is located.
              start_row:
                type: number
                description: The bottom-left row origin of the ROI.
              start_col:
                type: number
                description: The bottom-left column origin of the ROI.
additionalProperties: false
required:
  - roi_spec
  - exposure_time
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super(TakeComCamGuiderImage, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    async def run_block(self):

        note = self.note
        reason = self.reason
        program = self.program

        await self.comcam.init_guider(roi_spec=self.roi_spec)

        await self.comcam.take_engtest(
            n=1,
            exptime=self.exposure_time,
            reason=reason,
            program=program,
            group_id=self.group_id,
            note=note,
        )
