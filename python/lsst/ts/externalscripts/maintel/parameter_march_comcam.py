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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["ParameterMarchComCam"]

import asyncio
import json
import types

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.comcam import ComCam, ComCamUsages

from ..base_parameter_march import BaseParameterMarch


class ParameterMarchComCam(BaseParameterMarch):
    """Perform a parameter march by taking images at different
    degree of freedom position with ComCam.

    Parameters
    ----------
    index : int
        Index of Script SAL component.
    """

    def __init__(self, index, descr="Perform a parameter march with ComCam.") -> None:
        super().__init__(index=index, descr=descr)

        self.comcam = None

        self.dz = 1500  # microns, offset for out-of-focus images

        self.instrument_name = "LSSTComCam"

    @property
    def camera(self):
        return self.comcam

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        """Sets script metadata.

        Parameters
        ----------
        metadata : `salobj.type_hints.BaseMsgType`
            Script metadata topic.
        """

        metadata.duration = (
            self.n_steps
            * 3
            * (
                self.config.exp_time
                + self.camera.read_out_time
                + self.camera.shutter_time
            )
        )

        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    async def take_images(
        self,
    ) -> None:
        """Take triplet (intra focal, extra focal and in-focus)
        image sequence.
        """
        self.log.debug("Moving to intra-focal position")

        await self.mtcs.offset_camera_hexapod(x=0, y=0, z=self.dz, u=0, v=0)

        supplemented_group_id = self.next_supplemented_group_id()

        self.log.info("Taking intra-focal image")

        print(self.config)
        intra_visit_id = await self.camera.take_cwfs(
            exptime=self.config.exp_time,
            n=1,
            group_id=supplemented_group_id,
            filter=self.config.filter,
            reason="INTRA" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.config.program,
        )

        self.log.debug("Moving to extra-focal position")

        # Hexapod offsets are relative, so need to move 2x the offset
        # to get from the intra- to the extra-focal position.
        z_offset = -(self.dz * 2.0)
        await self.mtcs.offset_camera_hexapod(x=0, y=0, z=z_offset, u=0, v=0)

        self.log.info("Taking extra-focal image")

        extra_visit_id = await self.camera.take_cwfs(
            exptime=self.config.exp_time,
            n=1,
            group_id=supplemented_group_id,
            filter=self.config.filter,
            reason="EXTRA" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.config.program,
        )

        self.log.info("Send processing request to RA OCPS.")
        config = {
            "LSSTComCam-FROM-OCS_DONUTPAIR": f"{intra_visit_id[0]},{extra_visit_id[0]}"
        }
        ocps_execute_task = asyncio.create_task(
            self.ocps.cmd_execute.set_start(
                config=json.dumps(config),
                timeout=self.camera.fast_timeout,
            )
        )

        self.log.debug("Moving to in-focus position")

        # Move the hexapod back to in focus position
        await self.mtcs.offset_camera_hexapod(x=0, y=0, z=self.dz, u=0, v=0)

        self.log.info("Taking in-focus image")

        await self.camera.take_acq(
            exptime=self.config.exp_time,
            n=1,
            group_id=self.group_id,
            filter=self.config.filter,
            reason="INFOCUS" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.config.program,
        )

        try:
            await ocps_execute_task
        except Exception:
            self.log.exception("Executing OCPS task failed. Ignoring.")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.comcam is None:
            self.log.debug("Creating Camera.")
            self.comcam = ComCam(
                self.domain,
                intended_usage=ComCamUsages.TakeImage | ComCamUsages.StateTransition,
                log=self.log,
            )
            await self.comcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls) -> dict:
        schema_dict = super().get_schema()
        additional_properties = yaml.safe_load(
            """
            sim:
                description: Is ComCam in simulation mode? This mode is used for tests.
                type: boolean
                default: false

        """
        )
        schema_dict["properties"].update(additional_properties)
        return schema_dict

    def get_instrument_configuration(self) -> dict:
        return dict(filter=self.config.filter)

    def get_instrument_filter(self) -> str:
        return f"{self.config.filter}"

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return self.instrument_name

    async def configure(self, config: types.SimpleNamespace) -> None:
        await super().configure(config)
        if hasattr(config, "sim") and config.sim:
            self.comcam.simulation_mode = config.sim
            self.instrument_name += "Sim"
