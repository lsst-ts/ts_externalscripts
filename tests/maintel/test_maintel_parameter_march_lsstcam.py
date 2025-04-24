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

import types
import unittest
import unittest.mock as mock

import numpy as np
import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.parameter_march_lsstcam import (
    ParameterMarchLSSTCam,
)
from lsst.ts.observatory.control.utils.enums import DOFName


class TestParameterMarchLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = ParameterMarchLSSTCam(index=index)

        self.mock_mtcs()
        self.mock_camera()
        self.mock_ocps()

        return (self.script,)

    def mock_mtcs(self):
        """Mock MTCS instances and its methods."""
        self.script.mtcs = mock.AsyncMock()
        self.script.mtcs.assert_liveliness = mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.point_azel = mock.AsyncMock()
        self.script.mtcs.stop_tracking = mock.AsyncMock()
        self.script.mtcs.start_tracking = mock.AsyncMock()

        self.script.mtcs.rem.mtaos = unittest.mock.AsyncMock()
        self.script.mtcs.rem.mtaos.cmd_offsetDOF.attach_mock(
            unittest.mock.Mock(
                return_value=types.SimpleNamespace(value=np.zeros(len(DOFName)))
            ),
            "DataType",
        )

        self.script.format_values = unittest.mock.AsyncMock()
        self.script.format_values.return_value = (
            [f"+{i*0.1:.2f} um" for i in range(5)],
            [f"+{i*0.1:.2f} arcsec" for i in range(5, 10)],
            [f"+{i*0.1:.2f} um" for i in range(10, 30)],
            [f"+{i*0.1:.2f} um" for i in range(30, 50)],
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_acq = mock.AsyncMock(return_value=[1234])

    def mock_ocps(self):
        """Mock OCPS instance and its methods."""
        self.script.ocps = mock.Mock()
        self.script.ocps.cmd_execute = mock.Mock()
        self.script.ocps.cmd_execute.set_start = mock.AsyncMock()

    async def test_configure(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": 50,
            "range": 1,
            "n_steps": 11,
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.az == 35
            assert self.script.config.el == 15
            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.dofs, [1] * 50)
            assert self.script.rotation_sequence == [50] * 11
            assert self.script.step_sequence == np.linspace(-0.5, 0.5, 11).tolist()
            assert self.script.range == 1
            assert self.script.n_steps == 11
            assert self.script.config.program == "BLOCK-TXXX"

    async def test_configure_step_and_rotation_sequence(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.az == 35
            assert self.script.config.el == 15
            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.dofs, [1] * 50)
            assert self.script.range == 400
            assert self.script.n_steps == 5
            assert self.script.step_sequence == [0, 100, 200, 300, 400]
            assert self.script.rotation_sequence == [10, 20, 30, 40, 50]
            assert self.script.config.program == "BLOCK-TXXX"

    async def test_configure_ignore(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "ignore": ["mtm1m3", "mtrotator"],
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            # Mock the components_attr to contain the ignored components
            self.script.mtcs.components_attr = ["mtm1m3", "mtrotator"]
            self.script.camera.components_attr = []

            await self.configure_script(**config)

            assert self.script.config.az == 35
            assert self.script.config.el == 15
            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.dofs, [1] * 50)
            assert self.script.range == 400
            assert self.script.n_steps == 5
            assert self.script.step_sequence == [0, 100, 200, 300, 400]
            assert self.script.rotation_sequence == [10, 20, 30, 40, 50]
            assert self.script.config.program == "BLOCK-TXXX"

            # Verify ignoring components
            self.script.mtcs.disable_checks_for_components.assert_called_once_with(
                components=config["ignore"]
            )
            self.script.camera.disable_checks_for_components.assert_called_once_with(
                components=config["ignore"]
            )

    async def test_configure_dof_index(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dof_index": 17,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "ignore": ["mtm1m3", "mtrotator"],
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            # Mock the components_attr to contain the ignored components
            self.script.mtcs.components_attr = ["mtm1m3", "mtrotator"]
            self.script.camera.components_attr = []

            await self.configure_script(**config)

            assert self.script.config.az == 35
            assert self.script.config.el == 15
            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            dofs_expected = np.zeros(50)
            dofs_expected[17] = 1
            assert np.array_equal(self.script.dofs, dofs_expected)
            assert self.script.range == 400
            assert self.script.n_steps == 5
            assert self.script.step_sequence == [0, 100, 200, 300, 400]
            assert self.script.rotation_sequence == [10, 20, 30, 40, 50]
            assert self.script.config.program == "BLOCK-TXXX"

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "az": 35,
                "el": 15,
                "filter": "g",
                "exp_time": 30.0,
                "dofs": [1] * 51,
                "rotation_sequence": [10, 20, 30, 40, 50],
                "step_sequence": [0, 100, 200, 300, 400],
                "ignore": ["mtm1m3", "mtrotator"],
            },
            {
                "az": 35,
                "el": 15,
                "filter": "g",
                "exp_time": 30.0,
                "dofs": [1] * 50,
                "rotation_sequence": [10, 20, 30, 40, 50],
                "range": 1,
                "ignore": ["mtm1m3", "mtrotator"],
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_parameter_march(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # Check if the hexapod moved the expected number of times
            assert (
                self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.call_count
                == self.script.n_steps + 1
            )

            # Check if the camera took the expected number of images
            assert self.script.lsstcam.take_acq.call_count == self.script.n_steps

            # Check if the OCPS command was called
            assert self.script.ocps.cmd_execute.set_start.call_count == 0

    async def test_parameter_march_sim_mode(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "sim": True,
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # Check if the hexapod moved the expected number of times
            assert (
                self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.call_count
                == self.script.n_steps + 1
            )

            # Check if the camera took the expected number of images
            assert self.script.lsstcam.take_acq.call_count == self.script.n_steps

            # Check if the OCPS command was called
            assert self.script.ocps.cmd_execute.set_start.call_count == 0

            # Verify that simulation mode is set correctly
            assert self.script.lsstcam.simulation_mode

    async def test_cleanup(self):
        config = {
            "az": 35,
            "el": 15,
            "filter": "g",
            "exp_time": 30.0,
            "dofs": [1] * 50,
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "program": "BLOCK-TXXX",
        }

        async with self.make_script():
            await self.configure_script(**config)

            # Simulate an error during the parameter march to trigger cleanup
            self.script.iterations_started = True
            self.script.total_offset = 400  # Simulate some offset
            with mock.patch.object(
                self.script, "parameter_march", side_effect=Exception("Test exception")
            ):
                with pytest.raises(Exception):
                    await self.script.run_block()

            await self.script.cleanup()

            # Ensure the hexapod is returned to the original position
            offset_dof_data = self.script.mtcs.rem.mtaos.cmd_offsetDOF.DataType()
            for i, dof_offset in enumerate(
                self.script.dofs * -self.script.total_offset
            ):
                offset_dof_data.value[i] = dof_offset
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.assert_any_call(
                data=offset_dof_data
            )

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "parameter_march_lsstcam.py"
        await self.check_executable(script_path)

    async def test_executable_triplet(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "parameter_march_triplet_lsstcam.py"
        await self.check_executable(script_path)
