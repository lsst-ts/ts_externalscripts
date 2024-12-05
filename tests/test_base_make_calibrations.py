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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import asyncio
import logging
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from lsst.ts import standardscripts
from lsst.ts.externalscripts.base_make_calibrations import BaseMakeCalibrations

logger = logging.getLogger(__name__)
logger.propagate = True


class TestMakeCalibrations(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TestBaseMakeCalibrations(index=index)
        return (self.script,)

    @unittest.mock.patch(
        "lsst.ts.standardscripts.BaseBlockScript.obs_id", "202306060001"
    )
    async def test_configure(self):
        async with self.make_script():
            n_bias = 2
            n_dark = 2
            exp_times_dark = 10
            n_flat = 4
            exp_times_flat = [10, 10, 50, 50]
            detectors = [0, 1, 2]
            n_processes = 4
            program = "BLOCK-123"
            reason = "SITCOM-321"

            self.script.get_obs_id = unittest.mock.AsyncMock(
                side_effect=["202306060001"]
            )

            await self.configure_script(
                n_bias=n_bias,
                n_dark=n_dark,
                n_flat=n_flat,
                exp_times_dark=exp_times_dark,
                exp_times_flat=exp_times_flat,
                detectors=detectors,
                n_processes=n_processes,
                program=program,
                reason=reason,
                script_mode="BIAS_DARK_FLAT",
                generate_calibrations=True,
                do_verify=True,
            )

            assert self.script.config.n_bias == n_bias
            assert self.script.config.n_dark == n_dark
            assert self.script.config.n_flat == n_flat
            assert self.script.config.exp_times_dark == exp_times_dark
            assert self.script.config.exp_times_flat == exp_times_flat
            assert self.script.config.n_processes == n_processes
            assert self.script.config.detectors == detectors
            assert self.script.program == program
            assert self.script.reason == reason

            assert (
                # from the configure method in BaseBlockScript
                self.script.checkpoint_message
                == "TestBaseMakeCalibrations BLOCK-123 202306060001 SITCOM-321"
            )

    async def test_process_images_calib_no_verify(self):
        async with self.make_script():
            await self.configure_script(
                n_bias=2,
                n_dark=2,
                n_flat=4,
                exp_times_dark=10,
                exp_times_flat=[10, 10, 50, 50],
                n_processes=4,
                program="BLOCK-123",
                reason="SITCOM-321",
                script_mode="BIAS_DARK_FLAT",
                generate_calibrations=True,
                do_verify=False,
            )

            self.script.call_pipetask = AsyncMock(
                return_value={"jobId": "job_calib_123"}
            )
            self.script.process_verification = AsyncMock()
            self.script.certify_calib = AsyncMock()
            self.script.process_verification = AsyncMock()

            im_type = "BIAS"
            await self.script.process_images(im_type)
            self.script.call_pipetask.assert_called_with(im_type)
            self.script.process_verification.assert_not_called()
            self.script.certify_calib.assert_called_with(im_type, "job_calib_123")

    async def test_process_images_calib_and_verify(self):
        async with self.make_script():
            await self.configure_script(
                n_bias=2,
                n_dark=2,
                n_flat=4,
                exp_times_dark=10,
                exp_times_flat=[10, 10, 50, 50],
                n_processes=4,
                program="BLOCK-123",
                reason="SITCOM-321",
                script_mode="BIAS_DARK_FLAT",
                generate_calibrations=True,
                do_verify=True,
            )

            self.script.call_pipetask = AsyncMock(
                return_value={"jobId": "job_calib_123"}
            )
            self.script.certify_calib = AsyncMock()
            self.script.verify_calib = AsyncMock(
                return_value={"jobId": "verify_job123"}
            )

            # Wrap the real process_verification method
            original_process_verification = self.script.process_verification
            self.script.process_verification = AsyncMock(
                wraps=original_process_verification
            )
            self.script.check_verification_stats = AsyncMock(
                return_value={"CERTIFY_CALIB": True}
            )
            self.script.analyze_report_check_verify_stats = AsyncMock()

            im_type = "BIAS"
            await self.script.process_images(im_type)
            self.script.call_pipetask.assert_called_with(im_type)
            self.script.process_verification.assert_called_with(
                im_type, "job_calib_123"
            )
            self.script.certify_calib.assert_called_with(im_type, "job_calib_123")

    async def test_wait_for_background_tasks(self):
        async with self.make_script():

            # Create a future that will not complete
            async def long_running_task():
                await asyncio.sleep(100)  # Sleep longer than the timeout

            mock_task = asyncio.create_task(long_running_task())
            self.script.background_tasks = [mock_task]

            await self.configure_script(
                n_bias=2,
                n_dark=2,
                n_flat=4,
                exp_times_dark=10,
                exp_times_flat=[10, 10, 50, 50],
                n_processes=4,
                program="BLOCK-123",
                reason="SITCOM-321",
                script_mode="BIAS_DARK_FLAT",
                generate_calibrations=True,
                do_verify=True,
            )

            # Set a short timeout to force timeout
            self.script.config.background_task_timeout = 0.1

            with patch.object(
                self.script.log, "warning", new=MagicMock()
            ) as mock_log_warning:
                await self.script.wait_for_background_tasks()

                assert mock_task.cancelled(), "Task was not cancelled"

                assert self.script.background_tasks == []

                mock_log_warning.assert_called_with(
                    "Background tasks did not " "complete before timeout."
                )

    async def test_certify_calib_failure(self):
        async with self.make_script():
            await self.configure_script(
                n_bias=2,
                n_dark=2,
                n_flat=4,
                exp_times_dark=10,
                exp_times_flat=[10, 10, 50, 50],
                n_processes=4,
                program="BLOCK-123",
                reason="SITCOM-321",
                script_mode="BIAS_DARK_FLAT",
                generate_calibrations=True,
                do_verify=True,
            )

            self.script.certify_calib_failed = False

            self.script.call_pipetask = AsyncMock(return_value={"jobId": "job123"})

            self.script.ocps.cmd_execute.set_start = AsyncMock(
                return_value=MagicMock(result='{"job_id": "job123"}')
            )

            self.script.ocps.evt_job_result.next = AsyncMock(
                return_value=MagicMock(result='{"jobId": "job123"}')
            )

            self.script.verify_calib = AsyncMock(
                return_value={"jobId": "verify_job123"}
            )

            self.script.check_verification_stats = AsyncMock(
                return_value={"CERTIFY_CALIB": False}
            )

            self.script.analyze_report_check_verify_stats = AsyncMock()

            with patch.object(
                self.script.log, "exception", new=MagicMock()
            ) as mock_log_exception:
                await self.script.process_images("BIAS")

                # Verify that exception was not logged
                # (since failure is handled gracefully)
                mock_log_exception.assert_not_called()


class TestBaseMakeCalibrations(BaseMakeCalibrations):
    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="Test script",
        )

    @classmethod
    def get_schema(cls):
        url = "https://github.com/lsst-ts/"
        path = (
            "ts_externalscripts/blob/main/python/lsst/ts/externalscripts/"
            "/make_comcam_calibrations.py"
        )
        schema = f"""
            $schema: http://json-schema.org/draft-07/schema#
            $id: {url}/{path}
            title: MakeComCamCalibrations v1
            description: Configuration for making a LSSTComCam combined calibrations SAL Script.
            type: object
            properties:
                detectors:
                    description: Detector IDs. If omitted, all 9 LSSTComCam detectors \
                        will be used.
                    type: array
                    items:
                      - type: integer
                    minContains: 0
                    maxContains: 8
                    minItems: 0
                    maxItems: 9
                    uniqueItems: true
                    default: []
                filter:
                    description: Filter name or ID; if omitted the filter is not changed.
                    anyOf:
                      - type: string
                      - type: integer
                        minimum: 1
                      - type: "null"
                    default: null
                input_collections_bias:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to the bias pipetask.
                    default: "LSSTComCam/calib"
                input_collections_verify_bias:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to \
                        the verify (bias) pipetask.
                    default: "LSSTComCam/calib"
                input_collections_dark:
                    type: string
                    descriptor: Additional comma-separarted input collections to pass to the dark pipetask.
                    default: "LSSTComCam/calib"
                input_collections_verify_dark:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to \
                        the verify (dark) pipetask.
                    default: "LSSTComCam/calib"
                input_collections_flat:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to the flat pipetask.
                    default: "LSSTComCam/calib"
                input_collections_verify_flat:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to \
                        the verify (flat) pipetask.
                    default: "LSSTComCam/calib"
                input_collections_defects:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to the defects pipetask.
                    default: "LSSTComCam/calib"
                input_collections_ptc:
                    type: string
                    descriptor: Additional comma-separated input collections to pass to the \
                        Photon Transfer Curve pipetask.
                    default: "LSSTComCam/calib"
                calib_collection:
                    type: string
                    descriptor: Calibration collection where combined calibrations will be certified into.
                    default: "LSSTComCam/calib/daily"
                repo:
                    type: string
                    descriptor: Butler repository.
                    default: "/repo/LSSTComCam"
            additionalProperties: false
            """
        schema_dict = yaml.safe_load(schema)
        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    @property
    def ocps_group(self):
        return MagicMock()

    @property
    def ocps(self):
        return MagicMock()

    @property
    def camera(self):
        return MagicMock()

    def get_instrument_configuration(self):
        return {}

    @property
    def instrument_name(self):
        return "TestInstrument"

    @property
    def pipeline_instrument(self):
        return "TestPipelineInstrument"

    @property
    def detectors(self):
        return [0, 1, 2]

    @property
    def n_detectors(self):
        return 3

    @property
    def image_in_oods(self):
        return MagicMock()


if __name__ == "__main__":
    unittest.main()
