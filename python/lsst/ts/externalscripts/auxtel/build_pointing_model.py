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

__all__ = ["BuildPointingModel"]

import yaml

import numpy as np
import healpy as hp

from lsst.geom import PointD


from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask

from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
from lsst.ts.observing.utilities.auxtel.latiss.utils import (
    parse_visit_id,
    calculate_xy_offsets,
)
from lsst.ts.observatory.control.constants.latiss_constants import boresight


from lsst.ts.salobj import BaseScript
from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.observatory.control.utils.enums import RotType


class BuildPointingModel(BaseScript):
    """Build pointing model.

    This SAL Script is designed to take a series of observations in an all-sky
    grid with the intention of building pointing models. The Script constructs
    a grid, which the user controls the overall density. For each position in
    the grid it will search for a nearby star to use as a reference.
    The Script then slews to the target, center the brightest target in the FoV
    and register the positon.
    """

    def __init__(self, index: int, remotes: bool = True) -> None:

        super().__init__(
            index=index,
            descr="Build pointing model and hexapod LUT.",
        )

        if remotes:
            self.atcs = ATCS(domain=self.domain, log=self.log)
            self.latiss = LATISS(domain=self.domain, log=self.log)
        else:
            self.atcs = ATCS(
                domain=self.domain, log=self.log, intended_usage=ATCSUsages.DryTest
            )
            self.latiss = LATISS(
                domain=self.domain, log=self.log, intended_usage=LATISSUsages.DryTest
            )

        self.config = None

        self.iterations = dict(successful=0, failed=0)

        self.image_in_oods_timeout = 15.0
        self.get_image_timeout = 10.0

        self.elevation_grid = np.array([])
        self.azimuth_grid = np.array([])

    @classmethod
    def get_schema(cls):
        yaml_schema = """
$schema: http://json-schema/draft-07/schema#
$id: https://github.com/lsst-ts/ts_standardscripts/auxtel/BuildPointingModelAndHexapodLUT.yaml
title: BuildPointingModelAndHexapodLUT v1
description: Configuration for BuildPointingModelAndHexapodLUT.
type: object
properties:
    nside:
        type: integer
        default: 3
        description: Healpix nside parameter.
    azimuth_origin:
        type: number
        default: 0.
        description: Origin of the azimuth grid.
    elevation_minimum:
        type: number
        default: 20.
        description: >-
            Lowest elevation limit.
    elevation_maximum:
        type: number
        default: 80.
        description: Highest elevation limit.
    magnitude_limit:
        type: number
        default: 8.
        description: Largest/faintest magnitude of the star to search around each position in the grid.
    datapath:
        type: string
        default: /project/shared/auxTel
        description: Path to the data butler where the images can be located.
    exposure_time:
        type: number
        default: 1.
        description: Exposure time for the acquisition images used to center the target in the FoV.
required: []
additionalProperties: false
            """
        return yaml.safe_load(yaml_schema)

    def set_metadata(self, metadata):
        metadata.nimages = self.grid_size * self.images_per_position
        metadata.duration = metadata.nimages * (
            self.config.exposure_time
            + self.camera_readout_time
            + self.estimated_average_slew_time
        )

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.log.debug(f"Configuration: {config}")

        self.config = config

        self.configure_grid()

    def configure_grid(self):
        """Configure the observation grid."""
        self.log.debug("Configuring grid.")

        npix = hp.nside2npix(self.config.nside)

        healpy_indices = np.arange(npix)

        azimuth, elevation = hp.pix2ang(
            nside=self.config.nside, ipix=healpy_indices, lonlat=True
        )

        mask_out_of_range = np.bitwise_and(
            elevation >= self.config.elevation_minimum,
            elevation <= self.config.elevation_maximum,
        )

        self.elevation_grid = np.array(elevation[mask_out_of_range])
        self.azimuth_grid = np.array(azimuth[mask_out_of_range])

        self.log.debug("Sorting data in azimuth.")

        azimuth_sort = np.argsort(self.azimuth_grid)

        self.elevation_grid = self.elevation_grid[azimuth_sort]
        self.azimuth_grid = self.azimuth_grid[azimuth_sort]

        self.log.debug(f"Grid size: {self.grid_size}.")

    @property
    def grid_size(self):
        return len(self.elevation_grid)

    @property
    def images_per_position(self):
        return 2

    @property
    def camera_readout_time(self):
        return 2.0

    @property
    def estimated_average_slew_time(self):
        """The estimated average slew time considers a slew speed of 1 deg/sec.
        With that in mind, it returs the resolution of the grid in degrees.
        """
        return hp.nside2resol(self.config.nside, arcmin=True) / 60.0

    async def arun(self, checkpoint_active=False):

        for grid_index, azimuth, elevation in zip(
            range(self.grid_size), self.azimuth_grid, self.elevation_grid
        ):

            checkpoint_message = (
                f"Execute grid position {grid_index+1} of {self.grid_size}: "
                f"az={azimuth}, el={elevation}."
            )

            await self.handle_checkpoint(checkpoint_active, checkpoint_message)
            await self.execute_grid(azimuth, elevation)

    async def handle_checkpoint(self, checkpoint_active, checkpoint_message):

        if checkpoint_active:
            await self.checkpoint(checkpoint_message)
        else:
            self.log.info(checkpoint_message)

    async def execute_grid(self, azimuth, elevation):
        """Execute one grid position.

        Parameters
        ----------
        azimuth : `float`
            Azimuth of the grid position (in degrees).
        elevation : `float`
            Elevation of the grid position (in degrees).
        """

        try:
            target = await self.atcs.find_target(
                az=azimuth, el=elevation, mag_limit=self.config.magnitude_limit
            )
        except Exception:
            self.log.exception(
                f"Error finding target for azimuth={azimuth}, elevation={elevation}."
                "Skipping grid position."
            )
            self.iterations["failed"] += 1
            return

        await self.atcs.slew_object(name=target, rot_type=RotType.PhysicalSky)

        await self.center_on_brightest_source()

        self.iterations["successful"] += 1

    async def center_on_brightest_source(self):

        self.latiss.rem.atarchiver.evt_imageInOODS.flush()

        acquisition_image_ids = await self.latiss.take_engtest(
            exptime=self.config.exposure_time, n=1
        )

        await self.latiss.rem.atarchiver.evt_imageInOODS.next(
            flush=False, timeout=self.image_in_oods_timeout
        )

        offset_x, offset_y = await self.find_offset(image_id=acquisition_image_ids[0])

        await self.atcs.offset_xy(x=offset_x, y=offset_y)

        await self.latiss.take_engtest(exptime=self.config.exposure_time, n=1)

        await self.atcs.add_point_data()

    async def find_offset(self, image_id):

        exposure = await get_image(
            parse_visit_id(image_id),
            datapath=self.config.datapath,
            timeout=self.get_image_timeout,
            runBestEffortIsr=True,
        )

        quick_measurement_config = QuickFrameMeasurementTask.ConfigClass()
        quick_measurement = QuickFrameMeasurementTask(config=quick_measurement_config)

        result = quick_measurement.run(exposure)

        dx_arcsec, dy_arcsec = calculate_xy_offsets(
            PointD(result.brightestObjCentroid[0], result.brightestObjCentroid[1]),
            boresight,
        )

        return dx_arcsec, dy_arcsec

    async def run(self):
        await self.arun(checkpoint_active=True)
