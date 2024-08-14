# This file is part of ts_standardscripts
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

import unittest
import unittest.mock as mock

import pytest
from lsst.ts import salobj, externalscripts
from lsst.ts.observatory.control.utils.enums import DOFName
from lsst.ts.standardscripts.maintel.parameter_march_comcam import ParameterMarchComCam


class TestParameterMarchComCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = ParameterMarchComCam(index=index)

        self.mock_mtcs()
        self.mock_camera()
        self.mock_tcs()
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
        self.script.mtcs.rem.mtaos.configure_mock(
            **{
                "cmd_offsetDOF.start": unittest.mock.AsyncMock(),
                "cmd_offsetDOF.DataType.return_value": types.SimpleNamespace(value=np.zeros(len(DOFName))),
            }
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.comcam = mock.AsyncMock()
        self.script.comcam.assert_liveliness = mock.AsyncMock()
        self.script.comcam.assert_all_enabled = mock.AsyncMock()
        self.script.comcam.take_acq = mock.AsyncMock(return_value=[1234])
        self.script.comcam.take_cwfs = mock.AsyncMock(return_value=[12345])

    def mock_ocps(self):
        """Mock OCPS instance and its methods."""
        self.script.ocps = mock.Mock()
        self.script.ocps.cmd_execute = mock.Mock()
        self.script.ocps.cmd_execute.set_start = mock.AsyncMock()

    async def test_configure(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": 50,
            "range": 1,
            "n_steps": 11
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.config.dofs, np.ones(50))
            assert self.script.config.rotation_sequence == [50]*11
            assert self.script.config.step_sequence == [-1, -0.8, -0.6, -0.4, -0.2, 0, 0.2, 0.4, 0.6, 0.8, 1]
            assert self.script.config.range == 1
            assert self.script.config.n_steps == 11

    async def test_configure_step_and_rotation_sequence(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.config.dofs, np.ones(50))
            assert self.script.config.range == 400
            assert self.script.config.n_steps == 5
            assert self.script.config.step_sequence == [0, 100, 200, 300, 400]
            assert self.script.config.rotation_sequence == [10, 20, 30, 40, 50]

    async def test_configure_ignore(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "ignore": ["mtm1m3", "mtrotator"],
        }

        async with self.make_script():
            # Mock the components_attr to contain the ignored components
            self.script.mtcs.components_attr = ["mtm1m3", "mtrotator"]
            self.script.camera.components_attr = []

            await self.configure_script(**config)

            assert self.script.config.filter == "g"
            assert self.script.config.exp_time == 30.0
            assert np.array_equal(self.script.config.dofs, np.ones(50))
            assert self.script.config.range == 400
            assert self.script.config.n_steps == 5
            assert self.script.config.step_sequence == [0, 100, 200, 300, 400]
            assert self.script.config.rotation_sequence == [10, 20, 30, 40, 50]

            # Verify that the ignored components are correctly set to False
            assert not self.script.mtcs.check.mtm1m3
            assert not self.script.mtcs.check.mtrotator

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "filter": "g",
                "exp_time": 30.0,
                "dofs": np.ones(51),
                "rotation_sequence": [10, 20, 30, 40, 50],
                "step_sequence": [0, 100, 200, 300, 400],
                "ignore": ["mtm1m3", "mtrotator"],
            },
            {
                "filter": "g",
                "exp_time": 30.0,
                "dofs": np.ones(50),
                "rotation_sequence": [10, 20, 30, 40, 50, 55],
                "step_sequence": [0, 100, 200, 300, 400],
                "ignore": ["mtm1m3", "mtrotator"],
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_parameter_march(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # Check if the hexapod moved the expected number of times
            assert (
                self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.call_count
                == config["n_steps"] + 1
            )

            # Check if the camera took the expected number of images
            assert self.script.comcam.take_acq.call_count == config["n_steps"]

            # Check if the OCPS command was called
            self.script.ocps.cmd_execute.set_start.assert_called_once()

    async def test_focus_sweep_sim_mode(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
            "sim": True,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # Check if the hexapod moved the expected number of times
            assert (
                self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.call_count
                == config["n_steps"] + 1
            )

            # Check if the camera took the expected number of images
            assert self.script.comcam.take_acq.call_count == config["n_steps"]

            # Check if the OCPS command was called
            self.script.ocps.cmd_execute.set_start.assert_called_once()

            # Verify that simulation mode is set correctly
            assert self.script.comcam.simulation_mode

    async def test_cleanup(self):
        config = {
            "filter": "g",
            "exp_time": 30.0,
            "dofs": np.ones(50),
            "rotation_sequence": [10, 20, 30, 40, 50],
            "step_sequence": [0, 100, 200, 300, 400],
        }


        async with self.make_script():
            await self.configure_script(**config)

            # Simulate an error during the focus sweep to trigger cleanup
            self.script.iterations_started = True
            self.script.total_offset = 400  # Simulate some offset
            with mock.patch.object(
                self.script, "parameter_march", side_effect=Exception("Test exception")
            ):
                with pytest.raises(Exception):
                    await self.script.run_block()

            await self.script.cleanup()

            # Ensure the hexapod is returned to the original position
            offset_dof_data = self.tcs.rem.mtaos.cmd_offsetDOF.DataType()
            for i, dof_offset in enumerate(self.script.config.dofs * -self.script.total_offset):
                offset_dof_data.value[i] = dof_offset
            self.script.mtcs.rem.mtaos.cmd_offsetDOF.start.assert_any_call(
                self.script.total_offset
            )

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "parameter_march_comcam.py"
        await self.check_executable(script_path)
