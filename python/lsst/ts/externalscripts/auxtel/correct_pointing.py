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
import warnings

import numpy as np
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
    """Find the zero point offset of the pointing at the start of the night."""

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

        self.magnitude_limit = 8

    @classmethod
    def get_schema(cls):
        return None

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

        await self.execute_grid(90.0, 60.0, 0.0)

        offset_summary = await self.atcs.rem.atptg.evt_offsetSummary.aget(
            timeout=self.atcs.long_timeout
        )

        porigin_x = (
            offset_summary.pointingOriginX + offset_summary.pointingOriginHandsetDX
        )
        porigin_y = (
            offset_summary.pointingOriginY + offset_summary.pointingOriginHandsetDY
        )

        self.log.info(f"{porigin_x=}, {porigin_y=}")

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

        try:
            target = await self.atcs.find_target(
                az=azimuth,
                el=elevation,
                mag_limit=self.magnitude_limit,
            )
        except Exception:
            self.log.exception(
                f"Error finding target for azimuth={azimuth}, elevation={elevation}."
                "Skipping grid position."
            )
            self.iterations["failed"] += 1
            return

        await self.atcs.slew_object(
            name=target, rot=rotator, rot_type=RotType.PhysicalSky
        )

        await self.center_on_brightest_source()

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
        """Overload run method.

        This method simply call arun with checkpoint_active=True.
        """

        await self.arun(checkpoint_active=True)
