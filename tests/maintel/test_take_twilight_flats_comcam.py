import unittest
import unittest.mock as mock
from collections import namedtuple

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.take_twilight_flats_comcam import (
    TakeTwilightFlatsComCam,
)


class TestTakeTwilightFlatsComCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakeTwilightFlatsComCam(index=index)

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
        self.script.mtcs.get_sun_azel = mock.Mock(return_value=(90.0, -3.0))
        Coordinates = namedtuple("Coordinates", ["ra", "dec"])
        self.script.mtcs.radec_from_azel = mock.Mock(
            return_value=Coordinates(ra=6, dec=20)
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.comcam = mock.AsyncMock()
        self.script.comcam.assert_liveliness = mock.AsyncMock()
        self.script.comcam.assert_all_enabled = mock.AsyncMock()
        self.script.comcam.take_imgtype = mock.AsyncMock(return_value=[1234])
        self.script.comcam.take_acq = mock.AsyncMock(return_value=([32, 0]))
        self.script.comcam.disable_checks_for_components = mock.Mock()

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

    async def test_configure_ignore(self):
        components = [
            "ccoods",  # ComCam component
            "mtdome",  # MTCS component
            "mtmount",  # Not allowed to ignore MTCS component
            "not_comp",  # Neither MTCS nor ComCam component
        ]
        config = {
            "filter": "r_03",
            "ignore": components,
        }

        async with self.make_script():
            await self.configure_script(**config)

            self.script.camera.disable_checks_for_components.assert_called_once_with(
                components=components
            )
            assert not self.script.mtcs.check.mtdome
            self.script.mtcs.check.mtmount.assert_not_called()
            self.script.mtcs.check.not_comp.assert_not_called()

    """
    #TODO: properly test this script
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
            assert self.script.comcam.take_acq.call_count == 16
    """

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_twilight_flats_comcam.py"
        await self.check_executable(script_path)
