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

__all__ = ["TakeRotatedComCam"]

import astropy.units
import yaml
from astropy.coordinates import ICRS, Angle
from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.maintel.take_aos_sequence_comcam import (
    TakeAOSSequenceComCam,
)
from lsst.ts.xml.enums.MTPtg import WrapStrategy
from lsst.ts.xml.enums.Script import MetadataCoordSys, MetadataRotSys


class TakeRotatedComCam(TakeAOSSequenceComCam):
    """Take images with ComCam at different rotator angles.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Slewing to rotator angle {angle} degrees.": Before slewing to the angle.
    - "Taking images at rotator angle {angle} degrees.": Before taking images.
    """

    def __init__(self, index):
        super().__init__(
            index=index, descr="Take AOS sequence at rotated positions with ComCam."
        )
        # Timeout for slewing (in seconds).
        self.slew_timeout = 240.0

    @classmethod
    def get_schema(cls):
        """Get the configuration schema, combining base class schema with
        additional properties."""
        schema_dict = super().get_schema()
        schema_dict["$id"] = (
            "https://github.com/lsst-ts/ts_externalscripts/maintel/TakeRotatedComCam.yaml"
        )
        schema_dict["title"] = "TakeRotatedComCam v1"
        schema_dict["description"] = "Configuration for TakeRotatedComCam."

        additional_schema_yaml = """
        properties:
          ra:
            description: ICRS right ascension (hour).
            anyOf:
              - type: number
                minimum: 0
                maximum: 24
              - type: string
          dec:
            description: ICRS declination (deg).
            anyOf:
              - type: number
                minimum: -90
                maximum: 90
              - type: string
          target_name:
            description: Name of the target object.
            type: string
          angles:
            description: Sequence of rotation angles to move the rotator to.
            type: array
            items:
              type: number
          slew_timeout:
            description: Timeout for slew operations (seconds).
            type: number
            default: 240.0
        required:
          - ra
          - dec
          - target_name
          - angles
        """
        additional_schema = yaml.safe_load(additional_schema_yaml)

        schema_dict["properties"].update(additional_schema["properties"])

        schema_dict.setdefault("required", [])
        schema_dict["required"].extend(additional_schema.get("required", []))

        return schema_dict

    def set_metadata(self, metadata):
        super().set_metadata(metadata)
        metadata.coordinateSystem = MetadataCoordSys.ICRS
        radec_icrs = ICRS(
            Angle(self.config.ra, unit=astropy.units.hourangle),
            Angle(self.config.dec, unit=astropy.units.deg),
        )
        metadata.position = [radec_icrs.ra.deg, radec_icrs.dec.deg]

        # Since we are defaulting to RotType.Physical, metadata rotation system
        # should be MOUNT
        metadata.rotationSystem = MetadataRotSys.MOUNT
        metadata.cameraAngle = float(self.config.angles[0])
        metadata.summary = f"Rotator angles: {self.config.angles}"

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await super().configure(config)
        self.config = config
        self.slew_timeout = getattr(config, "slew_timeout", self.slew_timeout)
        self.log.info(f"Configured with target name={self.config.target_name}")

    async def run_block(self):
        """Execute script operations."""
        await self.assert_feasibility()

        for angle in self.config.angles:
            self.log.info(
                f"Slewing to target {self.config.target_name} with rotator angle {angle} degrees."
            )

            await self.checkpoint(
                f"[{self.config.target_name}; "
                f"ra={self.config.ra}, dec={self.config.dec};"
                f"rot={angle:0.2f}]::"
                f"Slewing to rotator angle {angle} degrees."
            )

            await self.mtcs.slew_icrs(
                ra=self.config.ra,
                dec=self.config.dec,
                rot=angle,
                rot_type=RotType.Physical,
                target_name=self.config.target_name,
                az_wrap_strategy=WrapStrategy.NOUNWRAP,
            )

            await self.checkpoint(
                f"[{self.config.target_name}; "
                f"ra={self.config.ra}, dec={self.config.dec};"
                f"rot={angle:0.2f}]::"
                f"Take aos sequence at angle {angle} degrees."
            )

            await self.take_aos_sequence()

            await self.checkpoint(
                f"[{self.config.target_name}; "
                f"ra={self.config.ra}, dec={self.config.dec};"
                f"rot={angle:0.2f}]::"
                f"Done aos sequence at angle {angle} degrees."
            )
