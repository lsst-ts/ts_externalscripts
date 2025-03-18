import unittest
import unittest.mock as mock

import pytest
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.take_ptc_flats_comcam import TakePTCFlatsComCam


class TestTakePTCFlatsComCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TakePTCFlatsComCam(index=index)
        self.mock_camera()
        self.mock_electrometer()

        return (self.script,)

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.comcam = mock.AsyncMock()
        self.script.comcam.assert_liveliness = mock.AsyncMock()
        self.script.comcam.assert_all_enabled = mock.AsyncMock()
        self.script.comcam.take_imgtype = mock.AsyncMock(return_value=[1234])

    def mock_electrometer(self):
        """Mock electrometer instance and its methods."""
        self.script.electrometer = mock.AsyncMock()
        self.script.electrometer.cmd_setMode = mock.AsyncMock()
        self.script.electrometer.cmd_setRange = mock.AsyncMock()
        self.script.electrometer.cmd_setIntegrationTime = mock.AsyncMock()
        self.script.electrometer.cmd_performZeroCalib = mock.AsyncMock()
        self.script.electrometer.cmd_setDigitalFilter = mock.AsyncMock()
        self.script.electrometer.cmd_startScanDt = mock.AsyncMock()
        self.script.electrometer.evt_largeFileObjectAvailable = mock.AsyncMock()

    async def test_configure(self):
        electrometer_config = {
            "index": 201,
            "mode": "CURRENT",
            "range": -1,
            "integration_time": 0.1,
        }
        interleave_darks_config = {"dark_exp_times": 30, "n_darks": 2}

        config = {
            "filter": "r_03",
            "flats_exp_times": [7.25, 5.25, 0.75, 12.75],
            "electrometer_scan": electrometer_config,
            "interleave_darks": interleave_darks_config,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.flats_exp_times == [7.25, 5.25, 0.75, 12.75]
            assert self.script.config.electrometer_scan["index"] == 201
            assert self.script.config.electrometer_scan["mode"] == "CURRENT"
            assert self.script.config.electrometer_scan["range"] == -1
            assert self.script.config.electrometer_scan["integration_time"] == 0.1
            assert self.script.config.interleave_darks["n_darks"] == 2
            assert self.script.config.interleave_darks["dark_exp_times"] == [30, 30]

    async def test_invalid_electrometer_mode_config(self):
        bad_config = {
            "filter": "r_03",
            "flats_exp_times": [7.25, 7.25, 0.75, 0.75],
            "electrometer_scan": {
                "index": 201,
                "mode": "INVALID_MODE",
                "range": -1,
                "integration_time": 0.1,
            },
        }

        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(**bad_config)

    async def test_configure_ignore(self):
        config = {
            "flats_exp_times": [7.25, 5.25, 0.75, 12.75],
            "ignore": ["ccoods", "no_comp"],
        }

        async with self.make_script():
            await self.configure_script(**config)

            self.script.comcam.disable_checks_for_components.assert_called_once_with(
                components=config["ignore"]
            )

    async def test_take_ptc_flats(self):
        config = {
            "filter": "r_03",
            "flats_exp_times": [7.25, 0.75, 3.5],
            "electrometer_scan": {
                "index": 201,
                "mode": "CURRENT",
                "range": -1,
                "integration_time": 0.1,
            },
            "interleave_darks": {"dark_exp_times": 30, "n_darks": 2},
        }

        async with self.make_script():
            await self.configure_script(**config)
            await self.run_script()

            # 4 flats + 8 darks
            assert self.script.comcam.take_flats.call_count == 6
            assert self.script.comcam.take_darks.call_count == 12

            # Check if the electrometer scan was called
            assert self.script.electrometer.cmd_startScanDt.set_start.call_count == 6

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_ptc_flats_comcam.py"
        await self.check_executable(script_path)
