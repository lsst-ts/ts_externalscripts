# This file is part of ts_externalscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["LatissRAAlign"]

import asyncio
import time
import types
import typing

import yaml
from astropy.table import QTable
from lsst.daf.butler import Butler

from .latiss_base_align import LatissAlignResults, LatissBaseAlign


class LatissRAAlign(LatissBaseAlign):
    """Perform an optical alignment procedure of Auxiliary Telescope with the
    LATISS instrument.

    Instead of estimating the wavefront error in-process (as
    `LatissWEPAlign` and `LatissCWFSAlign` do), this script reads the
    already-computed result from the Rapid Analysis (RA) service, which
    watches for consecutive LATISS intra/extra focal exposures and
    automatically performs wavefront estimation, publishing the results to
    the ``LATISS/quickLook`` Butler collection.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    # Name of the Butler dataset type that Rapid Analysis publishes the
    # Zernike coefficients under.
    ZERNIKE_DATASET_TYPE = "zernikes"

    def __init__(self, index: int = 1, remotes: bool = True) -> None:
        super().__init__(
            index=index,
            remotes=remotes,
            descr="Perform optical alignment procedure of the Rubin Auxiliary "
            "Telescope with LATISS using wavefront estimation results "
            "produced by the Rapid Analysis service.",
        )

        self.butler = None

        self.log.info(
            "LATISS Rapid Analysis alignment initialized. Perform optical "
            "alignment procedure of the Rubin Auxiliary Telescope with "
            "LATISS using Zernike coefficients computed by Rapid Analysis."
        )

    @classmethod
    def get_schema(cls) -> typing.Dict[str, typing.Any]:
        schema = super().get_schema()

        additional_properties_yaml = """
            ra_timeout:
              description: >-
                  Maximum time (sec) to wait for Rapid Analysis to publish the
                  Zernike coefficients for an intra/extra focal pair.
              type: number
              default: 120.
            ra_poll_interval:
              description: >-
                  Interval (sec) between polls of the Butler while waiting
                  for Rapid Analysis to publish results.
              type: number
              default: 5.
        """
        schema["properties"].update(yaml.safe_load(additional_properties_yaml))

        return schema

    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await super().configure(config)

        if self.butler is None:
            self.butler = Butler("LATISS")

        self.ra_timeout = config.ra_timeout
        self.ra_poll_interval = config.ra_poll_interval

        self.ra_collections = ["LATISS/raw/all", "LATISS/quickLook"]

    async def run_align(self) -> LatissAlignResults:
        """Reads the Zernike coefficients computed by Rapid Analysis for the
        most recently acquired intra/extra focal pair.

        Returns
        -------
        results : `LatissAlignResults`
            A dataclass containing the results of the calculation.
        """
        zk_table = await self.get_zernikes_from_ra()
        zk_average_nm = zk_table[zk_table["label"] == "average"]

        # output from Rapid Analysis is in nm
        self.zern = [
            -zk_average_nm["Z8"][0].value,
            zk_average_nm["Z7"][0].value,
            zk_average_nm["Z4"][0].value,
        ]

        return self.calculate_results()

    async def get_zernikes_from_ra(self) -> QTable:
        """Poll the Butler for the Zernike coefficients Rapid Analysis
        computes for the current intra/extra focal pair.

        Returns
        -------
        zk_table : `astropy.table.QTable`
            Table of Zernike coefficients, as published by Rapid Analysis.

        Raises
        ------
        TimeoutError
            If no matching dataset appears within `ra_timeout` seconds.
        """
        where = (
            f"visit in ({self.intra_visit_id}, {self.extra_visit_id}) "
            "and instrument='LATISS'"
        )

        start_time = time.time()
        elapsed_time = 0.0
        datasets = []

        while elapsed_time < self.ra_timeout:
            try:
                datasets = self.butler.query_datasets(
                    self.ZERNIKE_DATASET_TYPE,
                    collections=self.ra_collections,
                    where=where,
                )
                if datasets:
                    break
            except Exception:
                self.log.exception(
                    f"Querying '{self.ZERNIKE_DATASET_TYPE}' failed; retrying."
                )

            await asyncio.sleep(self.ra_poll_interval)
            elapsed_time = time.time() - start_time

        if not datasets:
            raise TimeoutError(
                f"Timed out after {self.ra_timeout}s waiting for Rapid Analysis "
                f"to publish '{self.ZERNIKE_DATASET_TYPE}' for visits "
                f"{self.intra_visit_id}/{self.extra_visit_id}."
            )

        if len(datasets) > 1:
            self.log.warning(
                f"Found {len(datasets)} '{self.ZERNIKE_DATASET_TYPE}' datasets "
                f"for visits {self.intra_visit_id}/{self.extra_visit_id}; "
                "using the first."
            )

        return self.butler.get(
            self.ZERNIKE_DATASET_TYPE,
            dataId=datasets[0].dataId,
            collections=self.ra_collections,
        )
