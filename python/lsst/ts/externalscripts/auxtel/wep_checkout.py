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

__all__ = ["WepCheckout"]

import numpy as np
from lsst.ts import salobj
from lsst.ts.externalscripts.auxtel.latiss_wep_align import run_wep


class WepCheckout(salobj.BaseScript):
    """Checkout the WEP pipeline.

    This script checks out the WEP pipeline by running the WEP pipeline
    with known intra/extra pair of images.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    """

    def __init__(self, index: int = 1, descr="Run the WEP pipeline checkout.") -> None:
        super().__init__(
            index=index,
            descr=descr,
        )

        self.timeout_get_image = 20.0

        # Set stamp size for WFE estimation
        # 192 pix is size for dz=1.5, but gets automatically
        # scaled based on dz later, so can multiply by an
        # arbitrary factor here to make it larger
        self.side = 192 * 1.1  # normally 1.1

        # Offset for the intra/extra images
        self.dz = 0.8

        self.intra_visit_id = 2021110400954
        self.extra_visit_id = 2021110400955

        # Expected Zernike coefficients in nm
        self.expected_zernikes = {
            "defocus": 58.163,  # 0.058163 * 1e3
            "coma_x": -95.882,  # -0.095882 * 1e3
            "coma_y": 138.513,  # 0.138513 * 1e3
        }

        self.threshold = 20  # nm tolerance for Zernike coefficients

    @classmethod
    def get_schema(cls):
        pass

    async def configure(self):
        pass

    def set_metadata(self):
        pass

    async def run(self):
        """Run the WEP pipeline checkout."""
        self.log.info("Starting WEP pipeline checkout.")

        # Process images using WEP
        donut_diameter = int(np.ceil(self.side * self.dz / 1.5 / 2.0) * 2)

        try:
            intra_result, extra_result, wep_results = run_wep(
                self.intra_visit_id,
                self.extra_visit_id,
                donut_diameter,
                self.timeout_get_image,
            )
            # Validate results
            self.validate_results(wep_results.outputZernikesAvg)
            self.log.info("WEP environment verification completed successfully.")
        except Exception as e:
            error_msg = f"Failed to process images with WEP: {str(e)}"
            self.log.error(error_msg)
            raise RuntimeError(error_msg)

    def validate_results(self, wep_results):
        """Validate the WEP results against expected values."""
        # Mapping indices to expected Zernike coefficients
        indices = {0: "defocus", 3: "coma_x", 4: "coma_y"}

        for index, key in indices.items():
            measured = wep_results[index] * 1e3  # nm
            expected = self.expected_zernikes[key]
            if abs(measured - expected) > self.threshold:
                error_msg = (
                    f"Zernike coefficient error for {key}: Measured "
                    f"{measured:.3f} nm, expected {expected:.3f} nm "
                    f"exceeds {self.threshold} nm threshold"
                )
                self.log.error(error_msg)
                raise RuntimeError(error_msg)
            else:
                self.log.info(
                    f"Zernike coefficient for {key} is within expected "
                    f"range: Measured {measured:.3f} nm, Expected "
                    f" {expected:.3f} nm"
                )
