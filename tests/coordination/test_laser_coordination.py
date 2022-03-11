# This file is part of ts_externalscripts
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License

import logging
import unittest

import numpy as np
import yaml

from lsst.ts import salobj
from lsst.ts import utils
from lsst.ts.externalscripts.coordination.laser_coordination import LaserCoordination

np.random.seed(71)

index_gen = utils.index_generator()

logging.basicConfig()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        self.script = LaserCoordination(index=self.index)


class TestLaserCoordination(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        salobj.set_random_lsst_dds_partition_prefix()

    async def test_configure(self):
        index = next(index_gen)

        async with LaserCoordination(index=index) as script:

            async def run_configure(**kwargs):
                await script.set_state(salobj.Script.ScriptState.UNCONFIGURED)
                config_data = script.cmd_configure.DataType()
                if kwargs:
                    config_data.config = yaml.safe_dump(kwargs)
                await script.do_configure(config_data)
