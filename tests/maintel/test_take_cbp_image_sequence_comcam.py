import unittest
import unittest.mock as mock

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.take_cbp_image_sequence_comcam import (
    TakeCBPImageSequenceComCam,
)


class TestTakeCBPImageSequenceComCam(
    standardscripts.BaseScriptTestCase,
    unittest.IsolatedAsyncioTestCase,
):
    async def basic_make_script(self, index):
        self.script = TakeCBPImageSequenceComCam(index=index)

        self.mock_mtcs()
        self.mock_camera()

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
        self.script.comcam = mock.AsyncMock()
        self.script.comcam.assert_liveliness = mock.AsyncMock()
        self.script.comcam.assert_all_enabled = mock.AsyncMock()
        self.script.comcam.take_imgtype = mock.AsyncMock(return_value=[1234])
        self.script.comcam.take_acq = mock.AsyncMock(return_value=([32, 0]))

    async def test_configure(self):

        config = {"nburst": 3, "cbp_elevation": 10}

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.nburst == 3
            assert self.script.config.cbp_elevation == 10

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_cbp_image_sequence_comcam.py"
        await self.check_executable(script_path)
