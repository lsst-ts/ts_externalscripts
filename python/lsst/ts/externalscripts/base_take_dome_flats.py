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

__all__ = ["BaseTakeDomeFlats"]

import abc
import types

import yaml
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript


class BaseTakeDomeFlats(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base class for taking dome flats. This will
    include white light and monochromatic flats"""

    def __init__(self, index, descr="Base script for taking dome flats.") -> None:
        super().__init__(index, descr)

        self.config = None
        self.instrument_setup_time = 0.0
        self.long_timeout = 30
        self.latest_exposure_id = None

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    @abc.abstractmethod
    async def configure_camera(self):
        """Abstract method to configure the camera, to be implemented
        in subclasses.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def configure_calsys(self):
        """Abstract method to configure the calibration system,
        to be implemented in subclasses.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_name(self):
        """Abstract method to be defined in subclasses to provide the
        instrument name.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_filter(self) -> str:
        """Abstract method to get the instrument filter configuration.

        Returns
        -------
        str
            Instrument filter configuration.
        """
        raise NotImplementedError()

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/base_take_dome_flats.yaml
            title: BaseTakeDomeFlats v1
            description: Configuration for BaseTakeDomeFlats.
            type: object
            properties:
              sequence_name:
                description: Name of sequence in MTCalsys
                type: string
                default: whitelight_r
              n_flat:
                description: Number of flats with this sequence
                type: integer
                default: 1
              use_camera:
                description: Will you use the camera during these flats
                type: boolean
                default: True

            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config: types.SimpleNamespace):
        """Configure script components including camera.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.config = config
        if config.use_camera:
            await self.configure_camera()
        await self.configure_calsys()

        await super().configure(config)

    @abc.abstractmethod
    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration.

        Returns
        -------
        str
            Instrument filter configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def take_dome_flat(self) -> None:
        """Method to setup the calibration system for flats and then take
        the flat images, including fiber specgtrograph and electrometer
        """
        raise NotImplementedError

    async def run_block(self):
        """Run the block of tasks to take Dome flats sequence."""

        await self.take_dome_flat()
