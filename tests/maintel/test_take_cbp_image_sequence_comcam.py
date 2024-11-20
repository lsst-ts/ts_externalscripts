import unittest

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

        return (self.script,)

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
