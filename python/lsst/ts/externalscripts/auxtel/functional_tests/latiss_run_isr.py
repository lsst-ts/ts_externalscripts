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

__all__ = ["LatissRunIsr"]

import os
import time
import yaml
import asyncio
import warnings

import concurrent.futures

from pathlib import Path

import numpy as np
from astropy import time as astropytime

from lsst.ts import salobj

import lsst.daf.persistence as dafPersist

# Source detection libraries
from lsst.meas.algorithms.detection import SourceDetectionTask

import lsst.afw.table as afwTable

from lsst.ip.isr.isrTask import IsrTask

import copy  # used to support binning


class LatissRunIsr(salobj.BaseScript):
    """ Test run Isr in a set of images.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    None

    **Details**

    """

    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index=1):

        super().__init__(
            index=index, descr="Test Isr task in images.",
        )

        # butler data path.
        self.dataPath = "/project/shared/auxTel/"

        self.isr_config = IsrTask.ConfigClass()
        self.isr_config.doLinearize = False
        self.isr_config.doBias = True
        self.isr_config.doFlat = False
        self.isr_config.doDark = False
        self.isr_config.doFringe = False
        self.isr_config.doDefect = True
        self.isr_config.doSaturationInterpolation = False
        self.isr_config.doSaturation = False
        self.isr_config.doWrite = False

    def get_isr_exposure(self, exp_id):
        """Get ISR corrected exposure.

        Parameters
        ----------
        exp_id: `string`
             Exposure ID for butler image retrieval

        Returns
        -------
        ISR corrected exposure as an lsst.afw.image.exposure.exposure object
        """

        isrTask = IsrTask(config=self.isr_config)

        got_exposure = False

        ntries = 0

        data_ref = None
        while not got_exposure:
            butler = dafPersist.Butler(self.dataPath)
            try:
                data_ref = butler.dataRef("raw", **dict(expId=exp_id))
            except RuntimeError as e:
                self.log.warning(
                    f"Could not get intra focus image from butler. Waiting "
                    f"{self.data_pool_sleep}s and trying again."
                )
                time.sleep(self.data_pool_sleep)
                if ntries > 10:
                    raise e
                ntries += 1
            else:
                got_exposure = True

        if data_ref is not None:
            return isrTask.runDataRef(data_ref).exposure
        else:
            raise RuntimeError(f"No data ref for {exp_id}.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/LatissRunIsr.yaml
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

    async def run(self):

        self.log.debug(f"Processing visit_id {self.config.exp_id}")
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()

        await loop.run_in_executor(executor, self.get_isr_exposure, self.config.exp_id)
