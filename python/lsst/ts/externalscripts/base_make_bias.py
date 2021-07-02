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

__all__ = ["BaseMakeBias"]

import yaml
import abc

from lsst.ts import salobj


class BaseMakeBias(salobj.BaseScript, metaclass=abc.ABCMeta):
    """ Base class for taking biases and construct a master bias.

    Parameters
    ----------
    index : `int`
        SAL index of this script
    """

    def __init__(self, index, descr):
        super().__init__(index=index, descr=descr)

    @classmethod
    def get_schema(cls):
        schema = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/blob/master/python/lsst/ts/externalscripts/>-
        maintel/make_comcam_bias.py
        title: BaseMakeBias v1
        description: Configuration for BaseMakeBias.
        type: object
        additionalProperties: false
        required: [input_collections, calib_dir, repo]
        properties:
            n_bias:
                type: integer
                default: 1
                description: number of biases to take

            detectors:
                type: string
                items:
                    type: integer
                    minItems: 1
                default: (0)
                descriptor: Detector IDs

            input_collections:
                type: string
                descriptor: Input collections to pass to the bias pipetask.

            calib_dir:
                type: string
                descriptor: path to the calib directory for the bias when certifying it.
            repo:
                type: string
                descriptor: Butler repository.
        """
        return yaml.safe_load(schema)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        # Log information about the configuration

        self.log.debug(
            f"n_bias: {config.n_bias}, detectors: {config.detectors}, "
        )

        self.config = config

    def set_metadata(self, metadata):
        """Set estimated duration of the script.
        """
        # Temporary number
        metadata.duration = 10

    @abc.abstractmethod
    async def arun(self, checkpoint=False):
        raise NotImplementedError

    async def run(self):
        """"""
        await self.arun(checkpoint=True)
