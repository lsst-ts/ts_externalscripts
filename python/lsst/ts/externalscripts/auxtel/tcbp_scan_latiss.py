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

__all__ = ["TCBPScanLatiss"]

import yaml
from lsst.ts.observatory.control.auxtel.latiss import LATISS, LATISSUsages

from ..base_tcbp_scan import BaseTCBPScan


class TCBPScanLatiss(BaseTCBPScan):
    """TCBP wavelength scan with LATISS on AuxTel."""

    def __init__(self, index):
        super().__init__(index=index, descr="Run a TCBP wavelength scan with LATISS.")
        self.latiss = None

    @classmethod
    def get_schema(cls):
        schema_dict = super().get_schema()
        extra = yaml.safe_load("""
            filter_grating:
                description: >-
                  LATISS filter/grating combination, formatted as
                  ``<filter>_<grating>``. Used both to set up LATISS and to
                  pick the optimized wavelength grid via the non-``empty``
                  side of the pair.
                type: string
                default: empty_holo
            """)
        schema_dict["properties"].update(extra)
        return schema_dict

    def get_image_id_key(self):
        return "AUXTELID"

    @staticmethod
    def _split_filter_grating(config):
        f, g = config.filter_grating.split("_", 1)
        if g == "holo":
            g = "holo4_003"
        elif g == "empty":
            g = "empty_1"
        if f == "empty":
            f = "empty_1"
        elif f == "og550":
            f = "OG550_65mm_1"
        elif f == "bg40":
            f = "BG40_65mm_1"
        return f, g

    def default_filter_for_optimized_wavelengths(self, config):
        """Use the non-empty side of ``filter_grating``."""
        f, g = self._split_filter_grating(config)
        return g if f == "empty_1" else f

    def datadir_tag(self, config):
        return config.filter_grating

    async def configure_camera(self):
        if self.latiss is None:
            self.log.debug("Creating LATISS.")
            self.latiss = LATISS(
                self.domain,
                intended_usage=LATISSUsages.TakeImageFull,
                log=self.log,
            )
            await self.latiss.start_task
        else:
            self.log.debug("LATISS already defined, skipping.")

    async def configure(self, config):
        await super().configure(config)
        f, g = self._split_filter_grating(config)
        await self.latiss.setup_instrument(filter=f, grating=g)

    async def take_camera_image(self, exptime, n_expo, reason, program):
        return await self.latiss.take_imgtype(
            imgtype=self.img_type,
            exptime=exptime,
            n=n_expo,
            reason=reason,
            program=program,
        )
