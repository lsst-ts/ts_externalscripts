import unittest
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel.take_twilight_flats_latiss import (
    TakeTwilightFlatsLatiss,
)


class TestTakeTwilightFlatsLatiss(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeTwilightFlatsLatiss(index=index)

        self.mock_atcs()
        self.mock_camera()

        return (self.script,)

    def mock_atcs(self):
        """Mock ATCS instances and its methods."""
        self.script.atcs = mock.AsyncMock()
        self.script.atcs.assert_liveliness = mock.AsyncMock()
        self.script.atcs.assert_all_enabled = mock.AsyncMock()
        self.script.atcs.offset_aos_lut = mock.AsyncMock()

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.latiss = mock.AsyncMock()
        self.script.latiss.assert_liveliness = mock.AsyncMock()
        self.script.latiss.assert_all_enabled = mock.AsyncMock()
        self.script.latiss.take_focus = mock.AsyncMock(return_value=[1234])

    async def test_configure(self):

        config = {
            "filter": "SDSSr_65mm",
            "n_flat": 15,
            "dither": 10,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.filter == "SDSSr_65mm"
            assert self.script.config.grating == "null"
            assert self.script.config.linear_stage == "null"
            assert self.script.config.target_sky_counts == 15000
            assert self.script.config.n_flat == 15
            assert self.script.config.dither == 10
            assert self.script.config.max_exp_time == 300

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "n_flat": -20,
                "filter": "SDSSr_65mm",
                "grating": "blue300lpmm_qn1",
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_take_twilight_flats(self):
        config = {
            "filter": "SDSSr_65mm",
            "n_flat": 15,
            "dither": 10,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # 16 flats
            assert self.script.latiss.take_twilight_flats.call_count == 16

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "take_twilight_flats_latiss.py"
        await self.check_executable(script_path)
