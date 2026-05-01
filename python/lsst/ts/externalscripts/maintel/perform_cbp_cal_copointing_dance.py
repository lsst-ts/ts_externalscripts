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

__all__ = ["PerformCBPCalCopointingDance"]

import asyncio
import hashlib
import io
import json
from typing import Sequence

import numpy as np
import numpy.typing as npt
import scipy.optimize
import yaml
from lsst.cbp import CoordinateConverter, CoordinateConverterConfig, MaskInfo
from lsst.obs.lsst import LsstCam
from lsst.ts import salobj, utils
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.standardscripts.utils import get_s3_bucket

# CBP pointing model coefficients from laser-tracker calibration
IA = np.double(0.009627455249452715)
IE = np.double(0.016560332301849945)
AN = np.double(0.00765466501000224)
AW = np.double(0.0014086095361487236)
NP = np.double(-0.00967580856329838)
TF = np.double(-0.008512352047946233)
SA = np.double(0.0037899497583516392)
SE = np.double(0.0030070251181208096)


class PerformCBPCalCopointingDance(BaseBlockScript):
    """Perform a CBP Cal copointing spiral search.

    This script generates a hexagonal spiral pattern in either:
    - Pupil plane (position search): varies pupil position while holding
      focal plane position fixed
    - Focal plane (angle/incidence search): varies focal plane position
      while holding pupil position fixed

    At each point in the spiral, the script:
    1. Computes the required CBP and TMA pointings
       using the coordinate converter
    2. Moves the CBP to the calculated az/el
    3. Moves the TMA to the calculated az/el
    4. Takes an electrometer reading

    The resulting brightness measurements can then be fit with a 2D Gaussian
    to find the optimal center position.

    IMPORTANT: Both search types center the spiral around the provided
    center coordinates. The Gaussian fit center from one iteration should
    be ADDED to the previous center to get the new center for the next
    iteration.
    """

    def __init__(self, index):
        super().__init__(index=index, descr="Perform a CBP cal system pointing dance.")

        self.mtcs = None
        self.mtcalsys = None
        self.electrometer = None
        self.config_data = None
        self.electrometer = None

        self.long_timeout = 30
        self.cbp_move_timeout = 60
        self.electrometer_scan_duration = 1.0
        self.sequence_summary = dict()
        self.pointings_data = []

        self.converter_config = None
        self.coordinate_converter = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/perform_cbp_cal_copointing_dance.yaml
            title: PerformCBPCalCopointingDance v1
            description: Configuration for PerformCBPCalCopointingDance.
            type: object
            properties:
              search_type:
                description: Type of search to perform.
                type: string
                enum: ["angle", "position"]
                default: angle
              pupil_plane_x_center:
                description: X pupil plane position in mm for the center of the spiral
                type: number
                default: -3671.7
              pupil_plane_y_center:
                description: Y pupil plane position in mm for the center of the spiral
                type: number
                default: 3775.9
              focal_plane_x_center:
                description: X focal plane position in mm for the center of the spiral
                type: number
                default: -165.0
              focal_plane_y_center:
                description: Y focal plane position in mm for the center of the spiral
                type: number
                default: -1.4
              spacing:
                description: Spacing between points of the hexagonal spiral in mm
                type: number
                default: 26.0
              radius:
                description: Outer radius of the spiral search pattern in mm
                type: number
                default: 126.0
              electrometer_scan_duration:
                description: Duration of each electrometer scan in seconds
                type: number
                default: 1.0
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config) -> None:
        """Configure the script with search parameters and create remotes."""
        # Create MTCS for telescope control
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

        # Handle creating the MTCalsys object and waiting remote to start.
        if self.mtcalsys is None:
            self.log.debug("Creating MTCalsys.")
            self.mtcalsys = MTCalsys(domain=self.domain, log=self.log)
            await self.mtcalsys.start_task

        else:
            self.log.debug("MTCalsys already defined, skipping.")

        if self.electrometer is None:
            self.electrometer = getattr(
                self.mtcalsys.rem,
                f"electrometer_{self.mtcalsys.electrometer_cbpcal_index}",
            )
        else:
            self.log.debug("Electrometer already defined, skipping.")

        # Store configuration
        self.search_type = config.search_type
        self.pupil_plane_x_center = config.pupil_plane_x_center
        self.pupil_plane_y_center = config.pupil_plane_y_center
        self.focal_plane_x_center = config.focal_plane_x_center
        self.focal_plane_y_center = config.focal_plane_y_center
        self.spacing = config.spacing
        self.radius = config.radius
        self.electrometer_scan_duration = getattr(
            config, "electrometer_scan_duration", 1.0
        )

        # Create the coordinate converter
        self.create_coordinate_converter()

        self.log.info(
            f"Configured {self.search_type} search: "
            f"pupil_center=({self.pupil_plane_x_center}, {self.pupil_plane_y_center}), "
            f"focal_center=({self.focal_plane_x_center}, {self.focal_plane_y_center}), "
            f"spacing={self.spacing}, radius={self.radius}"
        )

    def hex_spiral(self, spacing: float, radius: float) -> npt.NDArray[np.float64]:
        """Generate a hexagonal spiral pattern.

        Parameters
        ----------
        spacing : float
            Distance between adjacent points in mm.
        radius : float
            Maximum radius of the spiral in mm.

        Returns
        -------
        pts : np.ndarray
            Array of (x, y) coordinates in mm, ordered from center outward
            in a spiral pattern.
        """
        e1 = np.array([spacing, 0.0])
        e2 = np.array([0.5 * spacing, np.sqrt(3) / 2 * spacing])

        pts, rings, angles = [], [], []

        N = int(np.ceil(radius / spacing * 2)) + 1
        for i in range(-N, N + 1):
            for j in range(-N, N + 1):
                p = i * e1 + j * e2
                r_e = np.linalg.norm(p)
                if r_e <= radius:
                    x_c = i
                    z_c = j
                    y_c = -x_c - z_c
                    k = (abs(x_c) + abs(y_c) + abs(z_c)) // 2
                    pts.append(p)
                    rings.append(k)
                    angles.append(np.arctan2(p[1], p[0]))

        pts = np.array(pts)
        rings = np.array(rings)
        angles = np.array(angles)

        order = np.lexsort((angles, rings))
        pts = pts[order]

        return pts

    def point_cbp_internal(
        self, commanded_azel: Sequence[float]
    ) -> npt.NDArray[np.float64]:
        """Apply CBP pointing model to get expected pointing.

        Parameters
        ----------
        commanded_azel : Sequence[float]
            Commanded (az, el) in radians, counter-clockwise convention.

        Returns
        -------
        np.ndarray
            Expected pointing (az, el) in radians,
            counter-clockwise convention.
        """
        phi, lam = commanded_azel
        cos_phi = np.cos(phi)
        sin_phi = np.sin(phi)
        cos_lambda = np.cos(lam)
        tan_lambda = np.tan(lam)
        return commanded_azel + np.array(
            [
                IA + AN * tan_lambda * cos_phi + AW * tan_lambda * sin_phi + SA * phi,
                IE + NP * sin_phi + TF * cos_lambda + SE * lam,
            ]
        )

    def cbp_pointing_internal(
        self, target_azel: Sequence[float]
    ) -> npt.NDArray[np.float64]:
        """Invert CBP pointing model to get commanded position.

        Parameters
        ----------
        target_azel : Sequence[float]
            Target (az, el) in radians, counter-clockwise convention.

        Returns
        -------
        np.ndarray
            Commanded (az, el) in radians to achieve target pointing.
        """

        def objective(commanded_azel):
            return target_azel - self.point_cbp_internal(commanded_azel)

        return scipy.optimize.root(objective, target_azel).x

    def cbp_pointing(self, target_azel: Sequence[float]) -> npt.NDArray[np.float64]:
        """Get commanded CBP position for a target pointing.

        Parameters
        ----------
        target_azel : Sequence[float]
            Target (az, el) in degrees, clockwise convention.

        Returns
        -------
        np.ndarray
            Commanded (az, el) in degrees, clockwise convention.
        """
        return np.degrees(
            self.cbp_pointing_internal(np.radians(target_azel) * [-1.0, 1.0])
        ) * [-1.0, 1.0]

    def create_coordinate_converter(self) -> None:
        """Create the CBP-to-telescope coordinate converter."""
        self.converter_config = CoordinateConverterConfig(
            cbpPosition=(-12392, -433, 7708),
            cbpFocalLength=635,
            cbpFlipX=False,
            cbpAzimuthOffsetDeg=2,
            cbpAzimuthScale=-1,
            cbpAltitudeOffsetDeg=0,
            cbpAltitudeScale=1,
            cbpAltitudeLimitsDeg=(-69, 45),
            telPupilOffset=2000,
            telPupilDiameter=8400,
            telPupilObscurationDiameter=5100,
            telFocalPlaneDiameter=72,
            telFlipX=False,
            telAzimuthOffsetDeg=90,
            telAzimuthScale=-1,
            telAltitudeOffsetDeg=0,
            telAltitudeScale=1,
            telAltitudeLimitsDeg=(0, 90),
            telRotOffsetDeg=0,
            telRotScale=1,
            defaultDetector="LSSTCam",
        )

        center_hole = [(0, 0)]
        mask_center_hole = MaskInfo(
            "center_hole", defaultHole=0, holePositions=center_hole, holeNames=None
        )
        cam = LsstCam.getCamera()

        self.coordinate_converter = CoordinateConverter(
            config=self.converter_config, maskInfo=mask_center_hole, cameraGeom=cam
        )

    def adjust_pointing(
        self, use_cbp_pointing_model: bool = True
    ) -> npt.NDArray[np.float64]:
        """Get TMA and CBP pointings from current coordinate converter state.

        Parameters
        ----------
        use_cbp_pointing_model : bool
            Whether to apply the CBP pointing model correction.

        Returns
        -------
        np.ndarray
            Array of shape (2, 2): [[tel_az, tel_el], [cbp_az, cbp_el]]
            in degrees, normalized to [-180, 180).
        """
        tel_az = self.coordinate_converter.telAzAltObserved.getLongitude().asDegrees()
        tel_el = self.coordinate_converter.telAzAltObserved.getLatitude().asDegrees()
        cbp_az = self.coordinate_converter.cbpAzAltObserved.getLongitude().asDegrees()
        cbp_el = self.coordinate_converter.cbpAzAltObserved.getLatitude().asDegrees()

        if use_cbp_pointing_model:
            [cbp_az, cbp_el] = self.cbp_pointing([cbp_az, cbp_el])

        # Normalize to [-180, 180)
        tel_az = (tel_az + 180.0) % 360.0 - 180.0
        tel_el = (tel_el + 180.0) % 360.0 - 180.0
        cbp_az = (cbp_az + 180.0) % 360.0 - 180.0
        cbp_el = (cbp_el + 180.0) % 360.0 - 180.0

        return np.array([[tel_az, tel_el], [cbp_az, cbp_el]])

    def generate_pointings(self) -> list:
        """Generate all pointings for the spiral search.

        For 'angle' search: varies focal plane position around
        the focal_plane center while holding pupil position fixed.

        For 'position' search: varies pupil plane position around the
        pupil_plane center while holding focal plane position fixed.

        Returns
        -------
        list
            List of pointing arrays, each of shape (2, 2):
            [[tel_az, tel_el], [cbp_az, cbp_el]]
        """
        pts = self.hex_spiral(self.spacing, self.radius)
        self.log.info(f"Generated {len(pts)} spiral points")

        pupil_center = (self.pupil_plane_x_center, self.pupil_plane_y_center)
        focal_center = (self.focal_plane_x_center, self.focal_plane_y_center)

        pointings = []
        for pt in pts:
            if self.search_type == "angle":
                # Angle/incidence search: vary focal plane, hold pupil fixed
                # IMPORTANT: Center the search around focal_center, not (0,0)
                focal_pos = (focal_center[0] + pt[0], focal_center[1] + pt[1])
                self.coordinate_converter.setFocalPlanePos(
                    pupilPos=pupil_center, focalPlanePos=focal_pos
                )
            else:
                # Position search: vary pupil plane, hold focal plane fixed
                pupil_pos = (pupil_center[0] + pt[0], pupil_center[1] + pt[1])
                self.coordinate_converter.setFocalPlanePos(
                    pupilPos=pupil_pos, focalPlanePos=focal_center
                )

            pointings.append(self.adjust_pointing(use_cbp_pointing_model=True))

        return pointings

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""
        pts = self.hex_spiral(self.spacing, self.radius)
        n_points = len(pts)

        # Estimate time per point: CBP move + TMA settle + electrometer scan
        time_per_point = 10 + 5 + self.electrometer_scan_duration + 2  # ~18s

        total_duration = n_points * time_per_point
        metadata.duration = total_duration

    async def move_cbp(self, azimuth: float, elevation: float) -> None:
        """Move the CBP to the specified position.

        Parameters
        ----------
        azimuth : float
            Target azimuth in degrees.
        elevation : float
            Target elevation in degrees.
        """
        self.log.debug(f"Moving CBP to az={azimuth:.3f}, el={elevation:.3f}")
        await self.mtcalsys.rem.cbp.cmd_move.set_start(
            azimuth=azimuth,
            elevation=elevation,
            timeout=self.cbp_move_timeout,
        )

    async def move_tma(self, azimuth: float, elevation: float) -> None:
        """Move the TMA to the specified position.

        Parameters
        ----------
        azimuth : float
            Target azimuth in degrees.
        elevation : float
            Target elevation in degrees.
        """
        self.log.debug(f"Moving TMA to az={azimuth:.3f}, el={elevation:.3f}")

        await self.mtcs.point_azel(
            az=azimuth,
            el=elevation,
            target_name="CBPCal",
            ignore=["mtdome", "mtdometrajectory"],
        )

    async def take_electrometer_scan(self) -> None:
        """Take an electrometer scan."""
        self.log.debug(
            f"Taking electrometer scan for {self.electrometer_scan_duration}s"
        )
        await self.electrometer.cmd_startScanDt.set_start(
            scanDuration=self.electrometer_scan_duration,
            timeout=self.electrometer_scan_duration + 10,
        )

    async def prepare_summary_table(self):
        """Prepare the summary table for results."""
        self.sequence_summary = {}

        date_begin = utils.astropy_time_from_tai_unix(utils.current_tai()).isot
        self.sequence_summary["date_begin_tai"] = date_begin
        self.sequence_summary["script_index"] = self.salinfo.index
        self.sequence_summary["search_type"] = self.search_type
        self.sequence_summary["pupil_center"] = [
            self.pupil_plane_x_center,
            self.pupil_plane_y_center,
        ]
        self.sequence_summary["focal_center"] = [
            self.focal_plane_x_center,
            self.focal_plane_y_center,
        ]
        self.sequence_summary["spacing"] = self.spacing
        self.sequence_summary["radius"] = self.radius

    async def publish_sequence_summary(self):
        """Write sequence summary to LFA as a json file."""
        try:
            # Add the spiral points to the summary
            pts = self.hex_spiral(self.spacing, self.radius)
            self.sequence_summary["spiral_points"] = pts.tolist()
            self.sequence_summary["pointings_data"] = self.pointings_data

            date_end = utils.astropy_time_from_tai_unix(utils.current_tai()).isot
            self.sequence_summary["date_end_tai"] = date_end

            sequence_summary_payload = json.dumps(self.sequence_summary).encode()
            file_object = io.BytesIO()
            byte_size = file_object.write(sequence_summary_payload)
            file_object.seek(0)

            s3bucket = get_s3_bucket()

            key = s3bucket.make_key(
                salname=self.salinfo.name,
                salindexname=self.salinfo.index,
                generator="publish_sequence_summary",
                date=utils.astropy_time_from_tai_unix(utils.current_tai()),
                other=self.obs_id,
                suffix=".json",
            )

            await s3bucket.upload(fileobj=file_object, key=key)

            url = f"{s3bucket.service_resource.meta.client.meta.endpoint_url}/{s3bucket.name}/{key}"

            md5 = hashlib.md5()
            md5.update(sequence_summary_payload)

            await self.evt_largeFileObjectAvailable.set_write(
                id=self.obs_id,
                url=url,
                generator="publish_sequence_summary",
                mimeType="JSON",
                byteSize=byte_size,
                checkSum=md5.hexdigest(),
                version=1,
            )

            self.log.info(f"Published sequence summary to {url}")

        except Exception:
            msg = "Failed to save summary table."
            self.log.exception(msg)
            raise RuntimeError(msg)

    async def run_block(self):
        """Execute the CBP Cal copointing spiral dance.

        For each point in the hexagonal spiral:
        1. Compute CBP and TMA pointings
        2. Move CBP to position
        3. Move TMA to position
        4. Take electrometer reading
        """
        await self.prepare_summary_table()

        # Generate all pointings
        pointings = self.generate_pointings()
        pts = self.hex_spiral(self.spacing, self.radius)

        self.log.info(
            f"Starting {self.search_type} search with {len(pointings)} points"
        )

        for i, (pt, pointing) in enumerate(zip(pts, pointings)):
            self.log.info(
                f"Point {i+1}/{len(pointings)}: "
                f"offset=({pt[0]:.1f}, {pt[1]:.1f}) mm"
            )

            tel_az, tel_el = pointing[0]
            cbp_az, cbp_el = pointing[1]

            # Move CBP first (faster)
            await self.move_cbp(cbp_az, cbp_el)

            # Move TMA
            await self.move_tma(tel_az, tel_el)

            # Small settle time
            await asyncio.sleep(1.0)

            # Take electrometer reading
            await self.take_electrometer_scan()

            # Record this pointing
            self.pointings_data.append(
                {
                    "index": i,
                    "spiral_offset": pt.tolist(),
                    "tel_az": tel_az,
                    "tel_el": tel_el,
                    "cbp_az": cbp_az,
                    "cbp_el": cbp_el,
                }
            )

            # Check for stop signal
            await self.checkpoint(f"Completed point {i+1}/{len(pointings)}")

        await self.publish_sequence_summary()

        self.log.info(f"Completed {self.search_type} search.")
