import unittest

from lsst.ts import externalscripts, standardscripts


class TestMakeCBPThroughputScan(
    standardscripts.BaseScriptTestCase,
    unittest.IsolatedAsyncioTestCase,
):
    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "make_cbp_throughput_scan.py"
        await self.check_executable(script_path)
