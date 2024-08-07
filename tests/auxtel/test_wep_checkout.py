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

import unittest
from unittest.mock import AsyncMock, patch

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel import WepCheckout


class TestWepCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):

    async def basic_make_script(self, index):

        self.script = WepCheckout(index=index)

        with patch(
            "lsst.ts.externalscripts.auxtel.wep_checkout.run_wep",
            new_callable=AsyncMock,
        ) as mock_run_wep:
            mock_run_wep.return_value = (
                None,
                None,
                {"outputZernikesAvg": [58.163, 34.633, 100.47, -95.882, 138.513]},
            )
            self.script.run_wep = mock_run_wep

        return (self.script,)

    async def test_run_successful(self):
        async with self.make_script():
            await self.configure_script()
            await self.run_script()
            # Assert that run_wep was called once
            self.script.run_wep.assert_called_once()

    async def test_run_exception_handling(self):
        # Setup to simulate incorrect Zernike coefficients
        self.run_wep.return_value = (
            None,
            None,
            {
                "outputZernikesAvg": [0.1, 0.2, 0.3, 0.4, 0.5]
            },  # Incorrect Zernike coefficients
        )
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script()
                await self.run_script()
            # Ensure run_wep was called
            self.script.run_wep.assert_called_once()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "wep_checkout.py"
        await self.check_executable(script_path)
