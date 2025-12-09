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
    "BuildPointingModel",
]

import warnings

from lsst.ts.observatory.control.utils.enums import RotType

try:
    from lsst.summit.utils import BestEffortIsr
    from lsst.ts.observing.utilities.auxtel.latiss.getters import get_image
    from lsst.ts.observing.utilities.auxtel.latiss.utils import (
        calculate_xy_offsets,
        parse_visit_id,
    )
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")


from lsst.ts.externalscripts.base_build_pointing_model import BaseBuildPointingModel
from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.observatory.control.constants.latiss_constants import boresight


class BuildPointingModel(BaseBuildPointingModel):
    """Build pointing model.

    This SAL Script is designed to take a series of observations in an all-sky
    grid with the intention of building pointing models. The Script constructs
    a grid, which the user controls the overall density. For each position in
    the grid it will search for a nearby star to use as a reference.
    The Script then slews to the target, center the brightest target in the FoV
    and register the position.
    """

    def __init__(self, index: int, remotes: bool = True) -> None:
        super().__init__(
            index=index,
            descr="Build pointing model and hexapod LUT.",
        )

        if not remotes:
            self._atcs = ATCS(
                domain=self.domain, log=self.log, intended_usage=ATCSUsages.DryTest
            )
            self._latiss = LATISS(
                domain=self.domain, log=self.log, intended_usage=LATISSUsages.DryTest
            )
        else:
            self._atcs = None
            self._latiss = None

    @property
    def tcs(self):
        return self._atcs

    @property
    def camera(self):
        return self._latiss

    @property
    def boresight(self):
        return boresight

    def get_best_effort_isr(self):
        return BestEffortIsr()

    async def get_image(self, image_id):
        return await get_image(
            parse_visit_id(image_id),
            self.best_effort_isr,
            timeout=self.get_image_timeout,
        )

    async def calculate_offset(self, centroid):
        dx_arcsec, dy_arcsec = calculate_xy_offsets(
            centroid,
            self.boresight,
        )
        return dx_arcsec, dy_arcsec

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
        try:
            target = await self.tcs.find_target(
                az=azimuth,
                el=elevation,
                mag_limit=self.config.magnitude_limit,
                mag_range=self.config.magnitude_range,
            )
        except Exception:
            self.log.exception(
                f"Error finding target for azimuth={azimuth}, elevation={elevation}."
                "Skipping grid position."
            )
            self.iterations["failed"] += 1
            return False

        await self.tcs.slew_object(
            name=target, rot=rotator, rot_type=RotType.PhysicalSky
        )
        return True

    @classmethod
    def get_schema(cls):
        schema = super().get_schema()
        # Update the program default for AuxTel
        schema["properties"]["program"]["default"] = "ATPTMODEL"
        return schema

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        if self._atcs is None:
            self._atcs = ATCS(domain=self.domain, log=self.log)
            await self._atcs.start_task
        if self._latiss is None:
            self._latiss = LATISS(
                domain=self.domain,
                log=self.log,
                tcs_ready_to_take_data=self._atcs.ready_to_take_data,
            )
            await self._latiss.start_task

        await super().configure(config)

    async def setup_instrument(self):
        """Setup latiss.

        Set filter and grating to empty_1.
        """
        await self._latiss.setup_instrument(
            filter="empty_1",
            grating="empty_1",
        )

    async def setup_tcs(self):
        """Setup ATCS.

        This method will reset the ATAOS and pointing offsets.
        """
        self.log.info("Resetting pointing and hexapod x and y offsets.")

        await self._atcs.rem.ataos.cmd_resetOffset.set_start(
            axis="x",
            timeout=self._atcs.long_timeout,
        )
        await self._atcs.rem.ataos.cmd_resetOffset.set_start(
            axis="y",
            timeout=self._atcs.long_timeout,
        )
        await self._atcs.reset_offsets()
