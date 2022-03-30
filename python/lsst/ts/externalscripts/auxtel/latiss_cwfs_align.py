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

import os
import yaml
import asyncio
import warnings
import concurrent.futures
import functools
import numpy as np

from pathlib import Path

from lsst.ts import salobj
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.observatory.control.auxtel.atcs import ATCS
from lsst.ts.observatory.control.auxtel.latiss import LATISS
from lsst.ts.idl.enums.ATPtg import WrapStrategy

try:
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        parse_visit_id,
    )
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.rapid.analysis import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

# Import CWFS package
try:
    # TODO: (DM-24904) Remove this try/except clause when WEP is adopted
    from lsst import cwfs
    from lsst.cwfs.instrument import Instrument
    from lsst.cwfs.algorithm import Algorithm
    from lsst.cwfs.image import Image
except ImportError:
    warnings.warn("Could not import cwfs code.")

import copy  # used to support binning

STD_TIMEOUT = 10  # seconds to perform ISR


class LatissCWFSAlign(salobj.BaseScript):
    """Perform an optical alignment procedure of Auxiliary Telescope with
    the LATISS instrument (ATSpectrograph and ATCamera CSCs). This is for
    use with in-focus images and is performed using Curvature-Wavefront
    Sensing Techniques.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    None

    **Details**

    This script is used to perform measurements of the wavefront error, then
    propose hexapod offsets based on an input sensitivity matrix to minimize
    the errors. The hexapod offsets are not applied automatically and must be
    performed by the user.

    """

    def __init__(self, index=1, remotes=True):

        super().__init__(
            index=index,
            descr="Perform optical alignment procedure of the Rubin Auxiliary "
            "Telescope with LATISS using Curvature-Wavefront Sensing "
            "Techniques.",
        )

        self.atcs = None
        self.latiss = None
        if remotes:
            self.atcs = ATCS(self.domain, log=self.log)
            self.latiss = LATISS(
                self.domain,
                log=self.log,
                tcs_ready_to_take_data=self.atcs.ready_to_take_data,
            )

        # instantiate the quick measurement class
        try:
            qm_config = QuickFrameMeasurementTask.ConfigClass()
            self.qm = QuickFrameMeasurementTask(config=qm_config)
        except NameError:
            self.log.warning("Library unavailable certain tests will be skipped")

        # Timeouts used for telescope commands
        self.short_timeout = 5.0  # used with hexapod offset command
        self.long_timeout = 30.0  # used to wait for in-position event from hexapod
        # Have discovered that the occasional image will take 12+ seconds
        # to ingest
        self.timeout_get_image = 20.0

        # Sensitivity matrix: mm of hexapod motion for nm of wfs. To figure out
        # the hexapod correction multiply the calculcated zernikes by this.
        # Note that the zernikes must be derotated to
        #         self.sensitivity_matrix = [
        #         [1.0 / 161.0, 0.0, 0.0],
        #         [0.0, -1.0 / 161.0, (107.0/161.0)/4200],
        #         [0.0, 0.0, -1.0 / 4200.0]
        #         ]
        self.sensitivity_matrix = [
            [1.0 / 206.0, 0.0, 0.0],
            [0.0, -1.0 / 206.0, -(109.0 / 206.0) / 4200],
            [0.0, 0.0, 1.0 / 4200.0],
        ]

        # Rotation matrix to take into account angle between camera and
        # boresight
        self.rotation_matrix = lambda angle: np.array(
            [
                [np.cos(np.radians(angle)), -np.sin(np.radians(angle)), 0.0],
                [np.sin(np.radians(angle)), np.cos(np.radians(angle)), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )

        # Matrix to map hexapod offset to alt/az offset in the focal plane
        # units are arcsec/mm. X-axis is Elevation
        # Measured with data from AT run SUMMIT-5027, still unverified.
        # x-offset measured with images 2021060800432 - 2021060800452
        # y-offset measured with images 2021060800452 - 2021060800472
        self.hexapod_offset_scale = [
            [52.459, 0.0, 0.0],
            [0.0, 50.468, 0.0],
            [0.0, 0.0, 0.0],
        ]

        # Angle between camera and boresight
        # Assume perfect mechanical mounting
        self.camera_rotation_angle = 0.0

        # The following attributes are set via the configuration:
        self.filter = None
        self.grating = None
        # exposure time for the intra/extra images (in seconds)
        self.exposure_time = None
        # offset for the intra/extra images
        self._dz = None
        # butler data path.
        self.datapath = None
        # end of configurable attributes

        # Set (oversized) stamp size for centroid estimation
        self.pre_side = 300
        # Set stamp size for WFE estimation
        # 192 pix is size for dz=1.5, but gets automatically
        # scaled based on dz later, so can multiply by an
        # arbitrary factor here to make it larger
        self._side = 192 * 1.1  # normally 1.1
        # self.selected_source_centroid = None

        # angle between elevation axis and nasmyth2 rotator
        self.angle = None

        self.intra_visit_id = None
        self.extra_visit_id = None

        self.intra_exposure = None
        self.extra_exposure = None
        self.detection_exp = None

        self.I1 = []
        self.I2 = []
        self.fieldXY = [0.0, 0.0]

        self.inst = None
        # set binning of images to increase processing speed
        # at the expense of resolution
        self._binning = 1
        self.algo = None

        self.zern = None
        self.hexapod_corr = None

        # make global to expose for unit tests
        self.total_focus_offset = 0.0
        self.total_coma_x_offset = 0.0
        self.total_coma_y_offset = 0.0

        self.data_pool_sleep = 5.0

        self.log.info("latiss_cwfs_align initialized!")

    # define the method that sets the hexapod offset to create intra/extra
    # focal images
    @property
    def dz(self):
        if self._dz is None:
            self.dz = 0.8
        return self._dz

    @property
    def binning(self):
        return self._binning

    @binning.setter
    def binning(self, value):
        self._binning = value
        self.dz = self.dz

    @property
    def side(self):
        # must be an even number
        return int(np.ceil(self._side * self.dz / 1.5 / 2.0) * 2)

    @dz.setter
    def dz(self, value):
        self._dz = float(value)
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

    async def take_intra_extra(self):
        """Take pair of Intra/Extra focal images to be used to determine
        the measured wavefront error. Because m2 is being moved, the intra
        focal image occurs when the hexapod receives a positive offset and
        is pushed towards the primary mirror. The extra-focal image occurs
        when the hexapod is pulled back (negative offset) from the
        sbest-focus position.

        Returns
        -------
        images_end_readout_evt: list
            List of endReadout event for the intra and extra images.

        """

        self.log.debug("Moving to intra-focal position")

        await self.hexapod_offset(self.dz)

        intra_image = await self.latiss.take_engtest(
            exptime=self.exposure_time,
            n=1,
            group_id=self.group_id,
            filter=self.filter,
            grating=self.grating,
            reason="INTRA" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.program,
        )

        self.log.debug("Moving to extra-focal position")

        # Hexapod offsets are relative, so need to move 2x the offset
        # to get from the intra- to the extra-focal position.
        # then add the offset to compensate for un-equal magnification
        await self.hexapod_offset(-(self.dz * 2.0 + self.extra_focal_offset))

        self.log.debug("Taking extra-focal image")

        extra_image = await self.latiss.take_engtest(
            exptime=self.exposure_time,
            n=1,
            group_id=self.group_id,
            filter=self.filter,
            grating=self.grating,
            reason="EXTRA" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.program,
        )

        self.intra_visit_id = int(intra_image[0])

        self.log.info(f"intraImage expId for target: {self.intra_visit_id}")

        self.extra_visit_id = int(extra_image[0])

        self.log.info(f"extraImage expId for target: {self.extra_visit_id}")

        self.angle = 90.0 - await self.atcs.get_bore_sight_angle()
        self.log.info(f"angle used in cwfs algorithm is {self.angle:0.2f}")

        self.log.debug("Moving hexapod back to zero offset (in-focus) position")
        # This is performed such that the telescope is left in the
        # same position it was before running the script
        await self.hexapod_offset(self.dz)

    async def hexapod_offset(self, offset, x=0.0, y=0.0):
        """Applies z-offset to the hexapod to move between
        intra/extra/in-focus positions.

        Parameters
        ----------
        offset: `float`
             Focus offset to the hexapod in mm

        """

        offset = {
            "m1": 0.0,
            "m2": 0.0,
            "x": x,
            "y": y,
            "z": offset,
            "u": 0.0,
            "v": 0.0,
        }

        self.atcs.rem.athexapod.evt_positionUpdate.flush()
        await self.atcs.rem.ataos.cmd_offset.set_start(
            **offset, timeout=self.long_timeout
        )
        await self.atcs.rem.athexapod.evt_positionUpdate.next(
            flush=False, timeout=self.long_timeout
        )

    async def run_cwfs(self):
        """Runs CWFS code on intra/extra focal images.

        Returns
        -------
        Dictionary of calculated values
        results = {'zerns' : (self.zern),
                  'rot_zerns': (rot_zern),
                  'hex_offset': (hexapod_offset),
                  'tel_offset': (tel_offset)}

        """

        # get event loop to run blocking tasks
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()

        self.cwfs_selected_sources = []

        if self.intra_visit_id is None or self.extra_visit_id is None:
            self.log.warning(
                "Intra/Extra images not taken. Running take image sequence."
            )
            await self.take_intra_extra()
        else:
            self.log.info(
                f"Running cwfs on {self.intra_visit_id} and {self.extra_visit_id}."
            )
            self.log.debug(f"Using datapath of {self.datapath}.")
            self.log.debug(
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
                f"Intra success is {self.intra_result.success}. "
                f"Extra image success is {self.extra_result.success}."
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
                "{self.intra_result.brightestObjCentroidCofM[0]}]\n"
                f"extra found [y,x] = [{self.extra_result.brightestObjCentroidCofM[1]},"
                "{self.extra_result.brightestObjCentroidCofM[0]}]\n"
                "Forcing them to use the intra-location."
            )
            self.force_extra_focal_box_location = True
        else:
            self.force_extra_focal_box_location = False

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

    def create_donut_stamps_for_cwfs(self):
        """Create square stamps with donuts based on centroids."""
        # reset I1 and I2
        self.I1 = []
        self.I2 = []

        ceny, cenx = int(self.intra_result.brightestObjCentroidCofM[1]), int(
            self.intra_result.brightestObjCentroidCofM[0]
        )
        self.log.debug(
            f"Creating stamp for intra_image donut on centroid [y,x] = [{ceny},{cenx}] with a side "
            f"length of {2 * self.side} pixels"
        )
        intra_square = self.intra_exposure.image.array[
            ceny - self.side : ceny + self.side, cenx - self.side : cenx + self.side
        ]

        if self.force_extra_focal_box_location:
            extra_square = self.extra_exposure.image.array[
                ceny - self.side : ceny + self.side, cenx - self.side : cenx + self.side
            ]
        else:
            ceny, cenx = int(self.extra_result.brightestObjCentroidCofM[1]), int(
                self.extra_result.brightestObjCentroidCofM[0]
            )

            extra_square = self.extra_exposure.image.array[
                ceny - self.side : ceny + self.side, cenx - self.side : cenx + self.side
            ]

        self.log.debug(
            f"Created stamp for extra_image donut on centroid [y,x] = [{ceny},{cenx}] with a side "
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

    def rebin(self, arr, new_shape):
        """Rebins the array to a new shape via taking the mean of the
        surrounding pixels

        Parameters
        ----------
        arr: `np.array`
            2-D array of arbitrary size
        new_shape: `np.array`
            Tuple 2-element array of size of the output array

        Returns
        -------
        rebinned: `np.array`
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

    def calculate_results(self):
        """Calculates hexapod and telescope offsets based on
        derotated zernikes.

        Returns
        -------
        results : `dict`
            Dictionary of calculated values

        """
        rot_zern = np.matmul(
            self.zern, self.rotation_matrix(self.angle + self.camera_rotation_angle)
        )
        hexapod_offset = np.matmul(rot_zern, self.sensitivity_matrix)
        tel_offset = np.matmul(hexapod_offset, self.hexapod_offset_scale)

        self.log.info(
            f"""==============================
Measured [coma-X, coma-Y, focus] zernike coefficients [nm]: [{
            (len(self.zern) * '{:0.1f}, ').format(*self.zern)}]
De-rotated [coma-X, coma-Y, focus]  zernike coefficients [nm]: [{
            (len(rot_zern) * '{:0.1f}, ').format(*rot_zern)}]
Hexapod [x, y, z] offsets [mm] : {(len(hexapod_offset) * '{:0.3f}, ').format(*hexapod_offset)}
Telescope offsets [arcsec]: {(len(tel_offset) * '{:0.1f}, ').format(*tel_offset)}
==============================
"""
        )

        results = {
            "zerns": (self.zern),
            "rot_zerns": (rot_zern),
            "hex_offset": (hexapod_offset),
            "tel_offset": (tel_offset),
        }

        return results

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/LatissCWFSAlign.yaml
            title: LatissCWFSAlign v1
            description: Configuration for LatissCWFSAlign Script.
            type: object
            properties:
              find_target:
                type: object
                additionalProperties: false
                required:
                  - az
                  - el
                  - mag_limit
                description: >-
                    Optional configuration section. Find a target to perform CWFS in the given
                    position and magnitude range. If not specified, the step is ignored.
                properties:
                  az:
                    type: number
                    description: Azimuth (in degrees) to find a target.
                  el:
                    type: number
                    description: Elevation (in degrees) to find a target.
                  mag_limit:
                    type: number
                    description: Minimum (brightest) V-magnitude limit.
                  mag_range:
                    type: number
                    description: >-
                        Magnitude range. The maximum/faintest limit is defined as
                        mag_limit+mag_range.
                  radius:
                    type: number
                    description: Radius of the cone search (in degrees).
              track_target:
                type: object
                additionalProperties: false
                required:
                  - target_name
                description: >-
                    Optional configuration section. Track a specified target to
                    perform CWFS. If not specified, the step is ignored.
                properties:
                  target_name:
                    description: Target name
                    type: string
                  icrs:
                    type: object
                    additionalProperties: false
                    description: Optional ICRS coordinates.
                    required:
                      - ra
                      - dec
                    properties:
                      ra:
                        description: ICRS right ascension (hour).
                        type: number
                        minimum: 0
                        maximum: 24
                      dec:
                        description: ICRS declination (deg).
                        type: number
                        minimum: -90
                        maximum: 90
              filter:
                description: Which filter to use when taking intra/extra focal images.
                type: string
                default: empty_1
              grating:
                description: Which grating to use when taking intra/extra focal images.
                type: string
                default: empty_1
              exposure_time:
                description: The exposure time to use when taking intra/extra focal images (sec).
                type: number
                default: 30.
              acq_exposure_time:
                description: The exposure time to use when taking an in focus acquisition image(sec).
                type: number
                default: 5.
              take_detection_image:
                description: >-
                    Take an in-focus image before the cwfs loop to use for source
                    detection?
                type: boolean
                default: false
              dz:
                description: De-focus to apply when acquiring the intra/extra focal images (mm).
                type: number
                default: 0.8
              extra_focal_offset:
                description: >-
                    The additional m2 defocus (mm) to apply for the extra-focal image to be the
                    same size as the intra. This value is always positive to compensate for
                    the change in magnification from moving the secondary mirror.
                type: number
                default: 0.0011
              datapath:
                description: Path to the gen3 butler data repository. The default is for the summit.
                type: string
                default: /repo/LATISS
              large_defocus:
                description: >-
                    Defines a large defocus. If the measured defocus is larger than this value,
                    apply only half of correction.
                type: number
                default: 0.08
              threshold:
                 description: >-
                   Focus correction threshold. If correction is lower than this
                   value, stop correction loop.
                 type: number
                 default: 0.01
              coma_threshold:
                 description: >-
                   Coma correction threshold. If correction is lower than this
                   value, stop correction loop.
                 type: number
                 default: 0.2
              offset_telescope:
                description: When correcting coma, also offset the telescope?
                type: boolean
                default: true
              max_iter:
                  description: Maximum number of iterations.
                  type: integer
                  default: 5
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              program:
                description: >-
                  Optional name of the program this dataset belongs to.
                type: string
                default: CWFS
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

        if hasattr(config, "find_target") and hasattr(config, "track_target"):
            raise RuntimeError(
                "find_target and track_target configuration sections cannot be specified together."
            )
        elif hasattr(config, "find_target"):
            self.log.debug(f"Finding target for cwfs @ {config.find_target}")
            self.cwfs_target = await self.atcs.find_target(**config.find_target)
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None
            self.log.debug(f"Using target {self.cwfs_target} for cwfs.")
        elif hasattr(config, "track_target"):
            self.log.debug(f"Tracking target {config.track_target} for cwfs.")
            self.cwfs_target = config.track_target.get("target_name", "cwfs_target")
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None
            if "icrs" in config.track_target:
                self.cwfs_target_ra = config.track_target["icrs"]["ra"]
                self.cwfs_target_dec = config.track_target["icrs"]["dec"]
        else:
            self.log.debug("No target configured.")
            self.cwfs_target = None
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None

        self.filter = config.filter
        self.grating = config.grating

        # exposure time for the intra/extra images (in seconds)
        self.exposure_time = config.exposure_time

        self.acq_exposure_time = config.acq_exposure_time

        # offset for the intra/extra images
        self.dz = config.dz
        # delta offset for extra focal image
        self.extra_focal_offset = config.extra_focal_offset

        # butler data path.
        self.datapath = config.datapath

        # Instantiate BestEffortIsr
        self.best_effort_isr = self.get_best_effort_isr()

        self.large_defocus = config.large_defocus

        self.threshold = config.threshold

        self.coma_threshold = config.coma_threshold

        self.offset_telescope = config.offset_telescope

        self.max_iter = config.max_iter

        self.reason = config.reason

        self.program = config.program

        self.take_detection_image = config.take_detection_image

        # Assume the time-on-target is 10 minutes
        self.time_on_target = 10 * 60

    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr(self.datapath)

    def set_metadata(self, metadata):
        # It takes about 300s to run the cwfs code, plus the two exposures
        metadata.duration = 300.0 + 2.0 * self.exposure_time
        metadata.filter = f"{self.filter},{self.grating}"

    async def arun(self, checkpoint=False):
        """Perform CWFS measurements and hexapod adjustments until the
        thresholds are reached.
        """

        if self.cwfs_target is not None and self.cwfs_target_dec is None:
            if checkpoint:
                await self.checkpoint(f"Slewing to object: {self.cwfs_target}")
            await self.atcs.slew_object(
                name=self.cwfs_target,
                rot=0.0,
                rot_type=RotType.PhysicalSky,
                az_wrap_strategy=WrapStrategy.OPTIMIZE,
                time_on_target=self.time_on_target,
            )

        elif (
            self.cwfs_target is not None
            and self.cwfs_target_dec is not None
            and self.cwfs_target_ra is not None
        ):
            if checkpoint:
                await self.checkpoint(
                    f"Slewing to icrs coordinates: {self.cwfs_target} @ "
                    f"ra/dec = {self.cwfs_target_ra}/{self.cwfs_target_dec}."
                )

            await self.atcs.slew_icrs(
                ra=self.cwfs_target_ra,
                dec=self.cwfs_target_dec,
                target_name=self.cwfs_target,
                rot=0.0,
                rot_type=RotType.PhysicalSky,
                az_wrap_strategy=WrapStrategy.OPTIMIZE,
                time_on_target=self.time_on_target,
            )
        elif (self.cwfs_target_dec is not None and self.cwfs_target_ra is None) or (
            self.cwfs_target_dec is None and self.cwfs_target_ra is not None
        ):
            raise RuntimeError(
                "Invalid configuration. Only one of ra/dec pair was specified. "
                "Either define both or neither. "
                f"Got ra={self.cwfs_target_ra} and dec={self.cwfs_target_dec}."
            )

        if self.take_detection_image:
            if checkpoint:
                await self.checkpoint("Detection image.")
            await self.latiss.take_engtest(
                self.acq_exposure_time,
                group_id=self.group_id,
                reason="DETECTION_INFOCUS"
                + ("" if self.reason is None else f"_{self.reason}"),
                program=self.program,
            )

        self.total_focus_offset = 0.0
        self.total_coma_x_offset = 0.0
        self.total_coma_y_offset = 0.0
        for i in range(self.max_iter):

            self.log.debug(f"CWFS iteration {i + 1} starting...")

            if checkpoint:
                await self.checkpoint(
                    f"[{i + 1}/{self.max_iter}]: CWFS loop starting..."
                )

            # Setting visit_id's to none so run_cwfs will take a new dataset.
            self.intra_visit_id = None
            self.extra_visit_id = None
            results = await self.run_cwfs()
            coma_x = results["hex_offset"][0]
            coma_y = results["hex_offset"][1]
            focus_offset = results["hex_offset"][2]

            total_coma_offset = np.sqrt(coma_x**2.0 + coma_y**2.0)
            if (
                abs(focus_offset) < self.threshold
                and total_coma_offset < self.coma_threshold
            ):
                self.total_focus_offset += focus_offset
                self.log.info(
                    f"Focus ({focus_offset:0.3f}) and coma ({total_coma_offset:0.3f}) offsets "
                    f"inside tolerance level ({self.threshold:0.3f}). "
                    f"Total focus correction: {self.total_focus_offset:0.3f} mm. "
                    f"Total coma-x correction: {self.total_coma_x_offset:0.3f} mm. "
                    f"Total coma-y correction: {self.total_coma_y_offset:0.3f} mm."
                )
                if checkpoint:
                    await self.checkpoint(f"[{i + 1}/{self.max_iter}]: CWFS converged.")
                # Add coma offsets from previous run
                self.total_coma_x_offset += coma_x
                self.total_coma_y_offset += coma_y
                await self.hexapod_offset(focus_offset, x=coma_x, y=coma_y)
                if self.offset_telescope:
                    tel_el_offset, tel_az_offset = (
                        results["tel_offset"][0],
                        results["tel_offset"][1],
                    )
                    self.log.info(
                        f"Applying telescope offset [az,el]: [{tel_az_offset:0.3f}, {tel_el_offset:0.3f}]."
                    )
                    await self.atcs.offset_azel(
                        az=tel_az_offset,
                        el=tel_el_offset,
                        relative=True,
                        persistent=True,
                    )
                current_target = await self.atcs.rem.atptg.evt_currentTarget.aget(
                    timeout=self.short_timeout
                )
                hexapod_position = (
                    await self.atcs.rem.athexapod.tel_positionStatus.aget(
                        timeout=self.short_timeout
                    )
                )
                self.log.info(
                    f"Hexapod LUT Datapoint - {current_target.targetName} - "
                    f"reported hexapod position is, {hexapod_position.reportedPosition}."
                )
                self.log.debug("Taking in focus image after applying final results.")
                await self.latiss.take_object(
                    self.acq_exposure_time,
                    group_id=self.group_id,
                    reason="FINAL_INFOCUS"
                    + ("" if self.reason is None else f"_{self.reason}"),
                    program=self.program,
                )
                await self.atcs.add_point_data()

                self.log.info("latiss_cwfs_align script completed successfully!\n")
                return
            elif abs(focus_offset) > self.large_defocus:
                self.total_focus_offset += focus_offset / 2.0
                self.log.warning(
                    f"Computed focus offset too large: {focus_offset}. "
                    "Applying half correction."
                )
                if checkpoint:
                    await self.checkpoint(
                        f"[{i + 1}/{self.max_iter}]: CWFS focus error too large."
                    )
                await self.hexapod_offset(focus_offset / 2.0)
            else:
                self.total_focus_offset += focus_offset
                self.log.info(
                    f"Applying offset: x={coma_x}, y={coma_y}, z={focus_offset}."
                )
                if checkpoint:
                    await self.checkpoint(
                        f"[{i + 1}/{self.max_iter}]: CWFS applying coma and focus correction."
                    )
                self.total_coma_x_offset += coma_x
                self.total_coma_y_offset += coma_y
                await self.hexapod_offset(focus_offset, x=coma_x, y=coma_y)
                if self.offset_telescope:
                    tel_el_offset, tel_az_offset = (
                        results["tel_offset"][0],
                        results["tel_offset"][1],
                    )
                    self.log.info(
                        f"Applying telescope offset az/el: {tel_az_offset}/{tel_el_offset}."
                    )
                    await self.atcs.offset_azel(
                        az=tel_az_offset,
                        el=tel_el_offset,
                        relative=True,
                        persistent=True,
                    )

        self.log.warning(
            f"Reached maximum iteration ({self.max_iter}) without convergence.\n"
        )

    async def run(self):
        await self.arun(True)
