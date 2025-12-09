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

from lsst.ts.externalscripts.base_build_pointing_model import BaseBuildPointingModel
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


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
            descr="Build pointing model.",
        )

        if not remotes:
            self._mtcs = MTCS(
                domain=self.domain, log=self.log, intended_usage=MTCSUsages.DryTest
            )
            self._lsstcam = LSSTCam(
                domain=self.domain, log=self.log, intended_usage=LSSTCamUsages.DryTest
            )
        else:
            self._mtcs = None
            self._lsstcam = None

    @property
    def tcs(self):
        return self._mtcs

    @property
    def camera(self):
        return self._lsstcam

    @property
    def boresight(self):
        return (0, 0)

    def get_best_effort_isr(self):
        return None

    async def get_image(self, image_id):
        return None

    async def calculate_offset(self, centroid):
        return 0, 0

    @classmethod
    def get_schema(cls):
        schema = super().get_schema()
        # Update the program default for AuxTel
        schema["properties"]["program"]["default"] = "MTPTMODEL"
        return schema

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        if self._mtcs is None:
            self._mtcs = MTCS(
                domain=self.domain,
                log=self.log,
                intended_usage=MTCSUsages.Slew
                | MTCSUsages.StateTransition
                | MTCSUsages.AOS,
            )
            await self._mtcs.start_task
        if self._lsstcam is None:
            self._lsstcam = LSSTCam(
                domain=self.domain,
                log=self.log,
                tcs_ready_to_take_data=self._mtcs.ready_to_take_data,
                intended_usage=LSSTCamUsages.TakeImage,
            )
            await self._lsstcam.start_task

        await super().configure(config)

    async def setup_instrument(self):
        """Setup instrument.

        This method is a noop.
        """
        pass

    async def setup_tcs(self):
        """Setup ATCS.

        This method will reset pointing offsets.
        """
        self.log.info("Resetting pointing.")

        await self._mtcs.reset_offsets()

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
        await self.tcs.point_azel(
            az=azimuth,
            el=elevation,
            rot_tel=rotator,
        )
        await self.tcs.start_tracking()

        return True

    async def center_on_brightest_source(self):

        await self.camera.take_acq(
            exptime=self.config.exposure_time,
            n=1,
            group_id=self.group_id,
            reason="PtgModel"
            + ("" if self.config.reason is None else f" {self.config.reason}"),
            program=self.config.program,
        )

        await self.tcs.add_point_data()
