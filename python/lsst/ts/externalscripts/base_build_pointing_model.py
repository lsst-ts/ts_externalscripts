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

__all__ = [
    "BaseBuildPointingModel",
    "GridType",
]

import abc
import asyncio
import enum

import astropy.units
import healpy as hp
import numpy as np
import yaml
from lsst.ts import utils
from lsst.ts.salobj import BaseScript, ExpectedError


class GridType(enum.Enum):
    """Enumeration with different types of algorithm to build pointing grid."""

    HEALPIX = "healpix"
    RADEC = "radec"


class BaseBuildPointingModel(BaseScript, metaclass=abc.ABCMeta):
    """Base class for building pointing models.

    This SAL Script is designed to take a series of observations in an all-sky
    grid with the intention of building pointing models. The Script constructs
    a grid, which the user controls the overall density. For each position in
    the grid it will search for a nearby star to use as a reference.
    The Script then slews to the target, center the brightest target in the FoV
    and register the position.

    Parameters
    ----------
    index : `int`
        SAL index of this script
    descr : `str`
        Short description of the script.
    """

    def __init__(self, index: int, descr: str) -> None:
        super().__init__(
            index=index,
            descr=descr,
        )

        self.config = None

        self.iterations = dict(successful=0, failed=0)

        self.image_in_oods_timeout = 15.0
        self.get_image_timeout = 10.0

        self.elevation_grid = np.array([])
        self.azimuth_grid = np.array([])

    @property
    @abc.abstractmethod
    def tcs(self):
        """Telescope Control System instance.

        Returns
        -------
        tcs : `ATCS` or `MTCS`
            Telescope control system instance.
        """
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def camera(self):
        """Camera instance.

        Returns
        -------
        camera : `LATISS`, `ComCam`, or `LSSTCam`
            Camera instance.
        """
        raise NotImplementedError()

    @property
    @abc.abstractmethod
    def boresight(self):
        """Camera boresight position.

        Returns
        -------
        boresight : `lsst.geom.PointD`
            Boresight position in pixels.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_best_effort_isr(self):
        """Get BestEffortIsr instance for the camera.

        Returns
        -------
        best_effort_isr : `BestEffortIsr`
            BestEffortIsr instance.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def get_image(self, image_id):
        """Get image from the data repository.

        Parameters
        ----------
        image_id : `int`
            Image ID.

        Returns
        -------
        exposure : `lsst.afw.image.Exposure`
            Exposure object.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def setup_instrument(self):
        """Setup instrument for observations.

        This method should configure the instrument (filter, grating, etc.)
        for the pointing model observations.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def setup_tcs(self):
        """Setup telescope control system.

        This method should reset pointing offsets and any other necessary
        TCS configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def calculate_offset(self, centroid):
        """Calculate offset from centroid to boresight.

        Parameters
        ----------
        centroid : `lsst.geom.PointD`
            Centroid position in pixels.

        Returns
        -------
        offset_x : `float`
            X offset in arcseconds.
        offset_y : `float`
            Y offset in arcseconds.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    async def slew_to_az_el_rot(self, azimuth, elevation, rotator):
        """Slew to the provided az/el/rot position.

        Parameters
        ----------
        azimuth : float
            Azimuth position, in deg.
        elevation : float
            Elevation position, in deg.
        rotator : float
            Rotator position, in deg.

        Returns
        -------
        bool
            True if successful, False, otherwise.
        """
        raise NotImplementedError()

    @classmethod
    def get_schema(cls):
        yaml_schema = """
$schema: http://json-schema/draft-07/schema#
$id: https://github.com/lsst-ts/ts_externalscripts/base_build_pointing_model.py
title: BaseBuildPointingModel v1
description: Configuration for BaseBuildPointingModel.
type: object
properties:
    grid:
        type: string
        enum: ["healpix", "radec"]
        default: healpix
        description: >-
            Which type of spacial grid to use?
            healpix: Provide uniformly spaced pointing grid.
            radec: Non uniform but follow a more natural grid.
    healpix_grid:
        type: object
        additionalProperties: false
        description: Build pointing grid from healpix.
        properties:
            nside:
                type: integer
                default: 3
                minimum: 1
                description: >-
                    Healpix nside parameter.
                    The script uses healpix to construct an uniformly spaced grid around the visible sky.
                    This parameter defines the density of the pointing grid.
            azimuth_origin:
                type: number
                default: 0.
                description: >-
                    Origin of the azimuth grid.
                    This allows users to rotate the entire grid in azimuth, hence allowing you to run a grid
                    with the same density (nside) in different occasions to map different regions of the sky.
    radec_grid:
        type: object
        additionalProperties: false
        description: Build pointing grid from ra/dec grid.
        properties:
            dec_grid:
                type: object
                additionalProperties: false
                description: Declination grid information.
                default:
                    min: -80.0
                    max: 30.0
                    n: 9
                properties:
                    min:
                        type: number
                        minimum: -90.0
                        description: Minimum declination of the grid (in deg).
                    max:
                        type: number
                        maximum: 90.0
                        description: Maximum declination of the grid (in deg).
                    n:
                        type: integer
                        minimum: 2
                        description: Number of points in declination for the grid.
            ha_grid:
                type: object
                additionalProperties: false
                description: Hour Angle grid information.
                default:
                    min: -6.0
                    max: 6.0
                    n: [3, 5, 7, 9, 9, 9, 9, 7, 3]
                properties:
                    min:
                        type: number
                        minimum: -12.0
                        description: Minimum hour angle of the grid (in hours).
                    max:
                        type: number
                        maximum: 12.0
                        description: Maximum hour angle of the grid (in hours).
                    n:
                        type: array
                        minItems: 1
                        items:
                            type: integer
                        description: >-
                            Number of points in hour angle grid.
                            The size must match the size of the declination grid, but this is not enforced by
                            schema validation.
    rotator_sequence:
        type: array
        description: >-
            An array of arrays with the desired sequence of rotator values to
            sequence through.
        items:
            type: array
            items:
                type: number
        default: [[0],[-90, 90],[0]]
    elevation_minimum:
        type: number
        default: 20.
        description: Lowest elevation limit.
    elevation_maximum:
        type: number
        default: 80.
        description: Highest elevation limit.
    azimuth_minimum:
        type: number
        default: -190.
        description: Lower azimuth limit.
    azimuth_maximum:
        type: number
        default: 190.
        description: Highest azimuth limit.
    magnitude_limit:
        type: number
        default: 8.
        description: >-
            Limiting (brightest) stellar magnitude to use in determining the target at each position.
    magnitude_range:
        type: number
        default: 2.
        minimum: 1.
        description: >-
            Magnitude range. The faintest limit is defined as
            magnitude_limit+magnitude_range.
    exposure_time:
        type: number
        default: 1.
        description: Exposure time for the acquisition images used to center the target in the FoV.
    skip:
        type: integer
        default: 0
        minimum: 0
        description: Skip the initial given points in the grid.
    reason:
        description: Optional reason for taking the data.
        anyOf:
        - type: string
        - type: "null"
        default: null
    program:
        description: Optional name of the program this dataset belongs to.
        type: string
        default: PTMODEL
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

        # Instantiate BestEffortIsr
        self.best_effort_isr = self.get_best_effort_isr()

        self.configure_grid()

        self.rotator_sequence_gen = generate_rotator_sequence(
            self.config.rotator_sequence
        )

    def configure_grid(self):
        """Configure the observation grid."""
        self.log.info(f"Configuring {self.config.grid} grid.")

        grid_type = GridType(self.config.grid)

        if grid_type == GridType.HEALPIX:
            self._configure_grid_healpix()
        elif grid_type == GridType.RADEC:
            self._configure_grid_radec()
        else:
            raise RuntimeError(f"Unexpected grid type: {grid_type!r}")

        self.log.debug(f"Grid size: {self.grid_size}.")

    def _configure_grid_healpix(self):
        """Configure pointing grid using healpix algorithm."""
        npix = hp.nside2npix(self.config.healpix_grid["nside"])

        healpy_indices = np.arange(npix)

        azimuth, elevation = hp.pix2ang(
            nside=self.config.healpix_grid["nside"],
            ipix=healpy_indices,
            lonlat=True,
        )

        elevation += (np.random.rand(npix) - 0.5) * np.degrees(
            hp.nside2resol(self.config.healpix_grid["nside"])
        )

        position_in_search_area_mask = np.bitwise_and(
            elevation >= self.config.elevation_minimum,
            elevation <= self.config.elevation_maximum,
        )

        self.elevation_grid = np.array(elevation[position_in_search_area_mask])
        self.azimuth_grid = (
            np.array(azimuth[position_in_search_area_mask])
            + self.config.healpix_grid["azimuth_origin"]
        )

        azimuth_bellow_minimum = self.azimuth_grid < self.config.azimuth_minimum
        while azimuth_bellow_minimum.any():
            self.azimuth_grid[azimuth_bellow_minimum] += 360
            azimuth_bellow_minimum = self.azimuth_grid < self.config.azimuth_minimum

        azimuth_above_maximum = self.azimuth_grid > self.config.azimuth_maximum
        while azimuth_above_maximum.any():
            self.azimuth_grid[azimuth_above_maximum] -= 360
            azimuth_above_maximum = self.azimuth_grid > self.config.azimuth_maximum

        self.log.debug("Sorting data in azimuth.")

        azimuth_sort = np.argsort(self.azimuth_grid)

        self.elevation_grid = self.elevation_grid[azimuth_sort]
        self.azimuth_grid = self.azimuth_grid[azimuth_sort]

    def _configure_grid_radec(self):
        """Configure pointing grid using radec algorithm."""

        dec_grid_size = self.config.radec_grid["dec_grid"]["n"]
        ha_grid_size = len(self.config.radec_grid["ha_grid"]["n"])
        if dec_grid_size != ha_grid_size:
            raise ExpectedError(
                f"Size of declination grid ({dec_grid_size}) must match ha grid definition ({ha_grid_size})."
            )

        elevation_grid = []
        azimuth_grid = []

        reverse_ha = False
        dec_values = np.linspace(
            self.config.radec_grid["dec_grid"]["min"],
            self.config.radec_grid["dec_grid"]["max"],
            dec_grid_size,
        )

        for dec, n_ha in zip(dec_values, self.config.radec_grid["ha_grid"]["n"]):
            ha_values = np.linspace(
                self.config.radec_grid["ha_grid"]["min"],
                self.config.radec_grid["ha_grid"]["max"],
                n_ha,
            )

            if reverse_ha:
                ha_values = ha_values[::-1]

            reverse_ha = not reverse_ha

            for ha in ha_values:
                time = utils.astropy_time_from_tai_unix(utils.current_tai())
                time.location = self.tcs.location
                sidereal_time = time.sidereal_time("mean")
                ra = sidereal_time - ha * astropy.units.hourangle
                azel = self.tcs.azel_from_radec(ra, dec)
                if (
                    self.config.elevation_minimum
                    < azel.alt.to(astropy.units.degree).value
                    < self.config.elevation_maximum
                ):
                    az = azel.az.to(astropy.units.degree).value
                    if az > self.config.azimuth_maximum:
                        while az > self.config.azimuth_maximum:
                            az -= 360
                        if az < self.config.azimuth_minimum:
                            continue
                    elif az < self.config.azimuth_minimum:
                        while az < self.config.azimuth_minimum:
                            az += 360
                        if az > self.config.azimuth_maximum:
                            continue
                    elevation_grid.append(azel.alt.to(astropy.units.degree).value)
                    azimuth_grid.append(az)

        self.elevation_grid = np.array(elevation_grid)
        self.azimuth_grid = np.array(azimuth_grid)
        sort_az = np.argsort(self.azimuth_grid)

        self.elevation_grid = self.elevation_grid[sort_az]
        self.azimuth_grid = self.azimuth_grid[sort_az]

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
        With that in mind, it returns the resolution of the grid in degrees.
        """
        return hp.nside2resol(self.config.healpix_grid["nside"], arcmin=True) / 60.0

    async def arun(self, checkpoint_active=False):
        await self.handle_checkpoint(
            checkpoint_active=checkpoint_active,
            checkpoint_message="Setting up.",
        )

        await asyncio.gather(
            self.setup_tcs(),
            self.setup_instrument(),
        )

        if self.config.skip > 0:
            self.log.info(
                f"Skipping the initial {self.config.skip} points in the grid."
            )

        grid_str = "AzEl Grid:\n"

        for grid_index, azimuth, elevation in zip(
            range(self.grid_size),
            self.azimuth_grid,
            self.elevation_grid,
        ):
            if grid_index < self.config.skip:
                continue
            grid_str += (
                f"[{grid_index+1}/{self.grid_size}]:: "
                f"az={azimuth:0.2f}, el={elevation:0.2f}.\n"
            )

        self.log.info(grid_str)

        for grid_index, azimuth, elevation, rotator_sequence in zip(
            range(self.grid_size),
            self.azimuth_grid,
            self.elevation_grid,
            self.rotator_sequence_gen,
        ):
            if grid_index < self.config.skip:
                continue

            checkpoint_message = (
                f"[{grid_index+1}/{self.grid_size}]:: "
                f"az={azimuth:0.2f}, el={elevation:0.2f}, rot_seq={rotator_sequence}."
            )

            await self.handle_checkpoint(checkpoint_active, checkpoint_message)
            for rotator in rotator_sequence:
                await self.execute_grid(azimuth, elevation, rotator)

    async def handle_checkpoint(self, checkpoint_active, checkpoint_message):
        if checkpoint_active:
            await self.checkpoint(checkpoint_message)
        else:
            self.log.info(checkpoint_message)

    async def execute_grid(self, azimuth, elevation, rotator):
        """Performs target selection, acquisition, and pointing registration
        for a single grid position.

        Parameters
        ----------
        azimuth : `float`
            Azimuth of the grid position (in degrees).
        elevation : `float`
            Elevation of the grid position (in degrees).
        rotator : `float`
            Rotator (physical) position at the start of the slew. Rotator will
            follow sky from an initial physical position (e.g.
            rot_type=PhysicalSky).
        """

        success = await self.slew_to_az_el_rot(
            azimuth,
            elevation,
            rotator,
        )
        if not success:
            return

        await self.center_on_brightest_source()

        self.iterations["successful"] += 1

    async def center_on_brightest_source(self):
        self.camera.rem.atoods.evt_imageInOODS.flush()

        acquisition_image_ids = await self.camera.take_acq(
            exptime=self.config.exposure_time,
            n=1,
            group_id=self.group_id,
            reason="Acquisition"
            + ("" if self.config.reason is None else f" {self.config.reason}"),
            program=self.config.program,
        )

        await self.camera.rem.atoods.evt_imageInOODS.next(
            flush=False, timeout=self.image_in_oods_timeout
        )

        offset_x, offset_y = await self.find_offset(image_id=acquisition_image_ids[0])

        await self.tcs.offset_xy(x=offset_x, y=offset_y)

        await self.camera.take_acq(
            exptime=self.config.exposure_time,
            n=1,
            group_id=self.group_id,
            reason="Centered"
            + ("" if self.config.reason is None else f" {self.config.reason}"),
            program=self.config.program,
        )

        await self.tcs.add_point_data()

    async def find_offset(self, image_id):
        exposure = await self.get_image(image_id)

        try:
            from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
        except ImportError:
            raise RuntimeError("Cannot import QuickFrameMeasurementTask.")

        quick_measurement_config = QuickFrameMeasurementTask.ConfigClass()
        quick_measurement = QuickFrameMeasurementTask(config=quick_measurement_config)

        result = quick_measurement.run(exposure)

        from lsst.geom import PointD

        dx_arcsec, dy_arcsec = await self.calculate_offset(
            PointD(result.brightestObjCentroid[0], result.brightestObjCentroid[1])
        )

        return dx_arcsec, dy_arcsec

    async def run(self):
        await self.arun(checkpoint_active=True)


def generate_rotator_sequence(sequence):
    """A generator that cycles through the input sequence forward and
    backwards.

    Parameters
    ----------
    sequence : `list` [`list` [`float`]]
        A sequence of values to cicle through

    Yields
    ------
    `list`
        Values from the sequence.

    Notes
    -----
    This generator is designed to generate sequence of values cicling through
    the input forward and backwards. It will also reverse the list when moving
    backwards.

    Use it as follows:

    >>> sequence = [[0], [0, 180], [180]]
    >>> seq_gen = generate_rotator_sequence(sequence)
    >>> next(seq_gen)
    [0]
    >>> next(seq_gen)
    [0, 180]
    >>> next(seq_gen)
    [180]
    >>> next(seq_gen)
    [180, 0]
    >>> next(seq_gen)
    [0]
    """
    for s in sequence:
        yield s

    if len(sequence) > 1:
        while True:
            for s in sequence[:-1:][::-1]:
                yield s[::-1]
            for s in sequence[1::]:
                yield s
    else:
        for s in sequence:
            yield s
