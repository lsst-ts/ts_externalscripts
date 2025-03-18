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

__all__ = ["ParkCalibrationProjector"]

import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys


class ParkCalibrationProjector(salobj.BaseScript):
    """Move the calibration projector into a safe position

    Parameters
    ----------
    index : int
        Index of Script SAL component.
    """

    def __init__(self, index):
        super().__init__(
            index=index,
            descr="Park Calibration Projector",
        )

        self.mtcalsys = None

    def set_metadata(self, metadata):
        metadata.duration = 30

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/maintel/calibrations/park_calibration_projector.yaml # noqa: E501
            title: SetupWhiteFlats v1
            description: Configuration for SetupWhiteFlats.
              Each attribute can be specified as a scalar or array.
              All arrays must have the same length (one item per image).
            type: object

            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : ``self.cmd_configure.DataType``

        """
        self.log.info("Configure started")
        if self.mtcalsys is None:
            self.log.debug("Creating MTCalSys.")
            self.mtcalsys = MTCalsys(domain=self.domain, log=self.log)
            await self.mtcalsys.start_task

        self.linearstage_led_focus = self.mtcalsys.linearstage_led_focus
        self.linearstage_led_select = self.mtcalsys.linearstage_led_select
        self.linearstage_projector_select = self.mtcalsys.linearstage_projector_select
        self.led_projector = self.mtcalsys.rem.ledprojector

        self.log.info("Configure completed")

    async def run(self):
        """Run script."""
        await self.assert_components_enabled()

        self.log.info("Parking Calibration Projector")
        await self.mtcalsys.park_projector()

        # # TO-DO: DM-49065 for mtcalsys.py
        # params = await self.mtcalsys.get_projector_setup()

    async def assert_components_enabled(self):
        """Checks if LEDProjector and all LinearStages are ENABLED
        Raises
        ------
        RunTimeError:
            If either component is not ENABLED"""

        comps = [
            self.linearstage_led_focus,
            self.linearstage_led_select,
            self.linearstage_projector_select,
            self.led_projector,
        ]

        for comp in comps:
            summary_state = await comp.evt_summaryState.aget()
            try:
                summaryState = summary_state.summaryState
            except Exception as e:
                self.log.debug(f"Exception: {e}")
                summaryState = summary_state
            if salobj.State(summaryState) != salobj.State(salobj.State.ENABLED):
                raise RuntimeError(f"{comp} is not ENABLED")
