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
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.take_whitelight_flats_lsstcam import (
    TakeWhiteLightFlatsLSSTCam,
)
from lsst.ts.observatory.control.maintel.mtcalsys import MTCalsys


class TestTakeWhiteLightFlatsLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.log = logging.getLogger(__name__)
        self.log.propagate = True

    async def basic_make_script(self, index):
        self.script = TakeWhiteLightFlatsLSSTCam(index=index)

        # await self.mock_mtcalsys()
        await self.mock_camera()

        return (self.script,)

    @property
    def remote_group(self) -> MTCalsys:
        """The remote_group property."""
        return self.mtcalsys

    async def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_focus = mock.AsyncMock(return_value=[1234])
        self.script.lsstcam.take_acq = mock.AsyncMock(return_value=([32, 0]))

    async def test_configure(self):

        config = {
            "sequence_name": "whitelight_r",
            "n_flat": 1,
            "use_camera": True,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.sequence_name == "whitelight_r"
            assert self.script.config.n_flat == 1
            assert self.script.config.use_camera

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "n_flat": -20,
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
            "n_flat": 1,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            assert self.script.get_instrument_name() == "LSSTCam"
            filt = self.script.get_instrument_filter()
            self.log.debug(f"Filter {filt}")
            assert self.script.get_instrument_filter() == "z"

    async def test_take_whitelight_source(self):
        config = {
            "sequence_name": "whitelight_r_source",
            "n_flat": 1,
            "use_camera": False,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # Setup correctly?
            assert not self.script.config_data["use_camera"]
            assert self.script.config_data["wavelength"] == 612.5

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = os.path.join(
            scripts_dir, "maintel", "take_whitelight_flats_lsstcam.py"
        )
        await self.check_executable(script_path)
