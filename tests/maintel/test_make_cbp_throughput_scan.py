import unittest

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.make_cbp_throughput_scan import (
    MakeCBPThroughputScan,
)


class TestMakeCBPThroughputScan(
    standardscripts.BaseScriptTestCase,
    unittest.IsolatedAsyncioTestCase,
):
    async def basic_make_script(self, index):
        self.script = MakeCBPThroughputScan(index=index)

        return (self.script,)

    async def test_configure(self):

        config = {"nburst": 3, "cbp_elevation": 10}

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.nburst == 3
            assert self.script.config.cbp_elevation == 10

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "make_cbp_throughput_scan.py"
        await self.check_executable(script_path)
