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

__all__ = ["LatissCWFSAlign"]

import asyncio
import concurrent.futures
import functools
import os
import typing
import warnings
from pathlib import Path

import numpy as np

from .latiss_base_align import LatissAlignResults, LatissBaseAlign

try:
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
    from lsst.ts.observing.utilities.auxtel.latiss.utils import parse_visit_id
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

# Import CWFS package
try:
    # TODO: (DM-24904) Remove this try/except clause when WEP is adopted
    from lsst import cwfs
    from lsst.cwfs.algorithm import Algorithm
    from lsst.cwfs.image import Image
    from lsst.cwfs.instrument import Instrument
except ImportError:
    warnings.warn("Could not import cwfs code.")

import copy  # used to support binning

STD_TIMEOUT = 10  # seconds to perform ISR


class LatissCWFSAlign(LatissBaseAlign):
    """Perform an optical alignment procedure of Auxiliary Telescope with
    the LATISS instrument (ATSpectrograph and ATCamera CSCs). This is for
    use with in-focus images and is performed using Curvature-Wavefront
    Sensing Techniques.

    Parameters
    ----------
    index : `int`, optional
        Index of Script SAL component (default=1).
    remotes : `bool`, optional
        Should the remotes be created (default=True)? For unit testing this
        can be set to False, which allows one to mock the remotes behaviour.
    descr : `str`, optional
        Short description of the script.

    Notes
    -----
    See parent class `LatissBaseAlign` for additional information.
    """

    def __init__(self, index=1, remotes=True):

        super().__init__(
            index=index,
            remotes=remotes,
            descr="Perform optical alignment procedure of the Rubin Auxiliary "
            "Telescope with LATISS using the original Curvature-Wavefront "
            "Sensing code.",
        )

        # instantiate the quick measurement class
        try:
            qm_config = QuickFrameMeasurementTask.ConfigClass()
            self.qm = QuickFrameMeasurementTask(config=qm_config)
        except NameError:
            self.log.warning("Library unavailable certain tests will be skipped")

        self.extra_focal_position_out_of_range = None
        self.detection_exp = None

        self.I1 = []
        self.I2 = []
        self.fieldXY = [0.0, 0.0]

        self.inst = None
        # set binning of images to increase processing speed
        # at the expense of resolution
        self._binning = 1
        self.algo = None

        self.log.info(
            "LATISS Curvature Wavefront Sensing initialized. Perform optical "
            "alignment procedure of the Rubin Auxiliary Telescope with LATISS "
            "using the original Curvature-Wavefront Sensing code."
        )

    # define the method that sets the hexapod offset to create intra/extra
    # focal images
    @property
    def binning(self) -> int:
        return self._binning

    @binning.setter
    def binning(self, value: int) -> None:
        self._binning = value
        self.dz = self.dz

    def _run_additional_dz_settings(self) -> None:
        self.log.info("Using binning factor of {}".format(self.binning))

        # Create configuration file with the proper parameters
        cwfs_config_template = """#Auxiliary Telescope parameters:
Obscuration 				0.423
Focal_length (m)			21.6
Aperture_diameter (m)   		1.2
Offset (m)				{}
Pixel_size (m)			{}
"""
        config_index = "auxtel_latiss"
        path = Path(cwfs.__file__).resolve().parents[3].joinpath("data", config_index)
        if not path.exists():
            os.makedirs(path)
        dest = path.joinpath(f"{config_index}.param")
        with open(dest, "w") as fp:
            # Write the file and set the offset and pixel size parameters
            fp.write(
                cwfs_config_template.format(self._dz * 0.041, 10e-6 * self.binning)
            )

        self.inst = Instrument(config_index, int(self.side * 2 / self.binning))
        self.algo = Algorithm("exp", self.inst, 1)

    async def run_align(self) -> LatissAlignResults:
        """Runs curvature wavefront sensing code using the original cwfs
        code from https://github.com/bxin/cwfs.

        Returns
        -------
        results : `LatissAlignResults`
            A dataclass containing the results of the calculation.
        """

        # get event loop to run blocking tasks
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()

        self.cwfs_selected_sources = []

        self.log.info(
            f"Running cwfs on {self.intra_visit_id} and {self.extra_visit_id}."
            f"Using a data_id of {parse_visit_id(self.intra_visit_id)} "
            f"and {parse_visit_id(self.extra_visit_id)}."
        )

        self.intra_exposure, self.extra_exposure = await asyncio.gather(
            get_image(
                parse_visit_id(self.intra_visit_id),
                self.best_effort_isr,
                timeout=self.timeout_get_image,
            ),
            get_image(
                parse_visit_id(self.extra_visit_id),
                self.best_effort_isr,
                timeout=self.timeout_get_image,
            ),
        )

        self.log.debug("Running source detection")

        self.intra_result = await loop.run_in_executor(
            executor,
            functools.partial(
                self.qm.run, self.intra_exposure, donutDiameter=2 * self.side
            ),
        )
        self.extra_result = await loop.run_in_executor(
            executor,
            functools.partial(
                self.qm.run, self.extra_exposure, donutDiameter=2 * self.side
            ),
        )
        self.log.debug("Source detection completed")

        # Verify a result was achieved, if not then raising the exception
        if not self.intra_result.success or not self.extra_result.success:
            raise RuntimeError(
                f"Centroid finding algorithm was unsuccessful. "
                f"Intra image ({self.intra_exposure}) success is {self.intra_result.success}. "
                f"Extra image ({self.extra_exposure}) success is {self.extra_result.success}."
            )

        # Verify that results are within 100 pixels of each other (basically
        # the size of a typical donut). This should ensure the same source is
        # used.
        dy = (
            self.extra_result.brightestObjCentroidCofM[0]
            - self.intra_result.brightestObjCentroidCofM[0]
        )
        dx = (
            self.extra_result.brightestObjCentroidCofM[1]
            - self.intra_result.brightestObjCentroidCofM[1]
        )
        dr = np.sqrt(dy**2 + dx**2)
        if dr > 100.0:
            self.log.warning(
                "Source finding algorithm found different sources for intra/extra. \n"
                f"intra found [y,x] = [{self.intra_result.brightestObjCentroidCofM[1]},"
                f"{self.intra_result.brightestObjCentroidCofM[0]}]\n"
                f"extra found [y,x] = [{self.extra_result.brightestObjCentroidCofM[1]},"
                f"{self.extra_result.brightestObjCentroidCofM[0]}]\n"
                "Forcing them to use the intra-location."
            )
            self.extra_focal_position_out_of_range = True
        else:
            self.log.info(
                f"Source finding algorithm found matching sources within {dr} pixels for intra/extra. \n"
                f"intra found [y,x] = [{self.intra_result.brightestObjCentroidCofM[1]},"
                f"{self.intra_result.brightestObjCentroidCofM[0]}]\n"
                f"extra found [y,x] = [{self.extra_result.brightestObjCentroidCofM[1]},"
                f"{self.extra_result.brightestObjCentroidCofM[0]}]\n"
            )
            self.extra_focal_position_out_of_range = False

        # Create stamps for CWFS algorithm. Bin (if desired).
        self.create_donut_stamps_for_cwfs()

        # Now we should be ready to run CWFS
        self.log.info("Starting CWFS algorithm calculation.")
        # reset inputs just in case
        self.algo.reset(self.I1[0], self.I2[0])

        # for a slow telescope, should be running in paraxial mode
        await loop.run_in_executor(
            executor, self.algo.runIt, self.inst, self.I1[0], self.I2[0], "paraxial"
        )

        self.zern = [
            -self.algo.zer4UpNm[3],  # Coma-X (in detector axes, TBC)
            self.algo.zer4UpNm[4],  # Coma-Y (in detector axes, TBC)
            self.algo.zer4UpNm[0],  # defocus
        ]

        results_dict = self.calculate_results()
        return results_dict

    def get_donut_region(
        self, center_y: float, center_x: float
    ) -> typing.Tuple[float, float, float, float]:

        return (
            center_y - self.side,
            center_y + self.side,
            center_x - self.side,
            center_x + self.side,
        )

    def get_intra_donut_center(self) -> typing.Tuple[int, int]:
        return (
            int(self.intra_result.brightestObjCentroidCofM[1]),
            int(self.intra_result.brightestObjCentroidCofM[0]),
        )

    def get_extra_donut_center(self) -> typing.Tuple[int, int]:

        if self.extra_focal_position_out_of_range:
            return self.get_intra_donut_center()
        else:
            return (
                int(self.extra_result.brightestObjCentroidCofM[1]),
                int(self.extra_result.brightestObjCentroidCofM[0]),
            )

    def create_donut_stamps_for_cwfs(self) -> None:
        """Create square stamps with donuts based on centroids."""
        # reset I1 and I2
        self.I1 = []
        self.I2 = []

        self.log.debug(
            f"Creating stamp for intra_image donut on centroid "
            f"[y,x] = [{self.get_intra_donut_center()}] with a side "
            f"length of {2 * self.side} pixels"
        )

        intra_box = self.get_donut_region(*self.get_intra_donut_center())
        intra_square = self.intra_exposure.image.array[
            intra_box[0] : intra_box[1], intra_box[2] : intra_box[3]
        ]

        extra_box = self.get_donut_region(*self.get_extra_donut_center())
        extra_square = self.extra_exposure.image.array[
            extra_box[0] : extra_box[1], extra_box[2] : extra_box[3]
        ]

        self.log.debug(
            f"Created stamp for extra_image donut on centroid "
            f"[y,x] = [{self.get_extra_donut_center()}] with a side "
            f"length of {2 * self.side} pixels"
        )

        # Bin the images
        if self.binning != 1:
            self.log.info(
                f"Stamps for analysis will be binned by {self.binning} in each dimension."
            )
            intra_square0 = copy.deepcopy(intra_square)
            extra_square0 = copy.deepcopy(extra_square)
            # get tuple array from shape array (which is a tuple) and make
            # an integer
            new_shape = tuple(
                np.asarray(
                    np.asarray(intra_square0.shape) / self.binning, dtype=np.int32
                )
            )
            intra_square = self.rebin(intra_square0, new_shape)
            extra_square = self.rebin(extra_square0, new_shape)
            self.log.info(f"intra_square shape is {intra_square.shape}")
            self.log.info(f"extra_square shape is {extra_square.shape}")

        self.I1.append(Image(intra_square, self.fieldXY, Image.INTRA))
        self.I2.append(Image(extra_square, self.fieldXY, Image.EXTRA))

        self.log.debug("create_donut_stamps_for_cwfs completed")

    def rebin(self, arr: np.ndarray, new_shape: np.ndarray) -> np.ndarray:
        """Rebins the array to a new shape via taking the mean of the
        surrounding pixels

        Parameters
        ----------
        arr : `np.array`
            2-D array of arbitrary size
        new_shape : `np.array`
            Tuple 2-element array of size of the output array

        Returns
        -------
        rebinned : `np.array`
            Array binned to new shape
        """
        shape = (
            new_shape[0],
            arr.shape[0] // new_shape[0],
            new_shape[1],
            arr.shape[1] // new_shape[1],
        )
        rebinned = arr.reshape(shape).mean(-1).mean(1)
        return rebinned

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await super().configure(config)

        # Instantiate BestEffortIsr
        self.best_effort_isr = self.get_best_effort_isr()

    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr()
