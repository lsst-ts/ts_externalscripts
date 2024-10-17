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

__all__ = ["LatissAcquire"]

import asyncio
import concurrent.futures
import warnings

import numpy as np
import yaml
from lsst.geom import PointD
from lsst.ts import salobj
from lsst.ts.idl.enums.ATPtg import WrapStrategy
from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.observatory.control.constants import latiss_constants
from lsst.ts.observatory.control.utils import RotType

try:
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_obs_id,
    )
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

STD_TIMEOUT = 20  # seconds


class LatissAcquire(salobj.BaseScript):
    """Perform an acquisition of a target on LATISS with the AuxTel.

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

    def __init__(self, index, add_remotes: bool = True):
        super().__init__(
            index=index,
            descr="Perform target acquisition for LATISS.",
        )

        latiss_usage = None if add_remotes else LATISSUsages.DryTest

        atcs_usage = None if add_remotes else ATCSUsages.DryTest

        self.latiss = LATISS(
            domain=self.domain, intended_usage=latiss_usage, log=self.log
        )
        self.atcs = ATCS(domain=self.domain, intended_usage=atcs_usage, log=self.log)

        self.image_in_oods_timeout = 15.0

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/auxtel/latiss_acquire_and_take_sequence.yaml
            title: LatissAcquireAndTakeSequence v1
            description: Configuration for LatissAcquireAndTakeSequence Script.
            type: object
            properties:
              object_name:
                description: An object name to be passed to the header. Required unless do_reacquire is set.
                    If the object name is query-able in SIMBAD then no coordinates are required.
                type: string

              program:
                description: Name of the program this dataset belongs to (required).
                type: string

              reason:
                description: Reason for taking the data (required).
                type: string

              object_ra:
                description: Right Ascension (RA) as a float (hours) or a sexagesimal
                    string (HH:MM:SS.S or HH MM SS.S).
                default: null
                anyOf:
                  - type: string
                  - type: number
                  - type: "null"

              object_dec:
                description: Declination (Dec) as a float (deg) or a sexagesimal
                    string (DD:MM:SS.S or DD MM SS.S).
                default: null
                anyOf:
                  - type: string
                  - type: number
                  - type: "null"

              acq_filter:
                description: Which filter to use when performing acquisition.
                type: string
                default: empty_1

              acq_grating:
                description: Which grating to use when performing acquisition.
                type: string
                default: empty_1

              acq_exposure_time:
                description: The exposure time to use when performing acquisition (sec).
                type: number
                default: 2.

              max_acq_iter:
                description: Maximum number of iterations to perform when acquiring target at a location.
                type: number
                default: 3
                minimum: 0

              target_pointing_tolerance:
                description: Position tolerance for the acquisition sequence (arcsec).
                type: number
                default: 5

              target_pointing_verification:
                description: Take a follow-up exposure to verify calculated offset was applied
                    correctly before starting sequence?
                type: boolean
                default: True

              rot_value:
                description: >-
                  Rotator position value. Actual meaning depends on rot_type.
                type: number
                default: 0

              rot_type:
                description: >-
                  Rotator strategy. Options are:
                    Sky: Sky position angle strategy. The rotator is positioned with respect
                         to the North axis so rot_angle=0. means y-axis is aligned with North.
                         Angle grows clock-wise.
                    SkyAuto: Same as sky position angle but it will verify that the requested
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
                default: Parallactic

              time_on_target:
                description: Optional parameter use to provied estimated time on target after
                    acquisition (s) to set OPTIMIZED azimuth wrap strategy. Otherwise, use default
                    MAXTIMEONTARGET azimuth wrap strategy.
                anyOf:
                  - type: "null"
                  - type: number
                    minimum: 0.0
                default: null

              estimated_slew_time:
                description: An estimative of how much time the slew to target will take (s).
                type: number
                default: 180

              do_user_final_position:
                description: Acquire on user-supplied final position. If False, will acquire
                    on grating sweet-spot. If True, user_x and user_y parameters are required.
                type: boolean
                default: False

              user_final_x:
                description: User-supplied final X position for target acquisition in detector
                    coordinates.
                anyOf:
                  - type: "null"
                  - type: number
                    minimum: 0
                default: null

              user_final_y:
                description: User-supplied final Y position for target acquisition in detector
                    coordinates.
                anyOf:
                  - type: "null"
                  - type: number
                    minimum: 0
                default: null

              do_reacquire:
                description: Perform re-acquisition of target without initial slew. Assumes target
                    is near final position.
                type: boolean
                default: False

            additionalProperties: false
            if:
              properties:
                do_reacquire:
                  const: True
              required: ["program", "reason"]
            elif:
              properties:
                object_ra:
                  const: null
                object_dec:
                  const: null
              required: ["object_name", "program", "reason"]
            else:
              required: ["object_name", "object_ra", "object_dec", "program", "reason"]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        # Instantiate BestEffortIsr -
        self.best_effort_isr = self.get_best_effort_isr()

        # instantiate the quick measurement class
        qm_config = QuickFrameMeasurementTask.ConfigClass()
        self.qm = QuickFrameMeasurementTask(config=qm_config)

        self.do_reacquire = config.do_reacquire

        if not self.do_reacquire:
            self.object_name = config.object_name

        self.object_ra = config.object_ra
        self.object_dec = config.object_dec

        # config for the single image acquisition
        self.acq_grating = config.acq_grating
        self.acq_filter = config.acq_filter
        self.acq_exposure_time = config.acq_exposure_time

        # Max number of iterations to perform when putting source in place
        self.max_acq_iter = config.max_acq_iter

        # Tolerance in arcsec for distance from main source centroid to
        # relevant sweet spot
        self.target_pointing_tolerance = config.target_pointing_tolerance
        self.target_pointing_verification = config.target_pointing_verification

        self.reason = config.reason

        self.program = config.program

        self.time_on_target = config.time_on_target

        self.estimated_slew_time = config.estimated_slew_time

        if self.time_on_target is None:
            self.time_on_target = 0.0
            self.azimuth_wrap_strategy = WrapStrategy.MAXTIMEONTARGET
        else:
            self.azimuth_wrap_strategy = WrapStrategy.OPTIMIZE

        self.rot_type = config.rot_type
        self.rot_value = config.rot_value

        self.do_user_final_position = config.do_user_final_position

        self.user_final_x = config.user_final_x
        self.user_final_y = config.user_final_y

        if self.do_user_final_position:
            assert (
                self.user_final_x is not None
            ), "user_final_x is a mandatory input when do_user_final_position=True."
            assert (
                self.user_final_y is not None
            ), "user_final_y is a mandatory input when do_user_final_position=True."
            self.target_position_x = self.user_final_x
            self.target_position_y = self.user_final_y
        else:
            (
                self.target_position_x,
                self.target_position_y,
            ) = (
                latiss_constants.sweet_spots[self.acq_grating][0],
                latiss_constants.sweet_spots[self.acq_grating][1],
            )

    def set_metadata(self, metadata):
        estimated_slew_time = 0 if self.do_reacquire else self.estimated_slew_time
        latiss_config_duration = 5
        acq_iter_overhead_duration = 5

        metadata.duration = (
            estimated_slew_time
            + latiss_config_duration
            + (self.acq_exposure_time + acq_iter_overhead_duration) * self.max_acq_iter
        )

    # TODO: move to new class as part of DM-37665
    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr()

    # TODO: move to new class as part of DM-37665
    async def get_next_image_data_id(self):
        """Return dataID of image that appears from the ATOODS CSC.

        This is meant to be called at the same time as a take image command.
        If this is called after take_image is completed, it may not receive
        the imageInOODS event.
        """

        self.log.debug(
            f"Waiting for image to arrive in OODS for a maximum of {self.image_in_oods_timeout} seconds."
        )
        in_oods = await self.latiss.rem.atoods.evt_imageInOODS.next(
            timeout=self.image_in_oods_timeout, flush=True
        )

        data_id = parse_obs_id(in_oods.obsid)
        self.log.debug(f"seq_num {data_id['seq_num']} arrived in OODS")

        return data_id

    async def find_offset(self, data_id, target_position_x, target_position_y):
        """Detects the brightest star in an image and returns the offsets
        (dx_arcsec and dy_arcsec) required to move the target to the target
        position.

        Parameters
        ----------
        data_id : `dict`
            data Id for initial exposure with target initial position.
        target_position_x : `float`
            desired final X position in detector coordinates.
        target_position_y : `float`
            desired final X position in detector coordinates.

        Returns
        -------
        dx_arcsec, dy_arcsec: `float`, `float`
            offsets (arcsec) required to translate target from detected
            position to desired final position
        """
        exp = await get_image(
            data_id,
            self.best_effort_isr,
            timeout=self.acq_exposure_time + STD_TIMEOUT,
        )

        # Find brightest star in image.
        loop = asyncio.get_event_loop()
        executor = concurrent.futures.ThreadPoolExecutor()
        result = await loop.run_in_executor(executor, self.qm.run, exp)

        # Verify a result was achieved, if not raise the exception.
        if not result.success:
            raise RuntimeError("Centroid finding algorithm was unsuccessful.")

        current_position = PointD(
            result.brightestObjCentroid[0], result.brightestObjCentroid[1]
        )

        target_position = PointD(target_position_x, target_position_y)

        # Find offsets to desired position
        self.log.debug(
            f"Current brightest target position is {current_position} whereas the "
            f"target position is [{self.target_position_x},{self.target_position_y}]"
        )

        dx_arcsec, dy_arcsec = calculate_xy_offsets(current_position, target_position)
        return dx_arcsec, dy_arcsec

    async def execute_acquisition(self, target_position_x, target_position_y):
        """Perform acquisition of target.

        Will iteratively measure position of
        brightest object in image, calculate offsets required to translate to
        target_position, apply offsets, take a new image, measure position of
        brightest object in new image and check that it has arrived at target
        position within tolerance. Iterations will continue until either the
        brightest object has arrived at position within tolerance or
        configurable max acq iters parameter is met.

        Parameters
        ----------
        target_position_x : `float`
            desired final X position in detector coordinates.
        target_position_y : `float`
            desired final X position in detector coordinates.
        """

        self.log.debug(
            "Beginning Acquisition Iterative Loop, with a maximum amount of "
            f"iterations set to {self.max_acq_iter}"
        )
        _success = self.max_acq_iter == 0
        for iter_num in range(self.max_acq_iter):
            self.log.debug(
                f"\nStarting iteration number {iter_num + 1}, with a "
                f"maximum of {self.max_acq_iter}"
            )

            self.latiss.rem.atoods.evt_imageInOODS.flush()
            tmp = await self.latiss.take_acq(
                exptime=self.acq_exposure_time,
                n=1,
                group_id=self.group_id,
                reason=self.reason,
                program=self.program,
            )
            data_id = await self.get_next_image_data_id()
            self.log.debug(
                f"Take Object returned {tmp}. Now waiting for image to land in OODS"
            )

            dx_arcsec, dy_arcsec = await self.find_offset(
                data_id, target_position_x, target_position_y
            )

            dr_arcsec = np.sqrt(dx_arcsec**2 + dy_arcsec**2)

            self.log.debug(
                f"Calculated offsets [dx,dy] are [{dx_arcsec:0.2f}, {dy_arcsec:0.2f}] arcsec as calculated"
                f" from sequence number {data_id['seq_num']} on Observation Day of {data_id['day_obs']}"
            )

            # Check if star is in place, if so then we're done
            if dr_arcsec < self.target_pointing_tolerance:
                self.log.info(
                    "Acquisition completed successfully."
                    f"Current radial pointing error of {dr_arcsec:0.2f} arcsec is within the tolerance "
                    f"of {self.target_pointing_tolerance} arcsec. "
                )
                _success = True
                break
            else:
                self.log.info(
                    f"Current radial pointing error of {dr_arcsec:0.2f} arcsec exceeds the tolerance"
                    f" of {self.target_pointing_tolerance} arcsec. Applying x/y offset to telescope pointing."
                )

                # Use persistent = False otherwise when we switch gratings
                # it may keep an offset we no longer want
                await self.atcs.offset_xy(
                    x=dx_arcsec, y=dy_arcsec, relative=True, persistent=False
                )

            self.log.debug(
                f"At end of iteration loop {iter_num+1}, success is {_success}."
            )

        # Check that maximum number of iterations for acquisition
        # was not reached
        if not _success:
            raise RuntimeError(
                f"Failed to acquire star on target after {iter_num} images."
            )

    async def latiss_slew_and_acquire(self):
        """Performs slew to new target specified in configuration and initiates
        performs acquisition loop.

        A final, verification image is taken if
        configured.
        """
        if self.object_ra and self.object_dec:
            self.log.debug("Using slew_icrs (object coordinate designation).")
            _slew_coro = self.atcs.slew_icrs(
                self.object_ra,
                self.object_dec,
                target_name=self.object_name,
                rot=self.rot_value,
                rot_type=getattr(RotType, self.rot_type),
                slew_timeout=240,
                az_wrap_strategy=self.azimuth_wrap_strategy,
                time_on_target=self.time_on_target,
            )
        else:
            self.log.debug("Using slew_object (object name designation).")
            _slew_coro = self.atcs.slew_object(
                name=self.object_name,
                rot=self.rot_value,
                rot_type=getattr(RotType, self.rot_type),
                slew_timeout=240,
                az_wrap_strategy=self.azimuth_wrap_strategy,
                time_on_target=self.time_on_target,
            )

        tmp, data = await asyncio.gather(
            _slew_coro,
            self.latiss.setup_atspec(grating=self.acq_grating, filter=self.acq_filter),
        )

        # Perform acquisition loop to center target.
        await self.execute_acquisition(self.target_position_x, self.target_position_y)

        # Verify with another image that we're on target?
        if self.target_pointing_verification:
            await self.latiss.take_acq(
                exptime=self.acq_exposure_time,
                n=1,
                group_id=self.group_id,
                reason=self.reason,
                program=self.program,
            )
        else:
            self.log.debug(
                "Skipping additional image to verify offset was applied correctly as "
                f"target_pointing_verification is set to {self.target_pointing_verification}"
            )

    async def latiss_reacquire(self):
        """Initiates acquisition loop assuming telescope is already in
        position.

        A final, verification image is taken if configured.
        """

        # Check if we need to update latiss setup
        current_atspec_setup = await self.latiss.get_setup()
        if (
            current_atspec_setup[0] != self.acq_filter
            or current_atspec_setup[1] != self.acq_grating
        ):
            await self.latiss.setup_atspec(
                grating=self.acq_grating, filter=self.acq_filter
            )

        await self.execute_acquisition(self.target_position_x, self.target_position_y)

        # Verify with another image that we're on target?
        if self.target_pointing_verification:
            await self.latiss.take_acq(
                exptime=self.acq_exposure_time,
                n=1,
                group_id=self.group_id,
                reason=self.reason,
                program=self.program,
            )
        else:
            self.log.debug(
                f"Skipping additional image to verify offset was applied correctly as "
                f"target_pointing_verification is set to {self.target_pointing_verification}"
            )

    async def assert_feasibility(self) -> None:
        """Verify that the telescope and camera are in a feasible state to
        execute the script.
        """

        await self.atcs.assert_all_enabled()
        await self.latiss.assert_all_enabled()
        await self.atcs.assert_ataos_corrections_enabled()

    async def arun(self, checkpoint=False):
        await self.assert_feasibility()

        if checkpoint:
            await self.checkpoint("Beginning Target Acquisition")
        self.log.debug("Beginning target acquisition")

        if self.do_reacquire:
            await self.latiss_reacquire()
        else:
            await self.latiss_slew_and_acquire()

    async def run(self):
        """"""
        await self.arun(checkpoint=True)
