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


import logging
import os
import unittest
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts, utils
from lsst.ts.externalscripts.maintel.take_whitelight_flats_lsstcam import (
    TakeWhiteLightFlatsLSSTCam,
)


class TestTakeWhiteLightFlatsLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.script = TakeWhiteLightFlatsLSSTCam(index=index)

        self.mock_mtcalsys()
        self.mock_camera()

        return (self.script,)

    def mock_mtcalsys(self):
        """Mock MTCalsys instance"""
        self.script.mtcalsys = unittest.mock.AsyncMock()
        self.script.mtcalsys.start_task = utils.make_done_future()
        self.script.mtcalsys.load_calibration_config_file = unittest.mock.AsyncMock()
        self.script.mtcalsys.assert_valid_configuration_option = (
            unittest.mock.AsyncMock()
        )
        self.script.mtcalsys.run_calibration_sequence = unittest.mock.AsyncMock(
            side_effect=[
                {"sequence_id": 1, "duration": 10},
                {"sequence_id": 2, "duration": 12},
            ]
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()

    async def test_configure(self):
        config = {
            "sequence_name": "whitelight_r",
            "n_iterations": 1,
            "use_camera": True,
        }

        async with self.make_script():
            self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
                return_value={
                    "mtcamera_filter": "r_57",
                    "exposure_times": [15.0],
                    "calib_type": "WhiteLight",
                }
            )
            await self.configure_script(**config)

            assert self.script.sequence_name == "whitelight_r"
            assert self.script.n_iterations == 1
            assert self.script.use_camera

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "n_iterations": -20,
                "filter": "whitelight_led",
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_take_whitelight_flats(self):
        config = {
            "sequence_name": "whitelight_z",
            "n_iterations": 1,
        }

        async with self.make_script():
            self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
                return_value={
                    "mtcamera_filter": "z_20",
                    "exposure_times": [15.0],
                    "calib_type": "WhiteLight",
                }
            )
            await self.configure_script(**config)
            await self.run_script()
            assert self.script.get_instrument_filter() == "z_20"

    async def test_take_whitelight_source(self):
        config = {
            "sequence_name": "whitelight_r_source",
            "n_iterations": 1,
            "use_camera": False,
        }

        async with self.make_script():
            self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
                return_value={
                    "mtcamera_filter": "r_57",
                    "wavelength": 612.5,
                    "exposure_times": [5.0, 5.0],
                    "calib_type": "WhiteLight",
                }
            )

            await self.configure_script(**config)
            await self.run_script()

            assert not self.script.use_camera
            assert self.script.config_data["wavelength"] == 612.5

    async def test_take_multiple_iterations(self):
        config = {
            "sequence_name": "whitelight_r_source",
            "n_iterations": 2,
        }

        async with self.make_script():
            self.script.mtcalsys.get_calibration_configuration = unittest.mock.Mock(
                return_value={
                    "mtcamera_filter": "r_57",
                    "wavelength": 612.5,
                    "exposure_times": [5.0],
                    "calib_type": "WhiteLight",
                }
            )
            await self.configure_script(**config)
            await self.run_script()

            assert self.script.mtcalsys.run_calibration_sequence.await_count == 2

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "take_whitelight_flats_lsstcam.py"
        )
        await self.check_executable(script_path)
