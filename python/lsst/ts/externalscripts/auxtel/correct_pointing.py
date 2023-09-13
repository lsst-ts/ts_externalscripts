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
    "CorrectPointing",
]

import asyncio
import typing
import warnings

import numpy as np
import yaml
from lsst.geom import PointD

try:
    from lsst.pipe.tasks.quickFrameMeasurement import QuickFrameMeasurementTask
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_visit_id,
    )
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.observatory.control.constants.latiss_constants import boresight
from lsst.ts.observatory.control.utils.enums import RotType
from lsst.ts.salobj import BaseScript


class CorrectPointing(BaseScript):
    """Measure and apply a zero point offset to the pointing.

    This is most often executed at the beginning of the night.
    """

    def __init__(self, index: int, remotes: bool = True) -> None:
        super().__init__(
            index=index,
            descr="Correct pointing.",
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

        self.image_in_oods_timeout = 15.0
        self.get_image_timeout = 10.0
        self.tolerance = 1.0
        self.exposure_time = 1.0

        self.azimuth = 90.0
        self.elevation = 60.0
        self.radius = 5.0
        self.magnitude_limit = 6.0
        self.magnitude_range = 4.0

    @classmethod
    def get_schema(cls) -> dict[str, typing.Any]:
        schema_yaml = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/CorrectPointing.yaml
        title: CorrectPointing v1
        description: Configuration for CorrectPointing Script.
        type: object
        additionalProperties: false
        properties:
            az:
                type: number
                description: Azimuth (in degrees) to find a target.
                default: 90.0
            el:
                type: number
                description: Elevation (in degrees) to find a target.
                default: 60.0
            mag_limit:
                type: number
                description: Minimum (brightest) V-magnitude limit.
                default: 6.0
            mag_range:
                type: number
                description: >-
                    Magnitude range. The maximum/faintest limit is defined as
                    mag_limit+mag_range.
                default: 4.0
            radius:
                type: number
                description: Radius of the cone search (in degrees).
                default: 5.0
            catalog_name:
                description: >-
                    Name of a start catalog to load or None to skip loading a catalog.
                anyOf:
                    - type: string
                    - type: "null"
                default: HD_cwfs_stars
        """
        return yaml.safe_load(schema_yaml)

    def set_metadata(self, metadata):
        pass

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        self.best_effort_isr = self.get_best_effort_isr()

        self.azimuth = config.az
        self.elevation = config.el
        self.radius = config.radius
        self.magnitude_limit = config.mag_limit
        self.magnitude_range = config.mag_range
        self.catalog_name = config.catalog_name

    def get_best_effort_isr(self):
        # Isolate the BestEffortIsr class so it can be mocked
        # in unit tests
        return BestEffortIsr()

    @property
    def camera_readout_time(self):
        return 2.0

    async def arun(self, checkpoint_active=False):
        """Execute script main operations.

        Parameters
        ----------
        checkpoint_active : bool, optional
            Run script with checkpoints, by default False?
        """

        await self.handle_checkpoint(
            checkpoint_active=checkpoint_active,
            checkpoint_message="Setting up.",
        )

        await asyncio.gather(
            self._setup_atcs(),
            self._setup_latiss(),
        )

        await self.handle_checkpoint(checkpoint_active, "Correcting pointing...")

        await self.correct_pointing()

        offset_summary = await self.atcs.rem.atptg.evt_offsetSummary.aget(
            timeout=self.atcs.long_timeout
        )

        porigin_x = (
            offset_summary.pointingOriginX + offset_summary.pointingOriginHandsetDX
        )
        porigin_y = (
            offset_summary.pointingOriginY + offset_summary.pointingOriginHandsetDY
        )

        current_position = await self.atcs.rem.atptg.tel_mountPositions.aget(
            timeout=self.atcs.long_timeout
        )

        current_azimuth = current_position.azimuthCalculatedAngle[0]

        current_elevation = current_position.elevationCalculatedAngle[0]

        self.log.info(
            f"{porigin_x = :0.3f} arcsec, {porigin_y = :0.3f} arcsec, "
            f"{current_azimuth = :0.3f} deg, {current_elevation = :0.3f} deg"
        )

        await self.atcs.reset_offsets()

        await self.atcs.rem.atptg.cmd_poriginXY.set_start(
            x=porigin_x, y=porigin_y, timeout=self.atcs.long_timeout
        )

    async def _setup_latiss(self):
        """Setup latiss.

        Set filter and grating to empty_1.
        """
        await self.latiss.setup_instrument(
            filter="empty_1",
            grating="empty_1",
        )

    async def _setup_atcs(self):
        """Setup ATCS.

        This method will reset the ATAOS and pointing offsets.
        """
        self.log.info("Resetting pointing and hexapod x and y offsets.")

        await self.atcs.rem.ataos.cmd_resetOffset.set_start(
            axis="x",
            timeout=self.atcs.long_timeout,
        )
        await self.atcs.rem.ataos.cmd_resetOffset.set_start(
            axis="y",
            timeout=self.atcs.long_timeout,
        )
        await self.atcs.reset_offsets()

    async def handle_checkpoint(self, checkpoint_active, checkpoint_message):
        if checkpoint_active:
            await self.checkpoint(checkpoint_message)
        else:
            self.log.info(checkpoint_message)

    async def correct_pointing(self):
        """Performs target selection, acquisition, and pointing
        registration.
        """

        if self.catalog_name is not None:
            self.atcs.load_catalog(self.catalog_name)

        try:
            target = await self.atcs.find_target(
                az=self.azimuth,
                el=self.elevation,
                mag_limit=self.magnitude_limit,
                mag_range=self.magnitude_range,
                radius=self.radius,
            )
        except Exception:
            error_message = f"Error finding target for azimuth={self.azimuth}, elevation={self.elevation}."

            # Log the original exception and re-raise it as a RuntimeError.
            # This helps reduce the main error message presented to the user
            # and still logs the original error message.
            self.log.exception(error_message)
            raise RuntimeError(error_message)

        rotator_angle = await self.get_rotator_angle()

        await self.atcs.slew_object(
            name=target, rot=rotator_angle, rot_type=RotType.PhysicalSky
        )

        await self.center_on_brightest_source()

    async def get_rotator_angle(self) -> float:
        """Determine the desired rotator angle to execute the centering
        operation.

        Basically gets the current position of the active Nasmyth rotator.

        Returns
        -------
        float
            Desired rotator angle (in deg).
        """

        try:
            mount_positions = await self.atcs.rem.atptg.tel_mountPositions.aget(
                timeout=self.atcs.fast_timeout
            )

            return np.mean(mount_positions.nasmythCalculatedAngle)
        except asyncio.TimeoutError:
            self.log.warning("Could not determine Nasmyth angle. Fallback to zero.")
            return 0.0

    async def center_on_brightest_source(self):
        """Put the brightest source at the center of the detector."""

        self.latiss.rem.atoods.evt_imageInOODS.flush()

        offset = await self._center()

        while offset > self.tolerance:
            offset = await self._center()

        await self.atcs.add_point_data()

    async def _center(self) -> float:
        """Find offset between the brightest source and the bore sight and
        offset the telescope.

        Returns
        -------
        float
            Size of the offset required to center the source (in arcsec).
        """
        acquisition_image_ids = await self.latiss.take_acq(
            exptime=self.exposure_time,
            n=1,
            group_id=self.group_id,
            reason="Acquisition",
        )

        await self.latiss.rem.atoods.evt_imageInOODS.next(
            flush=False, timeout=self.image_in_oods_timeout
        )

        offset_x, offset_y = await self.find_offset(image_id=acquisition_image_ids[0])

        if np.isnan(offset_x) or np.isnan(offset_y):
            raise RuntimeError(
                f"offset_x and offset_y cannot contain any NANs: ({offset_x},{offset_y})"
            )

        await self.atcs.offset_xy(x=offset_x, y=offset_y, absorb=True)

        return np.sqrt(offset_x**2.0 + offset_y**2)

    async def find_offset(self, image_id: int) -> tuple[float, float]:
        """Find offset between the brightest source and the boresight.

        Parameters
        ----------
        image_id : int
            Image id.

        Returns
        -------
        tuple[float, float]
            Offset in image coordinates, x/y in arcsec.
        """

        # TODO: (DM-37665) Move this method to a utility class in
        # ts_observing_utilities.
        exposure = await get_image(
            parse_visit_id(image_id),
            self.best_effort_isr,
            timeout=self.get_image_timeout,
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
        """Override run method.

        This method simply call arun with checkpoint_active=True.
        """

        await self.arun(checkpoint_active=True)
