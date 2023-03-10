# This file is part of ts_externalcripts
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["LatissIntraExtraFocalData"]

import types
import yaml

from .latiss_base_align import LatissAlignResults, LatissBaseAlign


class LatissIntraExtraFocalData(LatissBaseAlign):
    """Intra and extra focal data procedure of Auxiliary
    Telescope with the LATISS instrument.

    This script takes intra and extra focal data on the specified
    target in AuxTel with the specified degrees of freedom.
    It can be used to take extra large donuts, measure sensitivity
    matrix or experiment with degrees of freedom.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index: int = 1, remotes: bool = True) -> None:
        super().__init__(
            index=index,
            remotes=remotes,
            descr="Procedure for taking intra and extra focal data of the Rubin "
            "Auxiliary Telescope with LATISS using the specified degrees of freedom "
            "on the targets of interest.",
        )

        self.log.info(
            "LATISS Wavefront Estimation Pipeline initialized. Perform optical "
            "Take intra and extra focal data with the Rubin Auxiliary Telescope with LATISS "
            "applying the specified degrees of freedom."
        )

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/externalscripts/"
            "auxtel/latiss_intra_extra_focal_data.py"
        )
        schema = f"""
        $schema: http://json-schema.org/draft-07/schema#
        $id: {url}{path}
        title: LatissIntraExtraFocalData v1
        description: Configuration for making a LATISS calibrations SAL Script.
        type: object
        properties:
            offset_x:
                description: x degree of freedom offset in mm.
                type: number
                default: 0.0
            offset_y:
                description: y degree of freedom offset in mm.
                type: number
                default: 0.0
            offset_z:
                description: z degree of freedom offset in mm.
                type: number
                default: 0.0
            offset_rx:
                description: rx degree of freedom offset in degrees.
                type: number
                default: 0.0
            offset_ry:
                description: ry degree of freedom offset in degrees.
                type: number
                default: 0.0
            offset_m1:
                description: M1 pressure degree of freedom offset in Pa.
                type: number
                default: 0.0
                maximum: 0.0
        additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema)
        base_schema_dict = super(LatissIntraExtraFocalData, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    async def additional_configuration(self, config: types.SimpleNamespace) -> None:
        """Additional configuration.
        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        # set dofs
        self.offset_x = config.offset_x
        self.offset_y = config.offset_y
        self.offset_z = config.offset_z
        self.offset_rx = config.offset_rx
        self.offset_ry = config.offset_ry
        self.offset_m1 = config.offset_m1

    async def arun(self, checkpoint: bool = False):
        """Run script operation encapsulating the checkpoints
        to allow running standalone.

        Parameters
        ----------
        checkpoint : `bool`, optional
            Should issue checkpoints (default=False)?

        """

        await self._configure_target()

        await self._slew_to_target(checkpoint)

        if self.take_detection_image:
            if checkpoint:
                await self.checkpoint("Detection image.")
            await self.latiss.take_acq(
                self.acq_exposure_time,
                group_id=self.group_id,
                reason="DETECTION_INFOCUS"
                + ("" if self.reason is None else f"_{self.reason}"),
                program=self.program,
            )

        # Apply degrees of freedom
        await self.look_up_table_offsets(
            self.offset_z,
            self.offset_x,
            self.offset_y,
            self.offset_rx,
            self.offset_ry,
            self.offset_m1,
        )

        # Setting visit_id's to none so run_cwfs will take a new dataset.
        self.intra_visit_id = None
        self.extra_visit_id = None
        try:
            await self.take_intra_extra()
        finally:
            # Return telescope to original state
            await self.look_up_table_offsets(
                -self.offset_z,
                -self.offset_x,
                -self.offset_y,
                -self.offset_rx,
                -self.offset_ry,
                -self.offset_m1,
            )

    async def run_align(self) -> LatissAlignResults:
        return LatissAlignResults()
