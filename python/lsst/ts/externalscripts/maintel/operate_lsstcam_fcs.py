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

__all__ = ["OperateLSSTCamFCS"]

import abc
import asyncio

import numpy as np
import math
import yaml
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam


class OperateLSSTCamFCS(BaseBlockScript, metaclass=abc.ABCMeta):
    """Class to operate and test the filter change system for LSSTCam.

    Parameters
    ----------
        index : `int`
        SAL index of this script"""
    def __init__(self, index, descr):
        super().__init__(index=index, descr=descr)
        self._lsstcam = LSSTCam(domain=self.domain, log=self.log)
        self.instrument_setup_time = 30.0 #seconds to change filter

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
            filter_list:
                description: List of filters to exchange. Setting a single filter \
                with n_changes=1 will set a filter. Defaults to no filter in optical \
                path.
                type: list
                default: ["None"]
            n_changes:
                type: integer
                default: 1
                description: Number of filter changes to do.
            pause:
                type: integer
                default: 1
                description: time in seconds to pause between changes.
            seed:
                type: integer
                default 42
                description: random seed for shuffling order to set filters
        """
        schema_dict = yaml.safe_load(schema)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

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
                f"filter_list: {config.filter_list}, "
                f"n_changes: {config.n_changes}, "
                f"pause: {config.pause}, "
                f"seed: {config.seed}"
            )

            self.config = config

            await super().configure(config=config)

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""

        # Total duration calculation
        total_duration = (
            (self.instrument_setup_time*self.n_changes)  # time to change
            + (self.pause*self.n_changes)  # time paused
        )

        metadata.duration = total_duration
        metadata.instrument = "LSSTCam"

    async def assert_feasibility(self) -> None:
        """Verify that camera is in a feasible state to
        execute the script.
        """
        await self.camera.assert_all_enabled()

    async def _make_shuffle(self) -> None:
        """create a shuffled list of filters with length n_changes,
           containing"""
        n_changes = self.config.n_changes
        n_filters = len(self.config.filter_list)
        filters = self.config.filter_list
        self.filter_order = (filters*(math.floor(n_changes/n_filters))
                            + filters[:n_changes % n_filters])
        
        np.random.seed(self.config.seed)
        np.random.shuffle(self.filter_order)

    async def _set_filters(self) -> None:
        """main loop for setting filters"""
        for filter in self.filter_order:
            self.camera.setup_instrument(filter=filter)
            asyncio.sleep(self.config.pause)

    async def run_block(self):
        """Run the block to set filters with the FCS"""
        await self.assert_feasibility()
        await self._make_shuffle()
        await self._set_filters()