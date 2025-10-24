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

__all__ = ["CorrectPointing"]

import asyncio
import functools
import warnings

import astropy.units as u
import numpy as np
import yaml
from astropy.coordinates import Angle
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.salobj import BaseScript

try:
    from lsst.summit.utils import ConsDbClient
except ImportError:
    warnings.warn("Cannot import ConsDB client. Script will not work.")


class CorrectPointing(BaseScript):
    """Measure and apply pointing corrections for the Simonyi Telescope.

    This script corrects pointing offsets introduced after homing the MTMount.
    It assumes the telescope is already tracking a target.

    The workflow:
    1. Take an exposure
    2. Wait for WCS solution from Rapid Analysis via ConsDB
    3. Calculate offset between measured and target position
    4. Apply offset to pointing component with absorb=True
    5. Repeat until offsets are below threshold
    """

    def __init__(self, index: int) -> None:
        super().__init__(
            index=index,
            descr="Correct pointing for Main Telescope.",
        )

        self.mtcs = None
        self.lsstcam = None
        self.consdb_client = None

        self.tolerance_arcsec = 1.0
        self.max_iterations = 5
        self.exposure_time = 2.0
        self.consdb_timeout = 60.0
        self.filter = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/maintel/CorrectPointing.yaml
        title: CorrectPointing v1
        description: Configuration for MainTel CorrectPointing Script.
        type: object
        properties:
            exposure_time:
                type: number
                description: Exposure time in seconds for each pointing image.
                default: 2.0
                minimum: 0.5
            tolerance_arcsec:
                type: number
                description: Maximum acceptable pointing offset in arcseconds.
                default: 1.0
                minimum: 0.1
            max_iterations:
                type: number
                description: Maximum number of correction iterations to attempt.
                default: 5
                minimum: 1
            consdb_timeout:
                type: number
                description: Timeout in seconds for waiting for ConsDB data.
                default: 60.0
                minimum: 10.0
            filter:
                description: Filter name or ID. If None, uses current filter.
                default: null
                anyOf:
                  - type: string
                  - type: integer
                    minimum: 1
                  - type: "null"
        additionalProperties: false
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await self.configure_tcs()
        await self.configure_camera()
        self.configure_consdb_client()

        self.exposure_time = config.exposure_time
        self.tolerance_arcsec = config.tolerance_arcsec
        self.max_iterations = config.max_iterations
        self.consdb_timeout = config.consdb_timeout
        self.filter = config.filter

    async def configure_tcs(self) -> None:
        """Handle creating the MTCS object and waiting for remote to start."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                intended_usage=MTCSUsages.Slew,
                log=self.log,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting for remote to
        start.
        """
        if self.lsstcam is None:
            self.log.debug("Creating LSSTCam.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
                tcs_ready_to_take_data=self.mtcs.ready_to_take_data,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("LSSTCam already defined, skipping.")

    def configure_consdb_client(self) -> None:
        """Handle creating the ConsDB client."""
        if self.consdb_client is None:
            self.log.debug("Creating ConsDB client.")
            self.consdb_client = ConsDbClient("http://consdb-pq.consdb:8080/consdb")
        else:
            self.log.debug("ConsDB client already defined, skipping.")

    def set_metadata(self, metadata):
        """Set estimated duration in metadata.

        Parameters
        ----------
        metadata : `lsst.ts.salobj.type_hints.BaseMsgType`
            Script metadata topic.
        """
        exposure_overhead = self.lsstcam.read_out_time + self.lsstcam.shutter_time
        duration_per_iteration = (
            self.exposure_time + exposure_overhead + self.consdb_timeout
        )

        metadata.duration = duration_per_iteration * self.max_iterations
        metadata.instrument = "LSSTCam"
        if self.filter is not None:
            metadata.filter = f"{self.filter}"

    async def assert_feasibility(self) -> None:
        """Verify that the telescope is in a feasible state to execute the
        script.
        """
        await self.lsstcam.assert_all_enabled()
        await self.mtcs.assert_all_enabled()

    async def run(self):
        """Execute the pointing correction procedure."""
        await self.assert_feasibility()

        self.log.info("Starting pointing correction procedure.")
        self.log.info(f"Tolerance: {self.tolerance_arcsec} arcsec")
        self.log.info(f"Max iterations: {self.max_iterations}")

        target_ra_rad, target_dec_rad = await self.get_target_coordinates()
        target_ra_deg = Angle(target_ra_rad, unit=u.rad).to(u.deg).value
        target_dec_deg = Angle(target_dec_rad, unit=u.rad).to(u.deg).value

        self.log.info(
            f"Target coordinates: RA={target_ra_deg:.6f} deg, Dec={target_dec_deg:.6f} deg"
        )

        offset_magnitude_arcsec = float("inf")
        iteration = 0

        while iteration < self.max_iterations:
            iteration += 1
            self.log.info(f"Starting iteration {iteration} of {self.max_iterations}")

            if offset_magnitude_arcsec < self.tolerance_arcsec:
                self.log.info(
                    f"Pointing offset {offset_magnitude_arcsec:.3f} arcsec is within "
                    f"tolerance {self.tolerance_arcsec:.3f} arcsec. Correction complete."
                )
                break

            exposure_ids = await self.lsstcam.take_acq(
                exptime=self.exposure_time,
                n=1,
                group_id=self.group_id,
                reason="pointing_correction",
                filter=self.filter,
            )

            exposure_id = int(exposure_ids[0])
            self.log.info(f"Took exposure {exposure_id}")

            measured_ra_deg, measured_dec_deg = (
                await self.get_measured_coordinates_from_consdb(exposure_id)
            )

            offset_ra_arcsec, offset_dec_arcsec, offset_magnitude_arcsec = (
                self.calculate_offset(
                    target_ra_deg, target_dec_deg, measured_ra_deg, measured_dec_deg
                )
            )

            self.log.info(
                f"Measured coordinates: RA={measured_ra_deg:.6f} deg, Dec={measured_dec_deg:.6f} deg"
            )
            self.log.info(
                f"Offset: RA={offset_ra_arcsec:.3f} arcsec, Dec={offset_dec_arcsec:.3f} arcsec, "
                f"Magnitude={offset_magnitude_arcsec:.3f} arcsec"
            )

            if offset_magnitude_arcsec >= self.tolerance_arcsec:
                await self.apply_pointing_offset(offset_ra_arcsec, offset_dec_arcsec)
            else:
                self.log.info(
                    f"Pointing offset {offset_magnitude_arcsec:.3f} arcsec is within "
                    f"tolerance {self.tolerance_arcsec:.3f} arcsec. Correction complete."
                )

        if offset_magnitude_arcsec >= self.tolerance_arcsec:
            raise RuntimeError(
                f"Failed to correct pointing after {self.max_iterations} iterations. "
                f"Final offset: {offset_magnitude_arcsec:.3f} arcsec"
            )

        self.log.info("Pointing correction successful.")

    async def get_target_coordinates(self):
        """Get the current target coordinates from MTPtg.

        Returns
        -------
        tuple
            Target RA and Dec in radians (ra_rad, dec_rad).
        """
        try:
            current_target = await self.mtcs.rem.mtptg.evt_currentTarget.aget(
                timeout=self.mtcs.fast_timeout
            )
            return current_target.ra, current_target.declination
        except asyncio.TimeoutError:
            raise RuntimeError(
                "Could not determine current target coordinates from MTPtg. "
                "Ensure the telescope is tracking."
            )

    async def get_measured_coordinates_from_consdb(self, exposure_id: int):
        """Get the measured WCS coordinates from ConsDB.

        Uses wait_for_row_to_exist to efficiently wait for the WCS solution
        to be computed and written to ConsDB, then extracts both RA and Dec
        from the single row result.

        Parameters
        ----------
        exposure_id : int
            Exposure ID to query.

        Returns
        -------
        tuple
            Measured RA and Dec in degrees (ra_deg, dec_deg).

        Raises
        ------
        RuntimeError
            If the WCS solution is not available within the timeout period,
            or if the s_ra or s_dec columns are None.
        """
        query = f"SELECT s_ra, s_dec FROM cbd_lsstcam.exposure_quicklook WHERE exposure_id = {exposure_id}"

        self.log.debug(f"Waiting for WCS solution in ConsDB for exposure {exposure_id}")

        get_wcs_row = functools.partial(
            self.consdb_client.wait_for_row_to_exist,
            query=query,
            timeout=self.consdb_timeout,
        )

        wcs_table = await asyncio.get_running_loop().run_in_executor(None, get_wcs_row)

        if len(wcs_table) == 0:
            raise RuntimeError(
                f"WCS solution not available for exposure {exposure_id} after {self.consdb_timeout}s timeout"
            )

        row = wcs_table[0]
        measured_ra_deg = row["s_ra"]
        measured_dec_deg = row["s_dec"]

        if measured_ra_deg is None or measured_dec_deg is None:
            raise RuntimeError(
                f"WCS solution incomplete for exposure {exposure_id}: "
                f"s_ra={measured_ra_deg}, s_dec={measured_dec_deg}"
            )

        self.log.debug(
            f"Retrieved WCS solution: RA={measured_ra_deg:.6f} deg, Dec={measured_dec_deg:.6f} deg"
        )

        return measured_ra_deg, measured_dec_deg

    def calculate_offset(
        self,
        target_ra_deg: float,
        target_dec_deg: float,
        measured_ra_deg: float,
        measured_dec_deg: float,
    ):
        """Calculate the pointing offset.

        Parameters
        ----------
        target_ra_deg : float
            Target RA in degrees.
        target_dec_deg : float
            Target Dec in degrees.
        measured_ra_deg : float
            Measured RA in degrees from WCS.
        measured_dec_deg : float
            Measured Dec in degrees from WCS.

        Returns
        -------
        tuple
            Offset in RA, Dec, and total magnitude in arcseconds
            (offset_ra, offset_dec, magnitude).
        """
        offset_ra_deg = measured_ra_deg - target_ra_deg
        offset_dec_deg = measured_dec_deg - target_dec_deg

        offset_ra_arcsec = offset_ra_deg * 3600.0 * np.cos(np.deg2rad(target_dec_deg))
        offset_dec_arcsec = offset_dec_deg * 3600.0

        offset_magnitude_arcsec = np.sqrt(offset_ra_arcsec**2 + offset_dec_arcsec**2)

        return offset_ra_arcsec, offset_dec_arcsec, offset_magnitude_arcsec

    async def apply_pointing_offset(
        self, offset_ra_arcsec: float, offset_dec_arcsec: float
    ):
        """Apply the pointing offset to the telescope.

        Parameters
        ----------
        offset_ra_arcsec : float
            RA offset in arcseconds.
        offset_dec_arcsec : float
            Dec offset in arcseconds.
        """
        self.log.info(
            f"Applying pointing offset: RA={offset_ra_arcsec:.3f} arcsec, "
            f"Dec={offset_dec_arcsec:.3f} arcsec"
        )

        await self.mtcs.offset_xy(x=offset_ra_arcsec, y=offset_dec_arcsec, absorb=True)

        self.log.info("Pointing offset applied.")
