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
            title: ParkCalibrationProjector v1
            description: Park the Calibration after use to ensure LEDs are off and stages
                are in a safe plce
            type: object
            properties:
                ignore:
                    description: >-
                        CSCs from teh group to ignore in status check
                    type: array
                    items:
                        type: string

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

        if hasattr(config, "ignore"):
            self.mtcalsys.disable_checks_for_components(components=config.ignore)

        self.log.info("Configure completed")

    async def run(self):
        """Run script."""
        await self.mtcalsys.assert_all_enabled()

        self.log.info("Parking Calibration Projector")
        await self.mtcalsys.park_projector()

        params = await self.mtcalsys.get_projector_setup()

        self.log.info(
            f"Projector Location is {params[0]}, \n"
            f"LED Location stage pos @: {params[1]}, \n"
            f"LED Focus stage pos @: {params[2]}, \n"
            f"Laser Focus stage pos @: {params[3]}, \n"
            f"LED State stage pos @: {params[4]}"
        )

        led_location = params[1]
        assert led_location == self.mtcalsys.led_rest_position
