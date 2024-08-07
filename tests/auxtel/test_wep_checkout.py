import unittest
from unittest.mock import AsyncMock, patch

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel import WepCheckout


class TestWepCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        super().setUp()
        self.mock_run_wep = AsyncMock(
            return_value=(
                None,
                None,
                [
                    0.05816297,
                    0.03463353,
                    0.10047541,
                    -0.09588187,
                    0.138513,
                ],  # Mock few Zernike coefficients
            )
        )

    async def basic_make_script(self, index):
        # Patch 'run_wep' in the script setup
        with patch(
            "lsst.ts.externalscripts.auxtel.wep_checkout.run_wep", self.mock_run_wep
        ):
            self.script = WepCheckout(index=index)

        return (self.script,)

    async def test_run_successful(self):
        async with self.make_script():
            await self.run_script()
            # Assert that run_wep was called once
            self.mock_run_wep.assert_called_once()

    async def test_run_exception_handling(self):
        # Setup to simulate incorrect Zernike coefficients
        self.mock_run_wep.return_value = (
            None,
            None,
            [0.1, -0.2, 0.3, 0.4, 0.5],  # Incorrect Zernike coefficients
        )
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.run_script()
            # Ensure run_wep was called
            self.mock_run_wep.assert_called_once()

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "wep_checkout.py"
        await self.check_executable(script_path)
