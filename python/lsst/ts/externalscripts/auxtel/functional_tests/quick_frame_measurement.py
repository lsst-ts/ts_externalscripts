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
import warnings
import yaml

import concurrent.futures

try:
    from lsst.rapid.analysis import BestEffortIsr
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.ts.observing.utilities.auxtel.latiss.utils import parse_obs_id
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image

except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

from lsst.geom import PointD
from lsst.ts import salobj

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

    def __init__(self, index, silent=False):

        super().__init__(
            index=index,
            descr="Test QuickFrameMeasurementTask.",
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
            description: Configuration for QuickFrameMeasurement Script.
            type: object
            properties:
              datapath:
                description: Path to the gen3 butler data repository.
                type: string
                default: /repo/LATISS/
              visit_id:
                description: Visit id of the image to process. Format is AT_O_YYYYMMDD_NNNNNN.
                type: string
            required:
              - visit_id
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

        # Instantiate BestEffortIsr
        self.best_effort_isr = self.get_best_effort_isr()

    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr(self.config.datapath)

    def set_metadata(self, metadata):
        metadata.duration = 60.0

    async def run_qm(self, visit_id):

        data_id = parse_obs_id(visit_id)

        exp = await get_image(
            data_id,
            self.best_effort_isr,
            timeout=STD_TIMEOUT,
        )
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()

        # Find brightest star
        result = await loop.run_in_executor(executor, self.qm.run, exp)

        if not result.success:
            raise RuntimeError("Centroid finding algorithm was unsuccessful.")

        current_position = PointD(
            result.brightestObjCentroid[0], result.brightestObjCentroid[1]
        )

        self.log.debug(f"Current brightest target position is {current_position}")

    async def run(self):

        self.log.debug(f"Running QuickFrameMeasurementTask in {self.config.visit_id}")
        await self.run_qm(self.config.visit_id)
