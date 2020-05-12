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

__all__ = ["LatissAcquireTarget"]

import yaml

from lsst.ts import salobj
from lsst.ts.standardscripts.auxtel.attcs import ATTCS
from lsst.ts.standardscripts.auxtel.latiss import LATISS

import lsst.daf.persistence as dafPersist

# Import Robert's CalibrationStarVisit method
import lsst.observing.commands.calibrationStarVisit as calibrationStarVisit


class LatissAcquireTarget(salobj.BaseScript):
    """ Perform an acquisition of a target on LATISS with the Auxiliary
    Telescope.
    This sets up the instrument and puts the brightest target on a
    specific pixel.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    * post-offset: after offset determination but before slew

    **Details**

    This script is used to put the brightest target in a field on a specific
    pixel.

    """

    __test__ = False  # stop pytest from warning that this is not a test

    def __init__(self, index, remotes=True):

        super().__init__(
            index=index, descr="Perform target acquisition for LATISS instrument."
        )

        self.attcs = None
        self.latiss = None
        if remotes:
            self.attcs = ATTCS(self.domain)
            self.latiss = LATISS(self.domain)

        self.short_timeout = 5.0
        self.long_timeout = 30.0

        # Create a accessible copy of the config:
        self.config = None

        # Update Focus based on filter/grating glass thickness
        self.updateFocus = True

        # Automatically accept calculated offset to sweetspot
        self.alwaysAcceptMove = True

        # Display the results in Firefly
        self.display = None

        # Grab data for pointing model
        # self.doPointingModel=False

        # Suppress verbosity
        self.silent = False

        #
        # end of configurable attributes

    # define required methods
    #

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/auxtel/LatissAcquireTarget.yaml
            title: LatissAcquireTarget v1
            description: Configuration for LatissAcquireTarget Script.
            type: object
            properties:
              object_name:
                description: SIMBAD queryable object name
                type: string
              filter:
                description: Which filter to use when performing acquisition.
                type: string
                default: empty_1
              grating:
                description: Which grating to use when performing acquisition.
                type: string
                default: empty_1
              exposure_time:
                description: The exposure time to use when performing acquisition (sec).
                type: number
                default: 2.
              dataPath:
                description: Path to the butler data repository.
                type: string
                default: /project/shared/auxTel/
              doPointingModel:
                description: Adjust star position (sweetspot) to use boresight
                type: boolean
                default: False
              updateFocus:
                description: Update focus based on grating/filter thickenss
                type: boolean
                default: True
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

        self.filter = config.filter
        self.grating = config.grating

        # exposure time for acquisition (in seconds)
        self.exposure_time = config.exposure_time

        # butler data path
        self.dataPath = config.dataPath

        # Instantiate the butler
        self.butler = dafPersist.Butler(self.dataPath)

        # Object name
        self.object_name = config.object_name

        # Adjust sweetspot to do pointing model
        self.doPointingModel = config.doPointingModel

        # Update Focus to adjust for glass thickness variations
        self.updateFocus = config.updateFocus

    # This bit is required for ScriptQueue
    def set_metadata(self, metadata):
        # It takes about 300s to run the cwfs code, plus the two exposures
        metadata.duration = 300.0 + 2.0 * self.exposure_time
        metadata.filter = f"{self.filter},{self.grating}"

    async def run(self):
        """ Perform acquisition. This just wraps Robert's method in the
        observing repo

        Returns
        -------


        """

        self.log.debug("Beginning Acquisition")

        # Create the array of tuples for the exposures
        exposures = [(self.filter, self.exposure_time, self.grating)]

        await calibrationStarVisit.takeData(
            self.attcs,
            self.latiss,
            self.butler,
            self.object_name,
            exposures,
            updateFocus=self.updateFocus,
            alwaysAcceptMove=self.alwaysAcceptMove,
            logger=self.log,
            display=None,
            doPointingModel=self.doPointingModel,
            silent=self.silent,
        )
