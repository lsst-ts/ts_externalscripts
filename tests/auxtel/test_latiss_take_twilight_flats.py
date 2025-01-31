import os
import unittest
import unittest.mock as mock
import warnings

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel.latiss_take_twilight_flats import (
    TakeTwilightFlatsLatiss,
)

try:
    from lsst.summit.utils import BestEffortIsr

    BEST_ISR_AVAILABLE = True
except ImportError:
    warnings.warn("Cannot import required libraries. Script will not work.")
    BEST_ISR_AVAILABLE = False


class TestTakeTwilightFlatsLatiss(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeTwilightFlatsLatiss(index=index)

        self.mock_atcs()
        self.mock_camera()
        self.mock_consdb()
        self.mock_vizier()

        return (self.script,)

    def mock_atcs(self):
        """Mock ATCS instances and its methods."""
        self.script.atcs = mock.AsyncMock()
        self.script.atcs.assert_liveliness = mock.AsyncMock()
        self.script.atcs.assert_all_enabled = mock.AsyncMock()
        self.script.atcs.offset_aos_lut = mock.AsyncMock()
        self.script.atcs.get_sun_azel = mock.Mock(return_value=(90, -3.0))
        self.script.atcs.radec_from_azel = mock.Mock(return_value={"ra": 6, "dec": 20})

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.latiss = mock.AsyncMock()
        self.script.latiss.assert_liveliness = mock.AsyncMock()
        self.script.latiss.assert_all_enabled = mock.AsyncMock()
        self.script.latiss.take_focus = mock.AsyncMock(return_value=[1234])
        self.script.latiss.take_acq = mock.AsyncMock(return_value=([32, 0]))

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
            "filter": "SDSSr_65mm",
            "n_flat": 15,
            "dither": 10.0,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.filter == "SDSSr_65mm"
            assert self.script.config.grating == "empty_1"
            assert self.script.config.target_sky_counts == 15000
            assert self.script.config.n_flat == 15
            assert self.script.config.dither == 10.0
            assert self.script.config.max_exp_time == 30

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

    @unittest.skipIf(
        BEST_ISR_AVAILABLE is False,
        f"Best_Effort_ISR is {BEST_ISR_AVAILABLE}."
        f"Skipping test_take_twilight_flats.",
    )
    async def test_take_twilight_flats(self):
        config = {
            "filter": "SDSSr_65mm",
            "n_flat": 15,
            "dither": 10,
        }

        # First make sure the best effort package is present
        assert os.path.exists(BestEffortIsr.__file__)

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # 16 flats
            assert self.script.latiss.take_acq.call_count == 16

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_take_twilight_flats.py"
        await self.check_executable(script_path)
