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
import collections.abc
import warnings

import lsst.daf.persistence as dafPersist
import numpy as np
import yaml
import concurrent.futures
from astropy import time as astropytime
from lsst.geom import PointD
from lsst.ts import salobj
from lsst.ts.observatory.control.auxtel import ATCS, LATISS
from lsst.ts.observatory.control.constants import latiss_constants
from lsst.ts.observatory.control.utils import RotType

from lsst.ts.standardscripts.utils import format_as_list

try:
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_obs_id,
    )
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

STD_TIMEOUT = 10  # seconds


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

    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, silent=False):

        super().__init__(
            index=index,
            descr="Perform target acquisition and data taking"
            " for LATISS instrument.",
        )

        self.atcs = ATCS(self.domain, log=self.log)
        self.latiss = LATISS(self.domain, log=self.log)
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
                default: True

              do_take_sequence:
                description: Take sequence of data on target?
                type: boolean
                default: True

              object_name:
                description: SIMBAD query-able object name
                type: string

              manual_focus_offset:
                description: Applies manual focus offset after the slew. This
                    is temporary in order to observe low-altitude stars until
                    the ATAOS LUTs improve.
                type: number
                default: 0.0

              acq_filter:
                description: Which filter to use when performing acquisition. Must use
                             filter = BG40 for now
                type: string
                default: BG40

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
                minimum: 1

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

              dataPath:
                description: Path to the butler data repository.
                type: string
                default: /project/shared/auxTel/

              doPointingModel:
                description: Adjust star position (sweet spot) to use boresight
                type: boolean
                default: False

            additionalProperties: false
            required: [object_name]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        # butler data path
        self.dataPath = config.dataPath

        # Instantiate the butler
        self.butler = dafPersist.Butler(self.dataPath)

        # Which processes to perform
        self.do_acquire = config.do_acquire
        self.do_take_sequence = config.do_take_sequence

        # Object name
        assert config.object_name is not None
        self.object_name = config.object_name

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

    # This bit is required for ScriptQueue
    # Does the calculation below need acquisition times?
    # I'm not quite sure what the metadata.filter bit is used for...
    def set_metadata(self, metadata):
        metadata.duration = 300
        filters, gratings, expTimeTotal = set(), set(), 0
        for (filt, expTime, grating) in self.visit_configs:
            expTimeTotal += expTime
            filters.add(filt)
            gratings.add(grating)
        metadata.filter = f"{filters},{gratings}"

    async def get_next_image_data_id(self, timeout=STD_TIMEOUT, flush=True):
        """Return dataID of image that appears from the ATArchiver CSC.
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
        in_oods = await self.latiss.rem.atarchiver.evt_imageInOODS.next(
            timeout=timeout, flush=flush
        )

        day_obs, seq_num = parse_obs_id(in_oods.obsid)[-2:]
        self.log.info(f"seqNum {seq_num} arrived in OODS")

        data_id = dict(dayObs=day_obs, seqNum=seq_num)

        return data_id

    async def latiss_acquire(self, doPointingModel=False):

        if doPointingModel:
            target_position = latiss_constants.boresight
        else:
            target_position = latiss_constants.sweet_spots[self.acq_grating]

        # get filter/disperser currently in the beam
        (
            current_filter,
            current_grating,
            current_stage_pos,
        ) = await self.latiss.get_setup()

        # Is the atspectrograph Correction in the ATAOS running?
        corr = await self.atcs.rem.ataos.evt_correctionEnabled.aget(
            timeout=self.cmd_timeout
        )

        # Setup instrument and telescope
        # Following code requires persistent offsets to be functional, but
        # that's not yet the case therefore this will result in a race
        # condition where the pointing offsets might be wiped out.
        # await asyncio.gather(
        #     self.atcs.slew_object(name=self.object_name,
        #     rot=rot_type=RotType.Parallactic, slew_timeout=240)
        #     self.latiss.setup_instrument(grating=self.acq_grating,
        #     filter=self.acq_filter),
        # )

        # Slew and setup in series for now
        # set rot_type to align to paralactic angle
        await self.atcs.slew_object(
            name=self.object_name, rot_type=RotType.Parallactic, slew_timeout=240
        )
        # Apply manual focus offset if required
        if self.manual_focus_offset != 0.0 and not self.manual_focus_offset_applied:
            self.log.debug(
                "Applying manual focus offset of " f"{self.manual_focus_offset}"
            )
            await self.atcs.rem.ataos.cmd_offset.set_start(z=self.manual_focus_offset)
            self.manual_focus_offset_applied = True

        # Check if a new instrument configuration is required
        _new_instrument_required = (self.acq_filter != current_filter) or (
            self.acq_grating != current_grating
        )
        self.log.debug(f"Instrument setup required: {_new_instrument_required}")
        if _new_instrument_required:
            self.log.debug(
                f"Must load new filter {self.acq_filter} or grating {self.acq_grating}"
            )

            if corr.atspectrograph:
                # If so, then flush correction events for confirmation of
                # corrections
                self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.flush()
                self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.flush()

        # Once persistent offsets are working this line should be removed
        # and the slew+setup should be performed asynchronously as seen
        # in the asyncio.gather statement above.
        await self.latiss.setup_instrument(
            grating=self.acq_grating, filter=self.acq_filter
        )

        # If ATAOS is running wait for adjustments to complete before
        # moving on.
        if corr.atspectrograph and _new_instrument_required:
            self.log.debug(
                "Verifying LATISS configuration is incorporated into ATAOS offsets"
            )
            # If so, then flush correction events for confirmation of
            # corrections
            # FIXME
            try:
                _evt1 = await self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.next(
                    timeout=self.cmd_timeout, flush=False
                )
                self.log.debug(
                    f"evt_atspectrographCorrectionStarted from line 373 is {_evt1}"
                )
                _evt2 = await self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.next(
                    timeout=self.cmd_timeout, flush=False
                )
                self.log.debug(
                    f"evt_atspectrographCorrectionCompleted from line 377 is {_evt2}"
                )
            except asyncio.TimeoutError:
                self.log.debug(
                    f"Caught an exception waiting for atspectrograph correction going"
                    f" from current filter {current_filter} to {self.acq_filter} and current "
                    f"grating of {current_grating} to {self.acq_grating} "
                )
            # FIXME: add sleep to test why we're exposing during offset
            self.log.debug("sleeping for grating offset correction")
            await asyncio.sleep(2.0)

        self.log.info(
            "Entering Acquisition Iterative Loop, with a maximum amount of "
            f"iterations set to {self.max_acq_iter}"
        )
        iter_num = 0
        while iter_num < self.max_acq_iter:
            # Take image
            self.log.debug(f"Starting iteration number {iter_num + 1}")
            tmp, data_id = await asyncio.gather(
                self.latiss.take_object(exptime=self.acq_exposure_time, n=1),
                self.get_next_image_data_id(
                    timeout=self.acq_exposure_time + STD_TIMEOUT
                ),
            )

            exp = await get_image(
                data_id,
                datapath=self.dataPath,
                timeout=self.acq_exposure_time + STD_TIMEOUT,
                runBestEffortIsr=True,
            )

            # Find brightest star
            try:
                loop = asyncio.get_event_loop()
                executor = concurrent.futures.ThreadPoolExecutor()
                result = await loop.run_in_executor(executor, self.qm.run, exp)
            except RuntimeError:
                # FIXME: Patrick - deal with a failure to find the source here
                pass  # and remove this
                # Note that the source finding should be made a function

            current_position = PointD(
                result.brightestObjCentroid[0], result.brightestObjCentroid[1]
            )

            # Find offsets
            self.log.debug(
                f"Current brightest target position is {current_position} whereas the"
                f"Target position is {target_position}"
            )

            dx_arcsec, dy_arcsec = calculate_xy_offsets(
                current_position, target_position
            )

            dr_arcsec = np.sqrt(dx_arcsec ** 2 + dy_arcsec ** 2)

            self.log.info(
                f"Calculated offsets [dx,dy] are [{dx_arcsec:0.2f}, {dy_arcsec:0.2f}] arcsec as calculated"
                f" from sequence number {data_id['seqNum']} on dayObs of {data_id['dayObs']}"
            )

            # Check if star is in place, if so then we're done
            if dr_arcsec < self.target_pointing_tolerance:
                self.log.info(
                    f"Current radial pointing error of {dr_arcsec:0.2f} arcsec is within the tolerance "
                    f"of {self.target_pointing_tolerance} arcsec. "
                    "Acquisition completed."
                )
                break
            else:
                self.log.info(
                    f"Current radial pointing error of {dr_arcsec:0.2f} arcsec exceeds the tolerance"
                    f" of {self.target_pointing_tolerance} arcsec."
                )

            # Ask user if we want to apply the correction?
            await self.checkpoint(
                f"Apply the calculated [x,y] correction of  [{dx_arcsec:0.2f}, {dy_arcsec:0.2f}] arcsec?"
            )
            # Offset telescope, using persistent offsets
            self.log.info("Applying x/y offset to telescope pointing.")

            # FIXME: ARBITRARILY ADDING NEGATIVE SIGN IN X-axis
            # Fix requires ATCS class rotation matrix for offset_xy to be
            # implemented
            await self.atcs.offset_xy(-dx_arcsec, dy_arcsec, persistent=True)
            # Mount not sending in-position event properly
            self.log.debug("sleeping for mount in-position issue correction")
            await asyncio.sleep(3)

            # Verify with another image that we're on target?
            if not self.target_pointing_verification:
                self.log.info(
                    f"Skipping additional image to verify offset was applied correctly as "
                    f"target_pointing_verification is set to {self.target_pointing_verification}"
                )
                break

            self.log.debug("Starting next iteration of acquisition sequence.\n")
            iter_num += 1

        else:

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

        # Update pointing model
        if doPointingModel:
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
        group_id = astropytime.Time.now().tai.isot
        for i, (filt, expTime, grating) in enumerate(self.visit_configs):

            await self.checkpoint(
                f"Performing image number {i} of {len(self.visit_configs)} "
                "of science sequence"
            )

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

            # get current filter/disperser
            (
                current_filter,
                current_grating,
                current_stage_pos,
            ) = await self.latiss.get_setup()

            # Check if a new configuration is required
            _new_instrument_required = (filt != current_filter) or (
                grating != current_grating
            )

            if _new_instrument_required:
                self.log.debug(f"Must load new filter {filt} or grating {grating}")

                # Is the atspectrograph Correction in the ATAOS running?
                corr = await self.atcs.rem.ataos.evt_correctionEnabled.aget(
                    timeout=self.cmd_timeout
                )
                if corr.atspectrograph:
                    # If so, then flush correction events for confirmation
                    # of corrections
                    self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.flush()
                    self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.flush()

                # Setup the instrument with the new configuration
                await self.latiss.setup_instrument(filter=filt, grating=grating)

                # If ATAOS is running wait for adjustments to complete before
                # moving on.
                if corr.atspectrograph:
                    # If so, then flush correction events for confirmation of
                    # corrections
                    self.log.debug(
                        "Waiting for ATAOS events saying correction " "started/finished"
                    )
                    # FIXME: Have to be looking at offsets not filters. config
                    #  may have a filter/grating with no offset
                    try:
                        _evt1 = await self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.next(
                            flush=False, timeout=self.cmd_timeout
                        )
                        self.log.debug(
                            f"evt_atspectrographCorrectionStarted from line 559 is {_evt1}"
                        )
                        _evt2 = await self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.next(
                            flush=False, timeout=self.cmd_timeout
                        )
                        self.log.debug(
                            f"evt_atspectrographCorrectionCompleted from line 563 is {_evt2}"
                        )
                    except asyncio.TimeoutError:
                        self.log.debug(
                            f"Caught an exception waiting for atspectrograph correction going"
                            f" from current filter {current_filter} to {filt} and current "
                            f"grating of {current_grating} to {grating} "
                        )
                        pass
                    # FIXME: add sleep to test why we're exposing during offset
                    self.log.debug("sleeping for grating offset correction")
                    await asyncio.sleep(2.0)
                    self.log.debug("ATAOS events arrived")

            # Take an image
            await self.latiss.take_object(exptime=expTime, n=1, group_id=group_id)

            self.log.info(
                f"Completed exposure {i + 1} of {nexp}. Exptime = {expTime:6.1f}s,"
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

    async def run(self):
        """"""
        if self.do_acquire:
            await self.checkpoint("Beginning Target Acquisition")
            self.log.debug("Beginning target acquisition")
            await self.latiss_acquire()
            await self.checkpoint("Acquisition Completed")

        if self.do_take_sequence:
            # Do we want to put the instrument back to the original state?
            # I don't think so since it'll add overhead we may not want.
            # The offsetting of focus etc is now being done
            # automatically...

            self.log.debug("Beginning taking data for target sequence")
            await self.checkpoint("Beginning taking data for target sequence")
            try:
                await self.latiss_take_sequence()
                self.checkpoint("Data taking for target sequence completed")
            except Exception as e:
                self.log.exception("Exception from latiss_take_sequence()")
                raise e
            finally:
                self.log.debug("At finally statement in run")
