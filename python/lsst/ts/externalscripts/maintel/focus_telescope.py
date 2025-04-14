# This file is part of ts_maintel_standardscripts
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

__all__ = ["FocusTelescope"]

import abc
import asyncio
import types
import typing
import warnings
from collections import defaultdict

import numpy as np
import yaml
from astropy.table import QTable
from lsst.daf.butler import Butler
from lsst.ts import salobj
from lsst.ts.observatory.control import BaseCamera
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages

try:
    from lsst.ts.wep.task.fitDonutRadiusTask import (
        FitDonutRadiusTask,
        FitDonutRadiusTaskConfig,
    )

except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")

CMD_TIMEOUT = 100


class FocusTelescope(salobj.BaseScript, metaclass=abc.ABCMeta):
    """Focus telescope"""

    def __init__(self, index=1, descr="") -> None:
        super().__init__(
            index=index,
            descr=descr,
        )

        self.mtcs = None
        self._camera = None

        self.butler = None

    @property
    def camera(self) -> BaseCamera:
        if self._camera is not None:
            return self._camera
        else:
            raise RuntimeError("Camera not defined.")

    @camera.setter
    def camera(self, value: BaseCamera | None) -> None:
        self._camera = value

    def configure_butler(self) -> None:
        """Configure the butler."""
        if self.butler is None:
            self.butler = Butler("/repo/LSSTCam")
        else:
            self.log.debug("Butler already defined, skipping.")

    async def configure_camera(self) -> None:
        """Handle creating Camera object and waiting for remote to start."""
        if self._camera is None:
            self.log.debug("Creating Camera.")

            self._camera = LSSTCam(
                self.domain,
                log=self.log,
                tcs_ready_to_take_data=self.mtcs.ready_to_take_data,
            )
            await self._camera.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    async def configure_tcs(self) -> None:
        """Handle creating MTCS object and waiting for remote to start."""
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                log=self.log,
                intended_usage=MTCSUsages.Slew | MTCSUsages.StateTransition,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    @classmethod
    def get_schema(cls) -> typing.Dict[str, typing.Any]:
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_standardscripts/auxtel/FocusTelescope.yaml
            title: FocusTelescope v1
            description: Configuration for FocusTelescope Script.
            type: object
            properties:
              filter:
                description: Which filter to use when taking intra/extra focal images.
                type: string
              exposure_time:
                description: The exposure time to use when taking images (sec).
                type: number
                default: 30.
              threshold:
                description: Z offset threshold for convergence (um).
                type: number
                default: 50.0
              max_iter:
                description:  >-
                    Maximum number of iterations.
                type: integer
                default: 2
              program:
                description: >-
                    Optional name of the program this dataset belongs to.
                type: string
                default: CWFS
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              note:
                description: A descriptive note about the image being taken.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              ignore:
                  description: >-
                      CSCs from the group to ignore in status check. Name must
                      match those in self.group.components, e.g.; hexapod_1.
                  type: array
                  items:
                      type: string
            additionalProperties: false
            required:
              - filter
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config: types.SimpleNamespace) -> None:
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """
        await self.configure_tcs()
        await self.configure_camera()
        self.configure_butler()

        self.filter = config.filter
        self.exposure_time = config.exposure_time
        self.threshold = config.threshold
        self.max_iter = config.max_iter

        self.reason = config.reason
        self.program = config.program
        self.note = config.note

        if hasattr(config, "ignore"):
            self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata: salobj.type_hints.BaseMsgType) -> None:
        """Sets script metadata.

        Parameters
        ----------
        metadata : `salobj.type_hints.BaseMsgType`
            Script metadata topic. The information is set on the topic
            directly.
        """
        # Estimated duration is maximum number of iterations multiplied by
        # the time it takes to take the data (2 images) plus estimation on
        # processing the data (10s).
        metadata.duration = self.camera.filter_change_timeout + 2 * self.max_iter * (
            self.exposure_time + self.camera.read_out_time + self.camera.shutter_time
        )
        metadata.filter = f"{self.filter}"

    async def take_images(self, supplemented_group_id: str) -> None:
        """Take an image and trigger the RA pipelines"""

        # Take in-focus image
        image = await self.camera.take_acq(
            self.exposure_time,
            group_id=supplemented_group_id,
            reason="INFOCUS" + ("" if self.reason is None else f"_{self.reason}"),
            program=self.program,
            filter=self.filter,
            note=self.note,
        )
        visit_id = int(image[0])

        take_second_snap_task = asyncio.create_task(
            self.camera.take_acq(
                self.exposure_time,
                group_id=supplemented_group_id,
                reason="INFOCUS" + ("" if self.reason is None else f"_{self.reason}"),
                program=self.program,
                filter=self.filter,
                note=self.note,
            )
        )

        await self.mtcs.rem.mtaos.cmd_runWEP.set_start(
            visitId=visit_id,
            extraId=None,
            useOCPS=self.use_ocps,
            config=self.wep_config,
            timeout=2 * CMD_TIMEOUT,
        )
        await take_second_snap_task

        return visit_id

    async def compute_z_offset(self, image_id: int) -> float:
        """Compute z offset from donut radius.

        Parameters
        ----------
        image_id : `int`
            Image ID of the donut image.

        Returns
        -------
        z_offset : `float`
            Z offset in microns.

        Raises
        ------
        ValueError
            If no valid SW0+SW1 intra/extra detector pairs found in the data.
        """
        detector_pairs = [
            ("R00_SW0", "R00_SW1"),
            ("R04_SW0", "R04_SW1"),
            ("R40_SW0", "R40_SW1"),
            ("R44_SW0", "R44_SW1"),
        ]

        intra_datasets = self.butler.query_datasets(
            "donutStampsIntra",
            collections=["LSSTCam/raw/all", "LSSTCam/quickLook"],
            where=f"visit in ({image_id})",
        )
        extra_datasets = self.butler.query_datasets(
            "donutStampsExtra",
            collections=["LSSTCam/raw/all", "LSSTCam/quickLook"],
            where=f"visit in ({image_id})",
        )

        donut_stamps_intra = [self.butler.get(dataset) for dataset in intra_datasets]
        donut_stamps_extra = [self.butler.get(dataset) for dataset in extra_datasets]

        config = FitDonutRadiusTaskConfig()
        task = FitDonutRadiusTask(config=config)
        table = task.run(donut_stamps_intra, donut_stamps_extra).donutRadiiTable

        intra_avg = self.average_radii_by_detector(table[table["DFC_TYPE"] == "intra"])
        extra_avg = self.average_radii_by_detector(table[table["DFC_TYPE"] == "extra"])

        valid = any(
            sw0 in intra_avg and sw1 in extra_avg for sw0, sw1 in detector_pairs
        )
        if not valid:
            raise ValueError(
                "No valid SW0+SW1 intra/extra detector pairs found in the data."
            )

        focus_per_pair = {}
        for sw0, sw1 in detector_pairs:
            if sw0 in intra_avg and sw1 in extra_avg:
                N = 1.234  # f-number for Rubin
                pixel_to_um = 10  # pixel size in um
                nominal_defocus = 1500  # um
                l_intra = (
                    intra_avg[sw0] * np.sqrt(4 * N**2 - 1) * pixel_to_um
                    - nominal_defocus
                )
                l_extra = (
                    extra_avg[sw1] * np.sqrt(4 * N**2 - 1) * pixel_to_um
                    - nominal_defocus
                )

                mean_offset = (np.abs(l_extra) + np.abs(l_intra)) / 2
                if l_extra > 0 and l_intra < 0:
                    # Extra is positive and intra negative, focus is negative
                    focus_per_pair[f"{sw0}"] = -mean_offset
                elif l_extra < 0 and l_intra > 0:
                    # Extra is negative and intra positive, focus is positive
                    focus_per_pair[f"{sw0}"] = mean_offset
                else:
                    raise ValueError(
                        f"Unexpected donut radius values for {sw0} and {sw1}: "
                        f"{l_intra}, {l_extra}"
                    )

        return np.mean(list(focus_per_pair.values()))

    def average_radii_by_detector(qtable: QTable) -> typing.Dict[str, float]:
        """Average donut radii by detector.

        Parameters
        ----------
        qtable : `astropy.table.QTable`
            Table with donut radii.

        Returns
        -------
        result : `dict`
            Dictionary with average donut radii by detector.
        """
        result = defaultdict(list)
        for row in qtable:
            result[row["DET_NAME"]].append(row["RADIUS"])
        return {det: np.mean(radii) for det, radii in result.items()}

    async def arun(self, checkpoint: bool = False) -> None:
        """Focus telescope.
        This method runs the focus telescope script. It takes images
        and computes the z offset from the donut radius. If the z offset
        is within the threshold, it stops. Otherwise, it offsets the camera
        hexapod and continues until the maximum number of iterations is
        reached.

        Parameters
        ----------
        checkpoint : `bool`, optional
            Should issue checkpoints
        """
        for i in range(self.max_iter):
            self.log.debug(f"Focus telescope iteration {i + 1} starting...")

            if checkpoint:
                await self.checkpoint(
                    f"[{i + 1}/{self.max_iter}]: Focus telescope sequence starting..."
                )
                await self.checkpoint(f"[{i + 1}/{self.max_iter}]: Taking image...")

            # Take in-focus image and trigger WEP processing
            image_id = self.take_images(self.next_supplemented_group_id())
            await self.mtcs.rem.mtaos.evt_wavefrontError.flush()

            # Compute z offset with fitDonutRadius task
            z_offset = await self.compute_z_offset(
                image_id=image_id,
            )
            self.log.info(f"Computed Z offset is {z_offset} um.")

            # Check if corrections have converged. If they have, then we stop.
            if np.abs(z_offset) < self.threshold:
                self.log.info(
                    f"Z offset is within tolerance ({self.threshold} um). We are in focus!"
                )
                if checkpoint:
                    await self.checkpoint(
                        f"Z offset is within tolerance ({self.threshold} um). We are in focus!"
                    )
                return
            else:
                corrections = np.array(
                    [
                        0.0,
                        0.0,
                        z_offset,
                        0.0,
                        0.0,
                    ]
                )
                await self.mtcs.offset_camera_hexapod(-corrections)

        self.log.warning(
            f"Reached maximum iteration ({self.max_iter}) without focusing.\n"
        )

    async def assert_feasibility(self) -> None:
        """Verify that the telescope and camera are in a feasible state to
        execute the script.
        """
        await self.mtcs.assert_all_enabled()
        await self.camera.assert_all_enabled()

    async def run(self) -> None:
        """Execute script.

        This method simply call `arun` with `checkpoint=True`.
        """
        await self.assert_feasibility()
        await self.arun(True)
