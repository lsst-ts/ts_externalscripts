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
import typing
import warnings

import numpy as np
import pandas
from lsst.afw.geom import SkyWcs
from lsst.geom import PointD
from lsst.pipe.base.struct import Struct

try:
    from lsst.summit.utils import BestEffortIsr, PeekExposureTask
    from lsst.ts.observing.utilities.auxtel.latiss.getters import (
        get_image_sync as get_image,
    )
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_visit_id,
    )
    from lsst.ts.wep.task.calcZernikesTask import (
        CalcZernikesTask,
        CalcZernikesTaskConfig,
    )
    from lsst.ts.wep.task.cutOutDonutsScienceSensorTask import (
        CutOutDonutsScienceSensorTask,
        CutOutDonutsScienceSensorTaskConfig,
    )

except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


from lsst.ts.observatory.control.constants.latiss_constants import boresight

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
                -wep_results.outputZernikesAvg[4] * 1e3,
                wep_results.outputZernikesAvg[3] * 1e3,
                wep_results.outputZernikesAvg[0] * 1e3,
            ]

        return self.calculate_results()


def run_wep(
    intra_visit_id: int,
    extra_visit_id: int,
    donut_diameter: int,
    timeout_get_image: float,
    max_distance_from_boresight: float = 500.0,
) -> typing.Tuple[Struct, Struct, Struct]:
    best_effort_isr = BestEffortIsr()

    # Get intra and extra results
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

    quick_frame_measurement_config = PeekExposureTask.ConfigClass()
    quick_frame_measurement_task = PeekExposureTask(
        config=quick_frame_measurement_config
    )

    result_intra = quick_frame_measurement_task.run(
        exposure_intra, donutDiameter=donut_diameter
    )
    result_extra = quick_frame_measurement_task.run(
        exposure_extra, donutDiameter=donut_diameter
    )

    if result_intra.mode == "failed" or result_extra.mode == "failed":
        raise RuntimeError(
            f"Centroid finding algorithm was unsuccessful. "
            f"Intra image ({exposure_intra}) success is {result_intra}. "
            f"Extra image ({exposure_extra}) success is {result_extra}."
        )

    dx_boresight_extra, dy_boresight_extra = calculate_xy_offsets(
        PointD(
            result_extra.brightestObjCentroid[0], result_extra.brightestObjCentroid[1]
        ),
        boresight,
    )
    dx_boresight_intra, dy_boresight_intra = calculate_xy_offsets(
        PointD(
            result_intra.brightestObjCentroid[0], result_intra.brightestObjCentroid[1]
        ),
        boresight,
    )

    dr_boresight_extra = np.sqrt(dx_boresight_extra**2 + dy_boresight_extra**2)
    dr_boresight_intra = np.sqrt(dx_boresight_intra**2 + dy_boresight_intra**2)

    extra_source_out_of_bounds = dr_boresight_extra > max_distance_from_boresight
    intra_source_out_of_bounds = dr_boresight_intra > max_distance_from_boresight

    if extra_source_out_of_bounds and intra_source_out_of_bounds:
        raise RuntimeError(
            "Both the intra and extra images detected sources are out of bounds. "
            f"Should be closer than {max_distance_from_boresight}. "
            f"Got {dr_boresight_extra} and {dr_boresight_intra}."
        )

    donut_catalog_intra = get_donut_catalog(
        *(
            (result_intra, exposure_intra.getWcs())
            if not intra_source_out_of_bounds
            else (result_extra, exposure_extra.getWcs())
        )
    )
    donut_catalog_extra = get_donut_catalog(
        *(
            (result_extra, exposure_extra.getWcs())
            if not extra_source_out_of_bounds
            else (result_intra, exposure_intra.getWcs())
        )
    )

    cut_out_config = CutOutDonutsScienceSensorTaskConfig()
    # LATISS config parameters
    cut_out_config.opticalModel = "onAxis"
    cut_out_config.donutStampSize = donut_diameter
    cut_out_config.donutTemplateSize = donut_diameter
    cut_out_config.instObscuration = 0.3525
    cut_out_config.instFocalLength = 21.6
    cut_out_config.instApertureDiameter = 1.2
    cut_out_config.instDefocalOffset = 32.8
    cut_out_task = CutOutDonutsScienceSensorTask(config=cut_out_config)

    camera = best_effort_isr.butler.get(
        "camera",
        dataId={"instrument": "LATISS"},
        collections="LATISS/calib/unbounded",
    )

    cut_out_output = cut_out_task.run(
        [exposure_extra, exposure_intra],
        [donut_catalog_extra, donut_catalog_intra],
        camera,
    )

    config = CalcZernikesTaskConfig()
    # LATISS config parameters
    config.opticalModel = "onAxis"
    config.instObscuration = 0.3525
    config.instFocalLength = 21.6
    config.instApertureDiameter = 1.2
    config.instDefocalOffset = 32.8
    task = CalcZernikesTask(config=config, name="Base Task")

    task_output = task.run(
        cut_out_output.donutStampsExtra, cut_out_output.donutStampsIntra
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
    donut_catalog["blend_centroid_x"] = [[]]
    donut_catalog["blend_centroid_y"] = [[]]
    donut_catalog["source_flux"] = [result.brightestObjApFlux70]

    donut_catalog = donut_catalog.sort_values(
        "source_flux", ascending=False
    ).reset_index(drop=True)

    return donut_catalog
