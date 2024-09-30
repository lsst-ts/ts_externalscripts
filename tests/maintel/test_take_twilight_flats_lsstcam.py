import unittest
import unittest.mock as mock
import warnings

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.take_twilight_flats_lsstcam import (
    TakeTwilightFlatsLSSTCam,
)

try:
    from lsst.summit.utils import ConsDbClient

    CONSDB_AVAILABLE = True
except ImportError:
    CONSDB_AVAILABLE = False
    warnings.warn("Cannot import summit utils. Most tests will be skipped.")


class TestTakeTwilightFlatsLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeTwilightFlatsLSSTCam(index=index)

        self.mock_atcs()
        self.mock_camera()

        return (self.script,)

    def mock_mtcs(self):
        """Mock ATCS instances and its methods."""
        self.script.atcs = mock.AsyncMock()
        self.script.atcs.assert_liveliness = mock.AsyncMock()
        self.script.atcs.assert_all_enabled = mock.AsyncMock()
        self.script.atcs.offset_aos_lut = mock.AsyncMock()

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_focus = mock.AsyncMock(return_value=[1234])

    @unittest.skipIf(
        CONSDB_AVAILABLE is False,
        f"ConsDB package availibility is {CONSDB_AVAILABLE}. Skipping test_consdb.",
    )
    async def test_consdb(self):

        self.client = ConsDbClient()

    @unittest.skipIf(
        CONSDB_AVAILABLE is False,
        f"ConsDB package availibility is {CONSDB_AVAILABLE}. Skipping test_configure.",
    )
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
            assert self.script.config.max_exp_time == 300

    @unittest.skipIf(
        CONSDB_AVAILABLE is False,
        f"ConsDB package availibility is {CONSDB_AVAILABLE}. Skipping test_invalid_configuration.",
    )
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

    @unittest.skipIf(
        CONSDB_AVAILABLE is False,
        f"ConsDB package availibility is {CONSDB_AVAILABLE}. Skipping test_take_twilight_flats.",
    )
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
            assert self.scripts.lsstcam.take_twilight_flats.call_count == 16

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_twilight_flats_lsstcam.py"
        await self.check_executable(script_path)
