import unittest
# from unittest.mock import Mock
import asyncio
import numpy as np

from lsst.ts import salobj

from lsst.ts.salscripts.scripts.auxtel import ATCamTakeImage

import SALPY_ATCamera

np.random.seed(47)

index_gen = salobj.index_generator()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        salobj.test_utils.set_random_lsst_dds_domain()

        self.script = ATCamTakeImage(index=self.index, descr='Test ATCamTakeImage')

        # Adds controller to Test
        self.at_cam = salobj.Controller(SALPY_ATCamera)

    async def cmd_take_images_callback(self, id_data):
        await asyncio.sleep((id_data.data.expTime +
                             self.script.read_out_time +
                             self.script.shutter_time*2.)*id_data.data.numImages)

        self.at_cam.evt_endReadout.put(self.at_cam.evt_endReadout.DataType())


class TestATCamTakeImage(unittest.TestCase):

    def test_script(self):
        async def doit():
            harness = Harness()
            exp_time = 5.
            exp_time_arr = np.random.uniform(0., 5., 3)

            # Adds callback to take image command
            harness.at_cam.cmd_takeImages.callback = harness.cmd_take_images_callback

            # test with exp_times as a float
            with self.subTest():
                harness.script.configure(exp_times=exp_time)

                await harness.script.run()

            with self.subTest():
                # test with exp_times as an array
                harness.script.configure(exp_times=exp_time_arr)

                await harness.script.run()

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == '__main__':
    unittest.main()
