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

__all__ = ["TCBPScanLSSTCam"]

import yaml
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages

from ..base_tcbp_scan import KNOWN_OPTIMIZED_FILTERS, BaseTCBPScan


class TCBPScanLSSTCam(BaseTCBPScan):
    """TCBP wavelength scan with LSSTCam on the Main Telescope."""

    def __init__(self, index):
        super().__init__(index=index, descr="Run a TCBP wavelength scan with LSSTCam.")
        self.lsstcam = None

    @classmethod
    def get_schema(cls):
        schema_dict = super().get_schema()
        extra = yaml.safe_load("""
            lsstcam_filter:
                description: Filter to install in LSSTCam for the scan.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
            """)
        schema_dict["properties"].update(extra)
        return schema_dict

    def get_image_id_key(self):
        return "LSSTCAMID"

    @staticmethod
    def _normalize(v):
        return str(v).lower() if v is not None else "empty"

    def default_filter_for_optimized_wavelengths(self, config):
        """Map the LSSTCam filter onto an optimized-wavelength key.

        LSSTCam filters use names like ``r_57`` that don't match the
        :func:`get_optimized_wavelengths` keys; fall back to the broad
        ``"empty"`` grid unless the filter name matches a known key
        directly.
        """
        f = self._normalize(getattr(config, "lsstcam_filter", None))
        return f if f in KNOWN_OPTIMIZED_FILTERS else "NONE"

    def datadir_tag(self, config):
        return self._normalize(getattr(config, "lsstcam_filter", None))

    async def configure_camera(self):
        if self.lsstcam is None:
            self.log.debug("Creating LSSTCam.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSSTCam already defined, skipping.")

    async def configure(self, config):
        await super().configure(config)
        self.lsstcam_filter = getattr(config, "lsstcam_filter", None)
        if self.lsstcam_filter is not None:
            await self.lsstcam.setup_instrument(filter=self.lsstcam_filter)

    async def take_camera_image(self, exptime, n_expo, reason, program):
        return await self.lsstcam.take_imgtype(
            imgtype=self.img_type,
            exptime=exptime,
            n=n_expo,
            reason=reason,
            program=program,
        )
