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

__all__ = ["LatissBaseAlign"]

import abc
import time
import types
import yaml
import typing
import dataclasses

import numpy as np

from lsst.ts import salobj
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.observatory.control.auxtel.atcs import ATCS
from lsst.ts.observatory.control.auxtel.latiss import LATISS
from lsst.ts.idl.enums.ATPtg import WrapStrategy

STD_TIMEOUT = 10


@dataclasses.dataclass
class LatissAlignResults:
    zernikes: typing.Tuple[float, float, float]
    zernikes_rot: typing.Tuple[float, float, float]
    offset_hex: typing.Tuple[float, float, float]
    offset_tel: typing.Tuple[float, float, float]


class LatissBaseAlign(salobj.BaseScript, metaclass=abc.ABCMeta):
    """Implements generic behavior for scripts that execute curvature wavefront
    sensing, abstracting the part that performs the measurements.

    This metaclass implements the basic functionality of finding targets and
    taking the (intra/extra focal) data. Child classes are left to implement
    the processing of the data and returning the results.

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
    **Checkpoints**

    - "Slewing to ...": Before slewing to target.
    - "Detection image": If taking in-focus detection image.
    - "[N/MAX_ITER]: CWFS loop starting...": Before each cwfs iteration, where
        "N"  is the iteration number and "MAX_ITER" is the maximum number of
        iterations.
    - "[N/MAX_ITER]: CWFS converged.": Once CWFS reaches convergence.
    - "[N/MAX_ITER]: CWFS focus error too large.": If computed focus correction
        is larger than specified threshhold.
    - "[N/MAX_ITER]: CWFS applying coma and focus correction.": Just before
        corrections are applied.

    **Details**

    This script is used to perform measurements of the wavefront error, then
    propose hexapod offsets based on an input sensitivity matrix to minimize
    the errors. The hexapod offsets are not applied automatically and must be
    performed by the user.
    """

    def __init__(self, index=1, remotes=True, descr=""):

        super().__init__(
            index=index,
            descr=descr,
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

        # Timeouts used for telescope commands
        self.timeout_short = 5.0  # used with hexapod offset command
        self.timeout_long = 30.0  # used to wait for in-position event from hexapod
        # Have discovered that the occasional image will take 12+ seconds
        # to ingest
        self.timeout_get_image = 20.0
        self.data_pool_sleep = 5.0

        # Sensitivity matrix: mm of hexapod motion for nm of wfs. To figure out
        # the hexapod correction multiply the calculated zernikes by this.
        # Note that the zernikes must be derotated before applying the
        # corrections. See https://tstn-016.lsst.io/ for information about how
        # these values were derived.
        self.matrix_sensitivity = [
            [1.0 / 206.0, 0.0, 0.0],
            [0.0, -1.0 / 206.0, -(109.0 / 206.0) / 4200],
            [0.0, 0.0, 1.0 / 4200.0],
        ]

        # Rotation matrix to take into account angle between camera and
        # boresight
        self.matrix_rotation = lambda angle: np.array(
            [
                [np.cos(np.radians(angle)), -np.sin(np.radians(angle)), 0.0],
                [np.sin(np.radians(angle)), np.cos(np.radians(angle)), 0.0],
                [0.0, 0.0, 1.0],
            ]
        )

        # Matrix to map hexapod offset to alt/az offset in the focal plane
        # units are arcsec/mm. X-axis is Elevation
        # Measured with data from AT run SUMMIT-5027.
        self.hexapod_offset_scale = [
            [52.459, 0.0, 0.0],
            [0.0, 50.468, 0.0],
            [0.0, 0.0, 0.0],
        ]

        # Default values for rotator angle and rotator strategy.
        self.rot = 0.0
        self.rot_strategy = RotType.SkyAuto

        # Angle between camera and boresight
        # Assume perfect mechanical mounting
        self.camera_rotation_angle = 0.0

        # The following attributes are set via the configuration:
        self.filter = None
        self.grating = None

        # exposure time for the intra/extra images (in seconds)
        self.exposure_time = None

        # Assume the time-on-target is 10 minutes (600 seconds)
        # for rotator positioning
        self.time_on_target = 600

        # Set stamp size for WFE estimation
        # 192 pix is size for dz=1.5, but gets automatically
        # scaled based on dz later, so can multiply by an
        # arbitrary factor here to make it larger
        self._side = 192 * 1.1  # normally 1.1

        # offset for the intra/extra images
        self._dz = None

        # end of configurable attributes

        # angle between elevation axis and nasmyth2 rotator
        self.angle = None

        self.intra_visit_id = None
        self.extra_visit_id = None

        self.zern = None
        self.hexapod_corr = None

        # Keep track of the total hexapod offset
        self.offset_total_focus = 0.0
        self.offset_total_coma_x = 0.0
        self.offset_total_coma_y = 0.0

        self.camera_playlist = None

    # define the method that sets the hexapod offset to create intra/extra
    # focal images
    @property
    def dz(self) -> float:
        if self._dz is None:
            self.dz = 0.8
        return self._dz

    @dz.setter
    def dz(self, value: float) -> None:
        self._dz = float(value)
        self._run_additional_dz_settings()

    @property
    def side(self) -> int:
        # must be an even number
        return int(np.ceil(self._side * self.dz / 1.5 / 2.0) * 2)

    @abc.abstractmethod
    async def run_align(self) -> LatissAlignResults:
        """Runs curvature wavefront sensing code.

        Returns
        -------
        results : `LatissAlignResults`
            A dataclass containing the results of the calculation.
        """
        raise NotImplementedError()

    def _run_additional_dz_settings(self) -> None:
        """Additional actions needed when setting the focus offset value.

        By default do nothing. When subclassing, implement additional actions
        that need to be executed when setting the focus offset value.
        """
        pass

    async def take_intra_extra(self) -> None:
        """Take pair of Intra/Extra focal images to be used to determine the
        measured wavefront error.

        Because m2 is being moved, the intra focal image occurs when the
        hexapod receives a positive offset and is pushed towards the primary
        mirror. The extra-focal image occurs when the hexapod is pulled back
        (negative offset) from the best-focus position.
        """

        self.log.debug("Moving to intra-focal position")

        await self.hexapod_offset(self.dz)

        self.log.debug("Taking intra-focal image")

        intra_image = await self.latiss.take_cwfs(
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

        extra_image = await self.latiss.take_cwfs(
            exptime=self.exposure_time,
            n=1,
            group_id=self.group_id,
            filter=self.filter,
            grating=self.grating,
            reason="EXTRA" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.program,
        )

        self.intra_visit_id = int(intra_image[0])
        self.extra_visit_id = int(extra_image[0])

        self.log.info(
            f"Intra/extra exposure ids: {self.intra_visit_id}/{self.extra_visit_id}"
        )

        self.angle = 90.0 - await self.atcs.get_bore_sight_angle()

        self.log.info(f"Angle used in cwfs algorithm is {self.angle:0.2f}")

        self.log.debug("Moving hexapod back to zero offset (in-focus) position")
        # This is performed such that the telescope is left in the
        # same position it was before running the script
        await self.hexapod_offset(self.dz)

    async def hexapod_offset(
        self, offset: float, x: float = 0.0, y: float = 0.0
    ) -> None:
        """Applies z-offset to the hexapod to move between
        intra/extra/in-focus positions.

        Parameters
        ----------
        offset : `float`
             Focus offset to the hexapod in mm.
        x : `float`, optional
            Offset the hexapod in the x-axis, in mm (default=0).
        y : `float`, optional
            Offset the hexapod in the y-axis, in mm (default=0).
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

        self.atcs.rem.ataos.evt_detailedState.flush()
        await self.atcs.rem.ataos.cmd_offset.set_start(
            **offset, timeout=self.timeout_long
        )
        # Wait for ataos to go through a cycle, which will apply the offset if
        # enough error has accumulated to pass the ataos thresholds.
        # Success means we need to see ATAOS substate bit 3 (hexapod
        # correction) or 4 (Focus correction), then 0 (IDLE).
        # The bit(s) will flip when the correction is being determined,
        # regardless  of if a hexapod actually had to move

        start_time = time.time()
        check_ss2 = False
        while time.time() < start_time + self.timeout_long:
            state = await self.atcs.rem.ataos.evt_detailedState.next(
                flush=False, timeout=self.timeout_long
            )
            if (
                bool(state.substate & (1 << 3))
                or bool(state.substate & (1 << 4))
                or check_ss2 is True
            ):
                check_ss2 = True
                if state.substate == 0:
                    break

    def calculate_results(self) -> LatissAlignResults:
        """Calculates hexapod and telescope offsets based on derotated
        zernikes.

        Returns
        -------
        results : `LatissAlignResults`
            Results of the wavefront sensing.
        """
        rot_zern = np.matmul(
            self.zern, self.matrix_rotation(self.angle + self.camera_rotation_angle)
        )
        hexapod_offset = np.matmul(rot_zern, self.matrix_sensitivity)
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

        results = LatissAlignResults(
            zernikes=(self.zern),
            zernikes_rot=(rot_zern),
            offset_hex=(hexapod_offset),
            offset_tel=(tel_offset),
        )

        return results

    @classmethod
    def get_schema(cls) -> typing.Dict[str, typing.Any]:
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/LatissCWFSAlign.yaml
            title: LatissBaseAlign v1
            description: Configuration for LatissBaseAlign Script.
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
              rot:
                type: number
                default: 0.0
                description: >-
                    Rotator angle (deg). The actual definition will depend on the
                    value of rot_type.
              rot_type:
                description: >-
                  Rotator strategy. Options are:
                    Sky: Sky position angle strategy. The rotator is positioned with respect
                         to the North axis so rot=0. means y-axis is aligned with North.
                         Angle grows clock-wise.

                    SkyAuto: Same as Sky position angle but it will verify that the requested
                             angle is achievable and wrap it to a valid range.

                    Parallactic: This strategy is required for taking optimum spectra with
                                 LATISS. If set to zero, the rotator is positioned so that the
                                 y-axis (dispersion axis) is aligned with the parallactic
                                 angle.

                    PhysicalSky: This strategy allows users to select the **initial** position
                                  of the rotator in terms of the physical rotator angle (in the
                                  reference frame of the telescope). Note that the telescope
                                  will resume tracking the sky rotation.

                    Physical: Select a fixed position for the rotator in the reference frame of
                              the telescope. Rotator will not track in this mode.
                type: string
                enum: ["Sky", "SkyAuto", "Parallactic", "PhysicalSky", "Physical"]
                default: PhysicalSky
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
                    detection? This was mostly used for early WEP testing and kept
                    for possible debugging scenarios.
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
              large_defocus:
                description: >-
                    Defines a large defocus. If the measured defocus is larger than this value,
                    apply only half of correction.
                type: number
                default: 0.12
              threshold:
                 description: >-
                   Focus correction threshold. If correction is lower than this
                   value, stop correction loop.
                 type: number
                 default: 0.015
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
              camera_playlist:
                description: >-
                  Optional name a camera playlist to load before running the script.
                  This parameter is mostly designed to use for integration tests and is
                  switched off by default (e.g. null).
                anyOf:
                  - type: string
                  - type: "null"
                default: null
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.

        Raises
        ------
        RuntimeError:
            If both `find_target` and `track_target` are defined in the
            configuration.
        """

        self.target_config = types.SimpleNamespace()

        if hasattr(config, "find_target"):
            self.target_config = config.find_target

        if hasattr(config, "track_target"):
            self.target_config = config.track_target

        self.rot = config.rot
        self.rot_strategy = getattr(RotType, config.rot_type)

        self.filter = config.filter
        self.grating = config.grating

        # exposure time for the intra/extra images (in seconds)
        self.exposure_time = config.exposure_time

        self.acq_exposure_time = config.acq_exposure_time

        # offset for the intra/extra images
        self.dz = config.dz
        # delta offset for extra focal image
        self.extra_focal_offset = config.extra_focal_offset

        self.large_defocus = config.large_defocus

        self.threshold = config.threshold

        self.coma_threshold = config.coma_threshold

        self.offset_telescope = config.offset_telescope

        self.max_iter = config.max_iter

        self.reason = config.reason

        self.program = config.program

        self.take_detection_image = config.take_detection_image

        self.camera_playlist = config.camera_playlist

    async def _configure_target(self):
        """Finish configuring target.

        Raises
        ------
        `RuntimeError`
            If both `find_target` and `track_target` are provided.
        """

        if hasattr(self.target_config, "find_target") and hasattr(
            self.target_config, "track_target"
        ):
            raise RuntimeError(
                "find_target and track_target configuration sections cannot be specified together."
            )
        elif hasattr(self.target_config, "find_target"):
            self.log.debug(
                f"Finding target for cwfs @ {self.target_config.find_target}"
            )
            self.cwfs_target = await self.atcs.find_target(
                **self.target_config.find_target
            )
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None
            self.log.debug(f"Using target {self.cwfs_target} for cwfs.")
        elif hasattr(self.target_config, "track_target"):
            self.log.debug(
                f"Tracking target {self.target_config.track_target} for cwfs."
            )
            self.cwfs_target = self.target_config.track_target.get(
                "target_name", "cwfs_target"
            )
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None
            if "icrs" in self.target_config.track_target:
                self.cwfs_target_ra = self.target_config.track_target["icrs"]["ra"]
                self.cwfs_target_dec = self.target_config.track_target["icrs"]["dec"]
        else:
            self.log.debug("No target configured.")
            self.cwfs_target = None
            self.cwfs_target_ra = None
            self.cwfs_target_dec = None

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        """Sets script metadata.

        Parameters
        ----------
        metadata : `salobj.type_hints.BaseMsgType`
            Script metadata topic. The information is set on the topic
            directly.
        """
        # Estimated duration is maximum number of iterations multiplied by
        # the time it takes to take the data (2 images) plus estimation on
        # processing the data (10s), plus time it takes to take final
        # acquisition image and 60 seconds to slew to the target.
        processing_time = 10.0
        slew_time = 60.0

        metadata.duration = (
            self.max_iter
            * 2.0
            * (
                self.exposure_time
                + self.latiss.read_out_time
                + self.latiss.shutter_time
                + processing_time
            )
            + self.acq_exposure_time
            + self.latiss.read_out_time
            + self.latiss.shutter_time
            + slew_time
        )
        metadata.filter = f"{self.filter},{self.grating}"

    async def arun(self, checkpoint: bool = False) -> None:
        """Perform CWFS measurements and hexapod adjustments until the
        thresholds are reached.

        Parameters
        ----------
        checkpoint : `bool`, optional
            Should issue checkpoints (default=False)?

        Raises
        ------
        RuntimeError:
            If coordinates are malformed.
        """

        await self._configure_target()

        if self.cwfs_target is not None and self.cwfs_target_dec is None:
            if checkpoint:
                await self.checkpoint(
                    f"Slewing to object: {self.cwfs_target}, "
                    f"rot={self.rot}, rot_strategy={self.rot_strategy!r}."
                )
            await self.atcs.slew_object(
                name=self.cwfs_target,
                rot=self.rot,
                rot_type=self.rot_strategy,
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
                    f"ra = {self.cwfs_target_ra}, dec = {self.cwfs_target_dec}, "
                    f"rot = {self.rot}, rot_strategy = {self.rot_strategy!r}."
                )

            await self.atcs.slew_icrs(
                ra=self.cwfs_target_ra,
                dec=self.cwfs_target_dec,
                target_name=self.cwfs_target,
                rot=self.rot,
                rot_type=self.rot_strategy,
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
            await self.latiss.take_acq(
                self.acq_exposure_time,
                group_id=self.group_id,
                reason="DETECTION_INFOCUS"
                + ("" if self.reason is None else f"_{self.reason}"),
                program=self.program,
            )

        self.offset_total_focus = 0.0
        self.offset_total_coma_x = 0.0
        self.offset_total_coma_y = 0.0
        for i in range(self.max_iter):

            self.log.debug(f"CWFS iteration {i + 1} starting...")

            if checkpoint:
                await self.checkpoint(
                    f"[{i + 1}/{self.max_iter}]: CWFS loop starting..."
                )

            # Setting visit_id's to none so run_cwfs will take a new dataset.
            self.intra_visit_id = None
            self.extra_visit_id = None
            await self.take_intra_extra()

            results = await self.run_align()

            coma_x = results.offset_hex[0]
            coma_y = results.offset_hex[1]
            focus_offset = results.offset_hex[2]

            total_coma_offset = np.sqrt(coma_x**2.0 + coma_y**2.0)
            if (
                abs(focus_offset) < self.threshold
                and total_coma_offset < self.coma_threshold
            ):
                self.offset_total_focus += focus_offset
                self.log.info(
                    f"Focus ({focus_offset:0.3f}) and coma ({total_coma_offset:0.3f}) offsets "
                    f"inside tolerance level ({self.threshold:0.3f}). "
                    f"Total focus correction: {self.offset_total_focus:0.3f} mm. "
                    f"Total coma-x correction: {self.offset_total_coma_x:0.3f} mm. "
                    f"Total coma-y correction: {self.offset_total_coma_y:0.3f} mm."
                )
                if checkpoint:
                    await self.checkpoint(f"[{i + 1}/{self.max_iter}]: CWFS converged.")
                # Add coma offsets from previous run
                self.offset_total_coma_x += coma_x
                self.offset_total_coma_y += coma_y
                await self.hexapod_offset(focus_offset, x=coma_x, y=coma_y)
                if self.offset_telescope:
                    tel_el_offset, tel_az_offset = (
                        results.offset_tel[0],
                        results.offset_tel[1],
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
                    timeout=self.timeout_short
                )
                hexapod_position = (
                    await self.atcs.rem.athexapod.tel_positionStatus.aget(
                        timeout=self.timeout_short
                    )
                )
                self.log.info(
                    f"Hexapod LUT Datapoint - {current_target.targetName} - "
                    f"reported hexapod position is, {hexapod_position.reportedPosition}."
                )
                self.log.debug("Taking in focus image after applying final results.")
                await self.latiss.take_acq(
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
                self.offset_total_focus += focus_offset / 2.0
                self.log.warning(
                    f"Computed focus offset {focus_offset:0.3f}mm larger than "
                    f"threshold {self.large_defocus:0.3f}mm. "
                    "Applying threshold value."
                )
                if checkpoint:
                    await self.checkpoint(
                        f"[{i + 1}/{self.max_iter}]: CWFS focus error too large."
                    )
                await self.hexapod_offset(self.large_defocus)
            else:
                self.offset_total_focus += focus_offset
                self.log.info(
                    f"Applying offset: x={coma_x:0.3f}, y={coma_y:0.3f}, z={focus_offset:0.3f}."
                )
                if checkpoint:
                    await self.checkpoint(
                        f"[{i + 1}/{self.max_iter}]: CWFS applying coma and focus correction."
                    )
                self.offset_total_coma_x += coma_x
                self.offset_total_coma_y += coma_y
                await self.hexapod_offset(focus_offset, x=coma_x, y=coma_y)
                if self.offset_telescope:
                    tel_el_offset, tel_az_offset = (
                        results.offset_tel[0],
                        results.offset_tel[1],
                    )
                    self.log.info(
                        f"Applying telescope offset az/el: {tel_az_offset:0.3f}/{tel_el_offset:0.3f}."
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

    async def assert_feasibility(self) -> None:
        """Verify that the telescope and camera are in a feasible state to
        execute the script.
        """

        await self.atcs.assert_all_enabled()
        await self.latiss.assert_all_enabled()

        self.log.debug("Check ATAOS corrections are enabled.")
        ataos_corrections = await self.atcs.rem.ataos.evt_correctionEnabled.aget(
            timeout=self.atcs.fast_timeout
        )

        assert (
            ataos_corrections.hexapod
            and ataos_corrections.m1
            and ataos_corrections.atspectrograph
        ), (
            "Not all required ATAOS corrections are enabled. "
            "The following loops must all be closed (True), but are currently: "
            f"Hexapod: {ataos_corrections.hexapod}, "
            f"M1: {ataos_corrections.m1}, "
            f"ATSpectrograph: {ataos_corrections.atspectrograph}. "
            "Enable corrections with the ATAOS 'enableCorrection' command before proceeding.",
        )

    async def run(self) -> None:
        """Execute script.

        This method simply call `arun` with `checkpoint=True`.
        """
        if self.camera_playlist is not None:
            await self.checkpoint(f"Loading camera playlist: {self.camera_playlist}.")
            self.log.warning(
                f"Running script with playlist: {self.camera_playlist}. "
                "This is only suitable for test-type run and should not be used for "
                "on-sky observations. If you are on sky, check your script configuration."
            )
            await self.latiss.rem.atcamera.cmd_play.set_start(
                playlist=self.camera_playlist,
                repeat=True,
                timeout=self.latiss.fast_timeout,
            )

        await self.assert_feasibility()

        await self.arun(True)
