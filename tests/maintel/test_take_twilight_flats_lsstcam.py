import unittest
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.take_twilight_flats_lsstcam import (
    TakeTwilightFlatsLSSTCam,
)


class TestTakeTwilightFlatsLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeTwilightFlatsLSSTCam(index=index)

        self.mock_mtcs()
        self.mock_camera()
        self.mock_consdb()
        self.mock_vizier()

        return (self.script,)

    def mock_mtcs(self):
        """Mock MTCS instances and its methods."""
        self.script.mtcs = mock.AsyncMock()
        self.script.mtcs.assert_liveliness = mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.offset_aos_lut = mock.AsyncMock()
        self.script.mtcs.get_sun_azel = mock.AsyncMock(return_value=(-3.0, 90.0))

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_focus = mock.AsyncMock(return_value=[1234])
        self.script.lsstcam.take_acq = mock.AsyncMock(return_value=([32, 0]))

    def mock_consdb(self):
        """Mock consdb and its methods."""
        self.script.client = mock.Mock()
        self.script.client.wait_for_item_in_row = mock.Mock(return_value=15000)

    def mock_vizier(self):
        """Mock Vizier catalog"""
        self.script.vizier = mock.Mock()
        self.script.vizier.query_region = mock.Mock(return_value=[])

    async def test_configure(self):

        config = {
            "filter": "r_03",
            "n_flat": 15,
            "dither": 10,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.filter == "r_03"
            assert self.script.config.target_sky_counts == 15000
            assert self.script.config.n_flat == 15
            assert self.script.config.dither == 10
            assert self.script.config.max_exp_time == 30

    async def test_invalid_configuration(self):
        bad_configs = [
            {
                "n_flat": -20,
                "filter": "SDSSr_65mm",
            },
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    """
    async def test_take_twilight_flats(self):
        config = {
            "filter": "r_03",
            "n_flat": 15,
            "dither": 10,
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # 16 flats
            assert self.script.lsstcam.take_acq.call_count == 16
    """

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_twilight_flats_lsstcam.py"
        await self.check_executable(script_path)
