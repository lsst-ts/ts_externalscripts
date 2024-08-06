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

import asyncio
import concurrent.futures
import functools

import numpy as np
import yaml
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

    def __init__(self, index, descr="Run the WEP pipeline checkout.") -> None:
        super().__init__(
            index=index,
            descr=descr,
        )

        self.config = None

        self.timeout_get_image = 20.0

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/wep_checkout.yaml
            title: WepCheckout
            description: Configuration schema for WepCheckout.
            type: object
            properties:
              intra_visit_id:
                description: >
                  An intra focus visit id.
                type: string
                default: "2021110400954"
              extra_visit_id:
                description: >
                  An extra focus visit id.
                type: string
                default: "2021110400955"
              dz:
                description: >
                  Offset for the intra/extra images.
                type: number
                default: 1.5
              side:
                description: >
                  Set stamp size for WFE estimation.
                type: number
                default: 192
              expected_zern_defocus:
                description: >
                  Expected Zernike defocus coefficient.
                type: number
                default: 69.856
              expected_zern_coma_x:
                description: >
                  Expected Zernike coma_x coefficient.
                type: number
                default: 35.745
              expected_zern_coma_y:
                description: >
                  Expected Zernike coma_y coefficient.
                type: number
                default: 70.311
              threshold:
                description: >
                  Tolerance for Zernike coefficients.
                type: number
                default: 20
            additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):

        self.intra_visit_id = config.intra_visit_id
        self.extra_visit_id = config.extra_visit_id
        self.dz = config.dz

        self.expected_zernikes = {
            "defocus": config.expected_zern_defocus,
            "coma_x": config.expected_zern_coma_x,
            "coma_y": config.expected_zern_coma_y,
        }

        self.threshold = config.threshold

        # 192 pix is size for dz=1.5, but gets automatically
        # scaled based on dz later, so can multiply by an
        # arbitrary factor here to make it larger
        self.side = config.side * 1.1  # normally 1.1

        self.config = config

    def set_metadata(self, metadata):
        metadata.duration = 10.0

    async def run(self):
        """Run the WEP pipeline checkout."""
        self.log.info("Starting WEP pipeline checkout.")

        # Process images using WEP
        donut_diameter = int(np.ceil(self.side * self.dz / 1.5 / 2.0) * 2)

        try:

            loop = asyncio.get_running_loop()

            with concurrent.futures.ProcessPoolExecutor(max_workers=1) as pool:
                self.log.debug(
                    "Running wep with: "
                    f"intra_visit_id={self.intra_visit_id}, "
                    f"extra_visit_id={self.extra_visit_id}, "
                    f"donut_diameter={donut_diameter}, "
                    f"timeout_get_image={self.timeout_get_image}. "
                )

                (intra_result, extra_result, wep_results) = await loop.run_in_executor(
                    pool,
                    functools.partial(
                        run_wep,
                        self.intra_visit_id,
                        self.extra_visit_id,
                        donut_diameter,
                        self.timeout_get_image,
                    ),
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
                    f"Zernike coefficient error for {key}. Measured: "
                    f"{measured:.3f} nm. Expected: {expected:.3f} nm "
                    f"It exceeds the {self.threshold} nm threshold."
                )
                self.log.error(error_msg)
                raise RuntimeError(error_msg)
            else:
                self.log.info(
                    f"Zernike coefficient for {key} is within expected "
                    f"range. Measured: {measured:.3f} nm. Expected: "
                    f" {expected:.3f} nm."
                )
