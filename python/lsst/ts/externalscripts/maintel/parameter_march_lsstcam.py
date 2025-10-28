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

__all__ = ["ParameterMarchLSSTCam"]

import types

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages

from ..base_parameter_march import BaseParameterMarch


class ParameterMarchLSSTCam(BaseParameterMarch):
    """Perform a parameter march by taking images at different
    degree of freedom position with LSSTCam.

    Parameters
    ----------
    index : int
        Index of Script SAL component.
    """

    def __init__(self, index, descr="Perform a parameter march with LSSTCam.") -> None:
        super().__init__(index=index, descr=descr)

        self.mtcs = None
        self.lsstcam = None

        self.instrument_name = "LSSTCam"

    @property
    def camera(self):
        return self.lsstcam

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.lsstcam is None:
            self.log.debug("Creating Camera.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage | LSSTCamUsages.StateTransition,
                log=self.log,
                tcs_ready_to_take_data=self.mtcs.ready_to_take_data,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        """Sets script metadata.

        Parameters
        ----------
        metadata : `salobj.type_hints.BaseMsgType`
            Script metadata topic.
        """

        metadata.duration = self.n_steps * (
            self.config.exp_time + self.camera.read_out_time + self.camera.shutter_time
        )

        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    @classmethod
    def get_schema(cls) -> dict:
        schema_dict = super().get_schema()
        additional_properties = yaml.safe_load(
            """
            sim:
                description: Is LSSTCam in simulation mode? This mode is used for tests.
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

    async def take_images(self) -> None:
        """Take images at different degree of freedom position."""

        await self.camera.take_acq(
            exptime=self.config.exp_time,
            group_id=self.group_id,
            reason="INFOCUS" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.config.program,
            filter=self.config.filter,
        )

    async def configure(self, config: types.SimpleNamespace) -> None:
        await super().configure(config)
        if hasattr(config, "sim") and config.sim:
            self.lsstcam.simulation_mode = config.sim
            self.instrument_name += "Sim"
