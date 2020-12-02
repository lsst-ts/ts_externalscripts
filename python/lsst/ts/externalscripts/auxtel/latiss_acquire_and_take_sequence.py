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

import lsst.daf.persistence as dafPersist
from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
import numpy as np
import yaml
from astropy import time as astropytime
from lsst.geom import PointD
from lsst.ts import salobj
from lsst.ts.observatory.control.auxtel import ATCS, LATISS
from lsst.ts.observatory.control.constants import latiss_constants
from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
from lsst.ts.observing.utilities.auxtel.latiss.utils import calculate_xy_offsets, parse_obs_id
from lsst.ts.standardscripts.utils import format_as_list

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

        super().__init__(index=index, descr="Perform target acquisition for LATISS instrument.")

        self.atcs = ATCS(self.domain, log=self.log)
        self.latiss = LATISS(self.domain, log=self.log)
        # instantiate the quick measurement class
        qm_config = QuickFrameMeasurementTask.ConfigClass()
        self.qm = QuickFrameMeasurementTask(config=qm_config)

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
                type: number
                default: 3

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
                description: Adjust star position (sweet-spot) to use boresight
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
        _recurrences = len(config.exposure_time_sequence) if isinstance(config.exposure_time_sequence,
                                                                        collections.Iterable) else 1

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
        in_oods = await self.latiss.rem.atarchiver.evt_imageInOODS.next(timeout=timeout, flush=flush)

        day_obs, seq_num = parse_obs_id(in_oods.obsid)[-2:]
        self.log.info(f"seqNum {seq_num} arrived in OODS")

        data_id = dict(dayObs=day_obs, seqNum=seq_num)

        return data_id

    async def latiss_acquire(self, doPointingModel=False):

        if doPointingModel:
            target_position = latiss_constants.boresight
        else:
            target_position = latiss_constants.sweet_spots[self.acq_grating]

        # get current filter/disperser
        current_filter, current_grating, current_stage_pos = await self.latiss.get_setup()

        # Check if a new configuration is required
        if (self.acq_filter is not current_filter) and (self.acq_grating is not current_grating):
            self.log.debug(f"Must load new filter {self.acq_filter} and grating {self.acq_grating}")

            # Is the atspectrograph Correction in the ATAOS running?
            corr = await self.atcs.rem.ataos.evt_correctionEnabled.aget(timeout=self.cmd_timeout)
            if corr.atspectrograph:
                # If so, then flush correction events for confirmation of
                # corrections
                self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.flush()
                self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.flush()

        # Setup instrument and telescope
        await asyncio.gather(
            self.atcs.slew_object(name=self.object_name, rot=0, slew_timeout=240),
            self.latiss.setup_instrument(grating=self.acq_grating, filter=self.acq_filter),
        )

        # If ATAOS is running wait for adjustments to complete before
        # moving on.
        if corr.atspectrograph:
            self.log.debug(f"Verifying LATISS configuration is incorporated into ATAOS offsets")
            # If so, then flush correction events for confirmation of
            # corrections
            await self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.next(timeout=self.cmd_timeout,
                                                                               flush=False)
            await self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.next(timeout=self.cmd_timeout,
                                                                                 flush=False)

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
                self.get_next_image_data_id(timeout=self.acq_exposure_time + STD_TIMEOUT),
            )

            exp = await get_image(
                data_id,
                datapath=self.dataPath,
                timeout=self.acq_exposure_time + STD_TIMEOUT,
                runBestEffortIsr=True,
            )

            # Find brightest star
            try:
                result = self.qm.run(exp)
            except RuntimeError:
                # Patrick - deal with a failure to find the source here
                pass  # and remove this
            current_position = PointD(result.brightestObjCentroid[0], result.brightestObjCentroid[1])

            # Find offsets
            self.log.debug(f"Current brightest target position is {current_position} whereas the"
                           f"Target position is {target_position}")

            dx_arcsec, dy_arcsec = calculate_xy_offsets(current_position, target_position)

            dr_arcsec = np.sqrt(dx_arcsec ** 2 + dy_arcsec ** 2)

            self.log.info(
                f"Calculated offsets [dx,dy] are [{dx_arcsec:0.2f},{dy_arcsec:0.2f}] arcsec as calculated"
                f" from sequence number {data_id['seqNum']} on dayObs of {data_id['dayObs']}"
            )

            # Check if star is in place, if so then we're done
            if dr_arcsec < self.target_pointing_tolerance:
                self.log.info(
                    "Current radial pointing error of {dr_arcsec:0.2f} arcsec is within the tolerance "
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
                f"Apply the calculated [x,y] correction of  [{dx_arcsec:0.2f},{dy_arcsec:0.2f}] arcsec?"
            )
            # Offset telescope, using persistent offsets
            self.log.info("Applying x/y offset to telescope pointing.")
            await self.atcs.offset_xy(dx_arcsec, dy_arcsec, persistent=True)

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
            raise SystemError(f"Failed to acquire star on target after {iter_num} images.")

        # Update pointing model
        if doPointingModel:
            self.log.info("Adding datapoint to pointing model")
            await self.atcs.add_point_data()

    async def latiss_take_sequence(self, silent=True):
        """Take the sequence of images as defined in visit_configs."""

        nexp = len(self.visit_configs)
        group_id = astropytime.Time.now().tai.isot
        for i, (filt, expTime, grating) in enumerate(self.visit_configs):

            # Focus and pointing offsets will be made automatically
            # by the TCS upon filter/grating changes

            # get current filter/disperser
            current_filter, current_grating, current_stage_pos = await self.latiss.get_setup()

            # Check if a new configuration is required
            if (filt is not current_filter) and (grating is not current_grating):
                self.log.debug(f"Must load new filter {filt} and grating {grating}")

                # Is the atspectrograph Correction in the ATAOS running?
                corr = await self.atcs.rem.ataos.evt_correctionEnabled.aget(timeout=self.cmd_timeout)
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
                    await self.atcs.rem.ataos.evt_atspectrographCorrectionStarted.aget(
                        timeout=self.cmd_timeout
                    )
                    await self.atcs.rem.ataos.evt_atspectrographCorrectionCompleted.aget(
                        timeout=self.cmd_timeout
                    )

            # Take an image
            await self.latiss.take_object(exptime=expTime, n=1, group_id=group_id)

            self.log.info(
                f"Completed exposure {i + 1} of {nexp}. Exptime = {expTime:6.1f}s,"
                f" filter={filt}, grating={grating})"
            )

    async def run(self):
        """"""
        if self.do_acquire:
            self.log.debug("Beginning target acquisition")
            await self.latiss_acquire()

        if self.do_take_sequence:
            # Do we want to put the instrument back to the original state?
            # I don't think so since it'll add overhead we may not want.
            # The offsetting of focus etc is now being done
            # automatically...

            self.log.debug("Beginning taking data for target sequence")
            try:
                await self.latiss_take_sequence()
            except Exception as e:
                print("grabbed exception from latiss_take_sequence(): ")
                raise e
            finally:
                self.log.debug("At finally statement in run")
                # # apply hexapod offsets to be the same as before to conserve
                # # focus
                # await self.atcs.rem.ataos.cmd_offset.set_start(
                #     axis="z", offset=hex_offsets.z, timeout=20
                # )
