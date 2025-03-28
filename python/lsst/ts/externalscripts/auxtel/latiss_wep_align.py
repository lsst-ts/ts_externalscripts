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

import astropy
import astropy.units as u
import numpy as np
from astropy.table import QTable
from lsst.afw.image import Exposure
from lsst.geom import PointD
from lsst.obs.lsst import Latiss
from lsst.pipe.base.struct import Struct

try:
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr
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
    from lsst.ts.wep.task.generateDonutCatalogUtils import addVisitInfoToCatTable

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
                f"donut_diameter={2*self.side}, "
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
            zk_table = wep_results.zernikes
            zk_average_nm = zk_table[zk_table["label"] == "average"]

            # output from wep is in nm
            self.zern = [
                -zk_average_nm["Z8"][0].value,
                zk_average_nm["Z7"][0].value,
                zk_average_nm["Z4"][0].value,
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
            (result_intra, exposure_intra)
            if not intra_source_out_of_bounds
            else (result_extra, exposure_extra)
        )
    )
    donut_catalog_extra = get_donut_catalog(
        *(
            (result_extra, exposure_extra)
            if not extra_source_out_of_bounds
            else (result_intra, exposure_intra)
        )
    )

    cut_out_config = CutOutDonutsScienceSensorTaskConfig()
    cut_out_config.donutStampSize = donut_diameter
    cut_out_config.opticalModel = "onAxis"
    cut_out_config.initialCutoutPadding = 40
    cut_out_task = CutOutDonutsScienceSensorTask(config=cut_out_config)

    camera = Latiss.getCamera()

    cut_out_output = cut_out_task.run(
        [exposure_extra, exposure_intra],
        [donut_catalog_extra, donut_catalog_intra],
        camera,
    )

    config = CalcZernikesTaskConfig()
    config.doDonutStampSelector = False
    task = CalcZernikesTask(config=config, name="Base Task")

    task_output = task.run(
        cut_out_output.donutStampsExtra, cut_out_output.donutStampsIntra
    )

    return result_intra, result_extra, task_output


def get_donut_catalog(result: Struct, exposure: Exposure) -> astropy.table.QTable:
    """Get the donut catalog, used by wep, from the quick frame measurement
    result.

    Parameters
    ----------
    result : `Struct`
        Result of `QuickFrameMeasurementTask`.
    exposure : `Exposure`
        Exposure, to compute Ra/Dec and pass on visit info.

    Returns
    -------
    donut_catalog : `astropy.table.QTable`
        Donut catalog.
    """
    wcs = exposure.getWcs()
    ra, dec = wcs.pixelToSkyArray(
        result.brightestObjCentroidCofM[0],
        result.brightestObjCentroidCofM[1],
        degrees=False,
    )
    donut_catalog = QTable()
    donut_catalog["coord_ra"] = ra * u.rad
    donut_catalog["coord_dec"] = dec * u.rad
    donut_catalog["centroid_x"] = [result.brightestObjCentroidCofM[0]] * u.pixel
    donut_catalog["centroid_y"] = [result.brightestObjCentroidCofM[1]] * u.pixel
    donut_catalog["source_flux"] = [result.brightestObjApFlux70] * u.nJy
    donut_catalog.meta["blend_centroid_x"] = ""
    donut_catalog.meta["blend_centroid_y"] = ""
    donut_catalog.sort("source_flux", reverse=True)
    donut_catalog = addVisitInfoToCatTable(exposure, donut_catalog)

    return donut_catalog
