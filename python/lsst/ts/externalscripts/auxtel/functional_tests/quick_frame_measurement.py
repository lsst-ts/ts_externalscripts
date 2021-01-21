# This file is part of ts_externalcripts.
#
# Developed for the Rubin Observatory Telescope and Site System.
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

__all__ = ["QuickFrameMeasurement"]

import asyncio
import collections.abc

import lsst.daf.persistence as dafPersist
from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
import numpy as np
import yaml
from astropy import time as astropytime
from lsst.geom import PointD
from lsst.ts import salobj
from lsst.ts.observatory.control.auxtel import ATCS, LATISS
from lsst.ts.observatory.control.constants import latiss_constants
from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
from lsst.ts.observing.utilities.auxtel.latiss.utils import (
    calculate_xy_offsets,
    parse_obs_id,
)
from lsst.ts.standardscripts.utils import format_as_list

STD_TIMEOUT = 10  # seconds


class QuickFrameMeasurement(salobj.BaseScript):
    """
    Test .

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    An (optional) checkpoint is available to verify the calculated
    telescope offset after each iteration of the acquisition.

    **Details**

    This script is used to put the brightest target in a field on a specific
    pixel.

    """

    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, silent=False):

        super().__init__(
            index=index, descr="Test QuickFrameMeasurementTask.",
        )

        # instantiate the quick measurement class
        qm_config = QuickFrameMeasurementTask.ConfigClass()
        self.qm = QuickFrameMeasurementTask(config=qm_config)

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/QuickFrameMeasurement.yaml
            title: LatissRunIsr v1
            description: Configuration for LatissCWFSAlign Script.
            type: object
            properties:
              dataPath:
                description: Path to the butler data repository.
                type: string
                default: /project/shared/auxTel/
              exp_id:
                description: Visit id of the image to process.
                type: integer
            required:
              - exp_id
            additionalProperties: false
        """

        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        self.config = config

    def set_metadata(self, metadata):
        metadata.duration = 60.0

    async def run_qm(self, data_id):

        exp = await get_image(
            data_id,
            datapath=self.config.dataPath,
            timeout=STD_TIMEOUT,
            runBestEffortIsr=True,
        )
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()

        # Find brightest star
        try:
            result = await loop.run_in_executor(executor, self.qm.run, exp)
        except RuntimeError:
            # FIXME: Patrick - deal with a failure to find the source here
            pass  # and remove this
            # Note that the source finding should be made a function

        current_position = PointD(
            result.brightestObjCentroid[0], result.brightestObjCentroid[1]
        )

        self.log.debug(f"Current brightest target position is {current_position}")

    async def run(self):

        self.log.debug(f"Running QuickFrameMeasurementTask in {self.config.exp_id}")
        await self.run_qm(self.config.exp_id)
