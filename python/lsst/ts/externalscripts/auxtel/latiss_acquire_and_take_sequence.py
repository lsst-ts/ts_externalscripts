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

__all__ = ["LatissAcquireAndTakeSequence"]

import asyncio
import collections
import warnings

import numpy as np
import yaml
import concurrent.futures

from lsst.geom import PointD
from lsst.ts import salobj
from lsst.ts.observatory.control.auxtel import ATCS, LATISS
from lsst.ts.observatory.control.constants import latiss_constants
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.utils import format_as_list
from lsst.ts.idl.enums.ATPtg import WrapStrategy

try:
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_obs_id,
    )
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr

    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

STD_TIMEOUT = 20  # seconds


class LatissAcquireAndTakeSequence(salobj.BaseScript):
    """
    Perform an acquisition of a target on LATISS with the AuxTel.
    This sets up the instrument and puts the brightest target on a
    specific pixel, then takes a sequence of exposures for a given
    set of instrument configurations.

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
            descr="Perform target acquisition and data taking"
            " for LATISS instrument.",
        )

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
        # Set timeout
        self.cmd_timeout = 30  # [s]

        # Suppress verbosity
        self.silent = silent

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/auxtel/latiss_acquire_and_take_sequence.yaml
            title: LatissAcquireAndTakeSequence v1
            description: Configuration for LatissAcquireAndTakeSequence Script.
            type: object
            properties:
              do_acquire:
                description: Perform target acquisition?
                type: boolean
                default: False

              do_take_sequence:
                description: Take sequence of data on target?
                type: boolean
                default: False

              object_name:
                description: An object name to be passed to the header. If the object name is query-able
                    in SIMBAD then no coordinates are required.
                type: string

              object_ra:
                description: Right Ascension (RA) as a string
                default: null
                anyOf:
                    - type: string
                    - type: "null"

              object_dec:
                description: Declination (Dec) as a string
                default: null
                anyOf:
                    - type: string
                    - type: "null"

              manual_focus_offset:
                description: Applies manual focus offset after the slew. This
                    is temporary in order to observe low-altitude stars until
                    the ATAOS LUTs improve.
                type: number
                default: 0.0

              acq_filter:
                description: Which filter to use when performing acquisition.
                type: string
                default: FELH0600

              acq_grating:
                description: Which grating to use when performing acquisition. Must use
                             empty_1 for now.
                type: string
                default: empty_1

              acq_exposure_time:
                description: The exposure time to use when performing acquisition (sec).
                type: number
                default: 2.

              max_acq_iter:
                description: Max number of iterations to perform when acquiring target at a location.
                             Only used if do_acquire=True.
                type: number
                default: 3
                minimum: 0

              target_pointing_tolerance:
                description: Number of arcsec from source to desired position to consider good enough.
                type: number
                default: 5

              target_pointing_verification:
                description: Take a follow-up exposure to verify calculated offset was applied
                    correctly before starting sequence?
                type: boolean
                default: True

              filter_sequence:
                description: Filters for exposure sequence. If a single value is specified then
                   the same filter is used for each exposure.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: string
                  - type: string
                default: empty_1

              grating_sequence:
                description: Gratings for exposure sequence. If a single value is specified then
                   the same grating is used for each exposure.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: string
                  - type: string
                default: empty_1

              exposure_time_sequence:
                description: Exposure times for exposure sequence (sec). Each exposure requires
                   a specified exposure time.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: number
                      minimum: 0
                  - type: number
                    minimum: 0
                default: 2.

              time_on_target:
                description: Override the automatically calculated time_on_target value used
                    to optimize the telescope cable wrap positions.
                    Set to null (default) to have it calculated automatically.

                anyOf:
                  - type: "null"
                  - type: number
                    minimum: 0.0
                default: null

              do_pointing_model:
                description: Adjust star position (sweet spot) to use boresight. Save datapoint
                    when on target.
                type: boolean
                default: False

              do_blind_offset:
                description: Perform blind offset during the slew. Useful to reduce iterations
                    so long as pointing model is accurate.
                type: boolean
                default: True

              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null

              program:
                description: >-
                  Optional name of the program this dataset belongs to.
                anyOf:
                  - type: string
                  - type: "null"
                default: null

            additionalProperties: false
            if:
              properties:
                object_ra:
                  const: null
                object_dec:
                  const: null
              required: ["object_name"]
            else:
              required: ["object_name", "object_ra", "object_dec"]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        # Instantiate BestEffortIsr
        self.best_effort_isr = self.get_best_effort_isr()

        # Which processes to perform
        self.do_acquire = config.do_acquire
        self.do_take_sequence = config.do_take_sequence
        # Do pointing file generation?
        self.do_pointing_model = config.do_pointing_model
        # Perform blind offsetting?
        self.do_blind_offset = config.do_blind_offset

        # Object name
        assert config.object_name is not None, "An object name is a mandatory input"

        self.object_name = config.object_name
        self.object_ra = config.object_ra
        self.object_dec = config.object_dec

        # config for the single image acquisition
        self.acq_grating = config.acq_grating
        self.acq_filter = config.acq_filter
        self.acq_exposure_time = config.acq_exposure_time
        self.manual_focus_offset = config.manual_focus_offset
        self.manual_focus_offset_applied = False

        # Max number of iterations to perform when putting source in place
        self.max_acq_iter = config.max_acq_iter

        # Tolerance in arcsec for distance from main source centroid to
        # relevant sweet spot
        self.target_pointing_tolerance = config.target_pointing_tolerance
        self.target_pointing_verification = config.target_pointing_verification

        self.acq_visit_config = (
            self.acq_filter,
            self.acq_exposure_time,
            self.acq_grating,
        )

        # make a list of tuples from the filter, exptime and grating lists
        _recurrences = (
            len(config.exposure_time_sequence)
            if isinstance(config.exposure_time_sequence, collections.Iterable)
            else 1
        )

        self.visit_configs = [
            (f, e, g)
            for f, e, g in zip(
                format_as_list(config.filter_sequence, _recurrences),
                format_as_list(config.exposure_time_sequence, _recurrences),
                format_as_list(config.grating_sequence, _recurrences),
            )
        ]

        self.reason = config.reason

        if self.reason is None:
            warnings.warn(
                "Reason not specified! Consider specifying the 'reason' for "
                "this observation. it helps reducing the data aftwards. Running "
                "without specifying a 'reason' will stop working in the future!",
                DeprecationWarning,
            )

        self.program = config.program

        if self.program is None:
            warnings.warn(
                "Program not specified! Consider specifying the 'program' for "
                "this observation, it helps reducing the data aftwards. Running "
                "without specifying a 'program' will stop working in the future!",
                DeprecationWarning,
            )

        self.time_on_target = config.time_on_target
        self.time_on_target = (
            self.compute_time_on_target()
            if config.time_on_target is None
            else config.time_on_target
        )

    def compute_time_on_target(self):
        """Determine the amount of time spent on target so the rotator position
        can be optimized. Assumed slew time is 3 minutes, and that the read,
        calculation, and offset totals 20s.

        Returns
        -------
        time_on_target: float
            Estimate of time on target in seconds.
        """

        time_on_target = 180 + self.max_acq_iter * (self.acq_exposure_time + 20)
        if self.do_take_sequence:
            nexp = len(self.visit_configs)
            visit_exptime_total = 0.0
            for (filt, exptime, grating) in self.visit_configs:
                visit_exptime_total += exptime

            time_on_target += visit_exptime_total
            # assume 5s for readout and instrument reconfiguration
            # for each exposure
            time_on_target += nexp * 5
        self.log.debug(
            f"Assuming a time_on_target of {time_on_target/60:0.2f} minutes."
        )

        return time_on_target

    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr()

    # This bit is required for ScriptQueue
    # Does the calculation below need acquisition times?
    # I'm not quite sure what the metadata.filter bit is used for...
    def set_metadata(self, metadata):
        metadata.duration = 300
        filters, gratings, exptime_total = set(), set(), 0
        for (filt, exptime, grating) in self.visit_configs:
            exptime_total += exptime
            filters.add(filt)
            gratings.add(grating)
        metadata.filter = f"{filters},{gratings}"

    async def get_next_image_data_id(self, timeout=STD_TIMEOUT, flush=True):
        """Return dataID of image that appears from the ATOODS CSC.
        This is meant to be called at the same time as a take image command.
        If this is called after take_image is completed, it may not receive
        the imageInOODS event.

        Inputs:
        timeout: `float`
            Amount of time to wait for image to arrive.
        """

        self.log.info(
            f"Waiting for image to arrive in OODS for a maximum of {timeout} seconds."
        )
        in_oods = await self.latiss.rem.atoods.evt_imageInOODS.next(
            timeout=timeout, flush=flush
        )

        data_id = parse_obs_id(in_oods.obsid)
        self.log.info(f"seq_num {data_id['seq_num']} arrived in OODS")

        return data_id

    async def latiss_acquire(self):

        if self.do_pointing_model:
            target_position = latiss_constants.boresight
        else:
            target_position = latiss_constants.sweet_spots[self.acq_grating]

        # Find offsets to desired detector position, calculate blind offset
        # and send as part of the slew command
        self.log.info(f"Performing blind offset set to {self.do_blind_offset}")
        if self.do_blind_offset:
            current_position = latiss_constants.boresight

            dx_arcsec, dy_arcsec = calculate_xy_offsets(
                current_position, target_position
            )
            self.log.debug(
                f"After slew, the target should be at the boresight [{current_position}] whereas the "
                f"target position is {target_position}. Blindly offsetting"
                f" [{dx_arcsec:0.1f}, {dy_arcsec:0.1f}] arcsec to this position."
            )
        else:
            dx_arcsec, dy_arcsec = 0.0, 0.0

        # Setup instrument and telescope
        # The following code sets up the instrument and slews the telescope
        # simultaneously.

        # if coordinates are provided then use those
        if self.object_ra and self.object_dec:
            self.log.debug("Using slew_icrs (object coordinate designation)")
            _slew_coro = self.atcs.slew_icrs(
                self.object_ra,
                self.object_dec,
                target_name=self.object_name,
                rot_type=RotType.Parallactic,
                slew_timeout=240,
                az_wrap_strategy=WrapStrategy.OPTIMIZE,
                time_on_target=self.time_on_target,
                offset_x=dx_arcsec,
                offset_y=dy_arcsec,
            )
        else:
            self.log.debug("Using slew_object (object name designation)")
            _slew_coro = self.atcs.slew_object(
                name=self.object_name,
                rot_type=RotType.Parallactic,
                slew_timeout=240,
                az_wrap_strategy=WrapStrategy.OPTIMIZE,
                time_on_target=self.time_on_target,
                offset_x=dx_arcsec,
                offset_y=dy_arcsec,
            )

        tmp, data = await asyncio.gather(
            _slew_coro,
            self.latiss.setup_atspec(grating=self.acq_grating, filter=self.acq_filter),
        )

        # Apply manual focus offset if required
        if self.manual_focus_offset != 0.0 and not self.manual_focus_offset_applied:
            self.log.debug(
                "Applying manual focus offset of " f"{self.manual_focus_offset}"
            )
            await self.atcs.rem.ataos.cmd_offset.set_start(z=self.manual_focus_offset)
            self.manual_focus_offset_applied = True

        self.log.debug(
            "Beginning Acquisition Iterative Loop, with a maximum amount of "
            f"iterations set to {self.max_acq_iter}"
        )
        iter_num = 0
        _success = False if self.max_acq_iter > 0 else True
        for iter_num in range(self.max_acq_iter):
            # Take image
            self.log.debug(
                f"\nStarting iteration number {iter_num + 1}, with a "
                f"maximum of {self.max_acq_iter}"
            )

            # Was not catching event from OODS in time without timing out
            self.latiss.rem.atoods.evt_imageInOODS.flush()
            tmp = await self.latiss.take_acq(
                exptime=self.acq_exposure_time,
                n=1,
                group_id=self.group_id,
                reason=self.reason,
                program=self.program,
            )
            data_id = await self.get_next_image_data_id(
                timeout=self.acq_exposure_time + STD_TIMEOUT, flush=False
            )
            self.log.debug(f"Take Object returned {tmp}")
            self.log.debug("Now waiting for image to land in OODS")

            exp = await get_image(
                data_id,
                self.best_effort_isr,
                timeout=self.acq_exposure_time + STD_TIMEOUT,
            )

            # Find brightest star
            loop = asyncio.get_event_loop()
            executor = concurrent.futures.ThreadPoolExecutor()
            result = await loop.run_in_executor(executor, self.qm.run, exp)
            # Verify a result was achieved, if not then remove focus
            # offset before raising the exception
            if not result.success:
                # Remove the focus offset if it was applied before
                # raising an exception
                if self.manual_focus_offset_applied:
                    self.log.debug(
                        "Removing manual focus offset of "
                        f"{self.manual_focus_offset} before raising error"
                    )
                    await self.atcs.rem.ataos.cmd_offset.set_start(
                        z=-self.manual_focus_offset
                    )
                    self.manual_focus_offset_applied = False
                raise RuntimeError("Centroid finding algorithm was unsuccessful.")

            current_position = PointD(
                result.brightestObjCentroid[0], result.brightestObjCentroid[1]
            )

            # Find offsets to desired position
            self.log.debug(
                f"Current brightest target position is {current_position} whereas the "
                f"target position is {target_position}"
            )

            dx_arcsec, dy_arcsec = calculate_xy_offsets(
                current_position, target_position
            )

            dr_arcsec = np.sqrt(dx_arcsec ** 2 + dy_arcsec ** 2)

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
                    f" of {self.target_pointing_tolerance} arcsec."
                )

            # Offset telescope, using persistent offsets
            self.log.info("Applying x/y offset to telescope pointing.")

            # Use persistent = False otherwise when we switch gratings
            # it may keep an offset we no longer want
            await self.atcs.offset_xy(
                dx_arcsec, dy_arcsec, relative=True, persistent=False
            )
            self.log.debug(
                f"At end of iteration loop, success is {_success}. So moving to next iteration"
            )

        # Check that maximum number of iterations for acquisition
        # was not reached
        if not _success:
            self.log.debug(
                "Failed to acquire star on target after "
                f"{iter_num} images. Removing focus offset and "
                "raising an exception"
            )
            # Remove the focus offset if only an acquisition is performed
            if self.manual_focus_offset_applied:
                self.log.debug(
                    "Removing manual focus offset of "
                    f"{self.manual_focus_offset} in after acquisition"
                )
                await self.atcs.rem.ataos.cmd_offset.set_start(
                    z=-self.manual_focus_offset
                )
                self.manual_focus_offset_applied = False

            raise RuntimeError(
                f"Failed to acquire star on target after {iter_num} images."
            )

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

        # Update pointing model
        if self.do_pointing_model:
            self.log.info("Adding datapoint to pointing model")
            await self.atcs.add_point_data()

        # Remove the focus offset if only an acquisition is performed
        if self.manual_focus_offset_applied and not self.do_take_sequence:
            self.log.debug(
                "Removing manual focus offset of "
                f"{self.manual_focus_offset} in after acquisition"
            )
            await self.atcs.rem.ataos.cmd_offset.set_start(z=-self.manual_focus_offset)
            self.manual_focus_offset_applied = False

    async def latiss_take_sequence(self, silent=True):
        """Take the sequence of images as defined in visit_configs."""

        nexp = len(self.visit_configs)

        for i, (filt, exptime, grating) in enumerate(self.visit_configs):

            # Check if a manual focus offset is required
            if self.manual_focus_offset != 0.0 and not self.manual_focus_offset_applied:
                self.log.debug(
                    "Applying manual focus offset of "
                    f"{self.manual_focus_offset} in latiss_take_sequence"
                )
                await self.atcs.rem.ataos.cmd_offset.set_start(
                    z=self.manual_focus_offset
                )
                self.manual_focus_offset_applied = True

            # Focus and pointing offsets will be made automatically
            # by the TCS upon filter/grating changes

            # Take an image
            await self.latiss.take_object(
                exptime=exptime,
                n=1,
                filter=filt,
                grating=grating,
                group_id=self.group_id,
                reason=self.reason,
                program=self.program,
            )

            self.log.info(
                f"Completed exposure {i + 1} of {nexp}. Exptime = {exptime:6.1f}s,"
                f" filter={filt}, grating={grating})"
            )

        # Remove the focus offset if applied
        if self.manual_focus_offset_applied:
            self.log.debug(
                "Removing manual focus offset of "
                f"{self.manual_focus_offset} in after acquisition"
            )
            await self.atcs.rem.ataos.cmd_offset.set_start(z=-self.manual_focus_offset)
            self.manual_focus_offset_applied = False

    async def arun(self, checkpoint=False):
        if self.do_acquire:
            if checkpoint:
                await self.checkpoint("Beginning Target Acquisition")
            self.log.debug("Beginning target acquisition")
            await self.latiss_acquire()

        if self.do_take_sequence:
            self.log.debug("Beginning taking data for target sequence")
            if checkpoint:
                await self.checkpoint("Beginning taking data for target sequence")
            try:
                await self.latiss_take_sequence()
            except Exception as e:
                self.log.exception("Exception from latiss_take_sequence()")
                raise e
            finally:
                self.log.debug("Latiss_acquire_and_take_sequence script completed\n")

    async def run(self):
        """"""
        await self.arun(checkpoint=True)
