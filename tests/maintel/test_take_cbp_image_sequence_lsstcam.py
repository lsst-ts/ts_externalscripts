import unittest
import unittest.mock as mock

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.take_cbp_image_sequence_lsstcam import (
    TakeCBPImageSequenceLSSTCam,
)


class TestTakeCBPImageSequenceLSSTCam(
    standardscripts.BaseScriptTestCase,
    unittest.IsolatedAsyncioTestCase,
):
    async def basic_make_script(self, index):
        self.script = TakeCBPImageSequenceLSSTCam(index=index)

        self.mock_mtcs()
        self.mock_camera()
        self.mock_mtcalsys()

        return (self.script,)

    def mock_mtcs(self):
        """Mock MTCS instances and its methods."""
        self.script.mtcs = mock.AsyncMock()
        self.script.mtcs.assert_liveliness = mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.offset_aos_lut = mock.AsyncMock()
        self.script.mtcs.get_sun_azel = mock.Mock(return_value=(90.0, -3.0))

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_imgtype = mock.AsyncMock(return_value=[1234])
        self.script.lsstcam.take_acq = mock.AsyncMock(return_value=([32, 0]))

    def mock_mtcalsys(self):
        """Mock camera instance and its methods."""
        self.script.mtcalsys = mock.AsyncMock()
        self.script.mtcalsys.assert_liveliness = mock.AsyncMock()
        self.script.mtcalsys.assert_all_enabled = mock.AsyncMock()
        self.script.mtcalsys.setup_laser = mock.AsyncMock()
        self.script.mtcalsys.laser_start_propagate = mock.AsyncMock()
        self.script.mtcalsys.change_laser_wavelength = mock.AsyncMock()
        self.script.mtcalsys.rem.tunablelaser.start_task = mock.AsyncMock()
        self.script.mtcalsys.rem.tunablelaser.cmd_triggerBurst.start = mock.AsyncMock()
        self.script.mtcalsys.rem.tunablelaser.cmd_setBurstMode.set_start = (
            mock.AsyncMock()
        )

    async def test_configure(self):

        config = {"nburst": 3, "cbp_elevation": 10}

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.nburst == 3
            assert self.script.config.cbp_elevation == 10

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_cbp_image_sequence_lsstcam.py"
        await self.check_executable(script_path)
