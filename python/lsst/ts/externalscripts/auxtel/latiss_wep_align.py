# This file is part of ts_externalcripts
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

__all__ = ["LatissWEPAlign"]

import asyncio
import concurrent.futures
import functools
import time
import typing
import warnings

import numpy as np
import pandas
from lsst.afw.geom import SkyWcs
from lsst.afw.image import ExposureF
from lsst.pipe.base.struct import Struct

try:
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.utils import parse_visit_id
    from lsst.ts.wep.task.EstimateZernikesLatissTask import (
        EstimateZernikesLatissTask,
        EstimateZernikesLatissTaskConfig,
    )
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


from .latiss_base_align import LatissAlignResults, LatissBaseAlign


class LatissWEPAlign(LatissBaseAlign):
    """Perform an optical alignment procedure of Auxiliary Telescope with the
    LATISS instrument.

    Instead of using the Curvature Wavefront Sensing package directly
    (e.g. https://github.com/lsst-ts/cwfs like LatissCWFSAlign) this script
    uses the wavefront estimation pipeline task, which is the same code we will
    use for the Main Telescope.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index: int = 1, remotes: bool = True) -> None:
        super().__init__(
            index=index,
            remotes=remotes,
            descr="Perform optical alignment procedure of the Rubin Auxiliary "
            "Telescope with LATISS using the latest Wavefront Estimation "
            "Pipeline code. This is the same code that will be used for the "
            "MTAOS.",
        )

        self.log.info(
            "LATISS Wavefront Estimation Pipeline initialized. Perform optical "
            "alignment procedure of the Rubin Auxiliary Telescope with LATISS "
            "using the Wavefront Estimation Pipeline task."
        )

    async def run_align(self) -> LatissAlignResults:
        """Runs wavefront estimation pipeline.

        Returns
        -------
        results : `LatissAlignResults`
            A dataclass containing the results of the calculation.
        """

        loop = asyncio.get_running_loop()

        with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:

            self.log.debug(
                "Running wep with: "
                f"intra_visit_id={self.intra_visit_id}, "
                f"extra_visit_id={self.extra_visit_id}, "
                f"donut_diameter={2 * self.side}, "
                f"timeout_get_image={self.timeout_get_image}. "
            )

            (
                self.intra_result,
                self.extra_result,
                wep_results,
            ) = await loop.run_in_executor(
                pool,
                functools.partial(
                    run_wep,
                    self.intra_visit_id,
                    self.extra_visit_id,
                    2 * self.side,
                    self.timeout_get_image,
                ),
            )

            # output from wep are in microns, need to convert to nm.
            self.zern = [
                -wep_results.outputZernikesAvg[0][4] * 1e3,
                wep_results.outputZernikesAvg[0][3] * 1e3,
                wep_results.outputZernikesAvg[0][0] * 1e3,
            ]

        return self.calculate_results()


def run_wep(
    intra_visit_id: int,
    extra_visit_id: int,
    donut_diameter: int,
    timeout_get_image: float,
) -> typing.Tuple[Struct, Struct, Struct]:

    best_effort_isr = BestEffortIsr()

    exposure_intra = get_image(
        parse_visit_id(intra_visit_id),
        best_effort_isr,
        timeout=timeout_get_image,
    )
    exposure_extra = get_image(
        parse_visit_id(extra_visit_id),
        best_effort_isr,
        timeout=timeout_get_image,
    )

    quick_frame_measurement_config = QuickFrameMeasurementTask.ConfigClass()
    quick_frame_measurement_task = QuickFrameMeasurementTask(
        config=quick_frame_measurement_config
    )

    result_intra = quick_frame_measurement_task.run(
        exposure_intra, donutDiameter=donut_diameter
    )
    result_extra = quick_frame_measurement_task.run(
        exposure_extra, donutDiameter=donut_diameter
    )

    if not result_intra.success or not result_extra.success:
        raise RuntimeError(
            f"Centroid finding algorithm was unsuccessful. "
            f"Intra image ({exposure_intra}) success is {result_intra.success}. "
            f"Extra image ({exposure_extra}) success is {result_extra.success}."
        )

    dy = (
        result_extra.brightestObjCentroidCofM[0]
        - result_intra.brightestObjCentroidCofM[0]
    )
    dx = (
        result_extra.brightestObjCentroidCofM[1]
        - result_intra.brightestObjCentroidCofM[1]
    )
    dr = np.sqrt(dy**2 + dx**2)

    position_out_of_range = dr > 100

    donut_catalog_intra = get_donut_catalog(result_intra, exposure_intra.getWcs())
    donut_catalog_extra = get_donut_catalog(
        *(
            (result_extra, exposure_extra.getWcs())
            if position_out_of_range
            else (result_intra, exposure_intra.getWcs())
        )
    )

    config = EstimateZernikesLatissTaskConfig()
    config.donutStampSize = donut_diameter
    config.donutTemplateSize = donut_diameter
    config.opticalModel = "onAxis"

    task = EstimateZernikesLatissTask(config=config)

    camera = best_effort_isr.butler.get(
        "camera",
        dataId={"instrument": "LATISS"},
        collections="LATISS/calib/unbounded",
    )

    task_output = task.run(
        [exposure_intra, exposure_extra],
        [donut_catalog_intra, donut_catalog_extra],
        camera,
    )

    return result_intra, result_extra, task_output


def get_donut_catalog(result: Struct, wcs: SkyWcs) -> pandas.DataFrame:
    """Get the donut catalog, used by wep, from the quick frame measurement
    result.

    Parameters
    ----------
    result : `Struct`
        Result of `QuickFrameMeasurementTask`.
    wcs : `SkyWcs`
        Exposure WCS, to compute Ra/Dec.

    Returns
    -------
    donut_catalog : `pandas.DataFrame`
        Donut catalog.
    """
    ra, dec = wcs.pixelToSkyArray(
        result.brightestObjCentroidCofM[0],
        result.brightestObjCentroidCofM[1],
        degrees=False,
    )

    donut_catalog = pandas.DataFrame([])
    donut_catalog["coord_ra"] = ra
    donut_catalog["coord_dec"] = dec
    donut_catalog["centroid_x"] = [result.brightestObjCentroidCofM[0]]
    donut_catalog["centroid_y"] = [result.brightestObjCentroidCofM[1]]
    donut_catalog["source_flux"] = [result.brightestObjApFlux70]

    donut_catalog = donut_catalog.sort_values(
        "source_flux", ascending=False
    ).reset_index(drop=True)

    return donut_catalog


def get_image(
    data_id: typing.Dict[str, typing.Union[int, str]],
    best_effort_isr: typing.Any,
    timeout: float,
    loop_time: float = 0.1,
) -> ExposureF:
    """Retrieve image from butler repository.

    If not present, then it will poll at intervals of loop_time (0.1s default)
    until the image arrives, or until the timeout is reached.

    Parameters
    ----------
    data_id : `dict`
        A dictionary consisting of the keys and data required to fetch an
        image from the butler.
        e.g data_id = {'day_obs': 20200219, 'seq_num': 2,
                       'detector': 0, "instrument": 'LATISS'}
    best_effort_isr : `BestEffortIsr`
        BestEffortISR class instantiated with a butler.
    loop_time : `float`
        Time between polling attempts. Defaults to 0.1s
    timeout:  `float`
        Total time to poll for image before raising an exception

    Returns
    -------
    exp: `ExposureF`
        Exposure returned from butler query
    """

    endtime = time.time() + timeout
    while True:
        try:
            exp = best_effort_isr.getExposure(data_id)
            return exp

        except ValueError:
            time.sleep(loop_time)

        if time.time() >= endtime:
            raise TimeoutError(
                f"Unable to get raw image from butler in {timeout} seconds."
            )
