import asyncio
import logging
import unittest

import numpy as np
import yaml

from lsst.ts import salobj
from lsst.ts.externalscripts.auxtel import CalSysTakeNarrowbandData

np.random.seed(84)

index_gen = salobj.index_generator()

logging.basicConfig()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        self.script = CalSysTakeNarrowbandData(index=self.index)


class TestCalSysTakeNarrowbandData(unittest.TestCase):
    def setUp(self):
        salobj.test_utils.set_random_lsst_dds_domain()

    def test_configure(self):
        index = next(index_gen)

        async def doit():
            script = CalSysTakeNarrowbandData(index=index)
            try:
                async def run_configure(**kwargs):
                    script.set_state(salobj.Script.ScriptState.UNCONFIGURED)
                    config_data = script.cmd_configure.DataType()
                    if kwargs:
                        config_data.config = yaml.safe_dump(kwargs)
                    await script.do_configure(config_data)
            finally:
                await script.close()

        asyncio.get_event_loop().run_until_complete(doit())
