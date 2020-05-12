# This file is part of ts_externalscripts
#
# Developed for the LSST Data Management System.
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

import yaml
import asyncio
import numpy as np

from lsst.ts import salobj
from lsst.ts.standardscripts.auxtel.attcs import ATTCS
from lsst.ts.standardscripts.auxtel.latiss import LATISS

# from lsst.ts.idl.enums.Script import ScriptState

from lsst.observing.utils.audio import playSound
from lsst.observing.utils.filters import changeFilterAndGrating, getFilterAndGrating
from lsst.observing.utils.offsets import findOffsetsAndMove
from lsst.observing.constants import boreSight, sweetSpots

import lsst.daf.persistence as dafPersist


class LatissAcquireAndTakeSequence(salobj.BaseScript):
    """ TODO: update docs
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
    **Checkpoints**

    **Details**

    This script is used to put the brightest target in a field on a specific
    pixel.

    """

    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, silent=False):

        super().__init__(
            index=index, descr="Perform target acquisition for LATISS instrument."
        )

        self.attcs = ATTCS(self.domain)
        self.latiss = LATISS(self.domain)

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
                description: Max number of iterations to perform when putting source in place.
                type: number
                default: 3

              target_pointing_tolerance:
                description: Number of arcsec from source to desired position to consider good enough.
                type: number
                default: 5

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
                description: Exposure times for exposure sequence (sec). If a single value
                  is specified then the same exposure time is used for each exposure.
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

        self.acq_visit_config = (
            self.acq_filter,
            self.acq_exposure_time,
            self.acq_grating,
        )

        # make a list of tuples from the filter, exptime and grating lists
        self.visit_configs = [
            (f, e, g)
            for f, e, g in zip(
                config.filter_sequence,
                config.exposure_time_sequence,
                config.grating_sequence,
            )
        ]

        print(self.visit_configs)

    # This bit is required for ScriptQueue
    def set_metadata(self, metadata):
        metadata.duration = 300
        filters, gratings, expTimeTotal = set(), set(), 0
        for (filt, expTime, grating) in self.visit_configs:
            expTimeTotal += expTime
            filters.add(filt)
            gratings.add(grating)
        metadata.filter = f"{filters},{gratings}"

    async def latiss_acquire(self, silent=True, doPointingModel=False):

        if doPointingModel:
            targetPosition = boreSight
        else:
            targetPosition = sweetSpots[self.acq_grating]

        # Automatically accept calculated offset to sweetspot?
        # if False this queries the user, which will fail badly on
        # the script queue so make it always True
        _alwaysAcceptMove = True

        await asyncio.gather(
            self.attcs.slew_object(name=self.object_name, pa_ang=0, slew_timeout=240),
            self.latiss.setup_atspec(grating=self.acq_grating, filter=self.acq_filter),
        )

        success = False
        iterNum = -1  # heinous to support max_acq_iter = 0 working TODO: fix this!
        for iterNum in range(self.max_acq_iter):

            retvals = await asyncio.gather(
                findOffsetsAndMove(
                    self.attcs,
                    targetPosition,
                    self.latiss,
                    dataId=None,
                    butler=self.butler,
                    doMove=True,
                    alwaysAcceptMove=_alwaysAcceptMove,
                ),
                self.latiss.take_object(exptime=self.acq_exposure_time, n=1),
            )

            exp, dx_arcsec, dy_arcsec, peakVal = retvals[0]
            dr_arcsec = np.sqrt(dx_arcsec ** 2.0 + dy_arcsec ** 2.0)
            print(f"Calculated offsets [dx,dy] are [{dx_arcsec},{dy_arcsec}] arcsec")
            print(f"Current radial pointing error is {dr_arcsec}")

            if dr_arcsec < self.target_pointing_tolerance:
                success = True
                break

        if success:
            self.log.info("Achieved centering accuracy")
        else:
            if (
                iterNum != -1
            ):  # also heinous to support max_acq_iter = 0 working TODO: fix this!
                self.log.info(
                    f"Failed to center star on boresight after {iterNum+1} iterations"
                )
            return

        if not silent:
            playSound()

        self.log.info(f"Moved {self.object_name} to boresight")
        if not silent:
            playSound()

        # Update pointing model
        if doPointingModel:
            self.log.info("Adding datapoint to pointing model")
            await self.attcs.add_point_data()

        return

    async def latiss_take_sequence(self, silent=True):
        """Take the sequence of images as defined in visit_configs."""

        nexp = len(self.visit_configs)
        for i, (filt, expTime, grating) in enumerate(self.visit_configs):

            # NB: changeFilterAndGrating also does a focus offset
            # and a nod to keep the star in position
            # TODO: this needs pushing down into the LATISS class
            await changeFilterAndGrating(
                self.attcs, self.latiss, filter=filt, grating=grating
            )
            await self.latiss.take_object(exptime=expTime, n=1)

            # this is quick, so pull each time for logger to deal with Nones
            current_filter, current_grating = await getFilterAndGrating(self.latiss)
            self.log.info(
                f"Took {expTime:6.1f}s exposure ({current_filter}/{current_grating})"
            )
            if not silent:
                playSound("ding" if i < nexp - 1 else "gong")

    async def run(self):
        """"""
        if self.do_acquire:
            self.log.debug("Beginning target acquisition and data taking")
            await self.latiss_acquire()

        if self.do_take_sequence:
            # Grab hexapod offsets such that we can change it back upon
            # completion
            hex_offsets = await self.attcs.ataos.evt_correctionOffsets.aget(timeout=5)
            print("hex_offset before starting sequence is {}".format(hex_offsets))
            self.log.debug("Beginning taking data for target sequence")
            try:
                await self.latiss_take_sequence()
            except Exception as e:
                print("grabbed exception from latiss_take_sequence(): ")
                raise e
            finally:
                # apply hexapod offsets to be the same as before to conserve
                # focus
                await self.attcs.ataos.cmd_applyAxisOffset.set_start(
                    axis="z", offset=hex_offsets.z, timeout=20
                )
