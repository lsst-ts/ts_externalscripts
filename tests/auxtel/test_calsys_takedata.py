import logging
import unittest

import asynctest
import numpy as np
import yaml

from lsst.ts import salobj
from lsst.ts.externalscripts.auxtel import CalSysTakeData

np.random.seed(71)

index_gen = salobj.index_generator()

logging.basicConfig()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        self.script = CalSysTakeData(index=self.index)


class TestCalSysTakeData(asynctest.TestCase):
    def setUp(self):
        salobj.test_utils.set_random_lsst_dds_domain()

    async def test_configure(self):
        index = next(index_gen)

        async with CalSysTakeData(index=index) as script:
            async def run_configure(**kwargs):
                script.set_state(salobj.Script.ScriptState.UNCONFIGURED)
                config_data = script.cmd_configure.DataType()
                if kwargs:
                    config_data.config = yaml.safe_dump(kwargs)
                await script.do_configure(config_data)


if __name__ == "__main__":
    unittest.main()
