import unittest
import asyncio

import yaml

from lsst.ts import salobj

from lsst.ts.externalscripts.auxtel import ATCamTakeImage

import SALPY_ATCamera
import SALPY_Script

index_gen = salobj.index_generator()


class Harness:
    def __init__(self):
        self.index = next(index_gen)
        self.test_index = next(index_gen)
        salobj.test_utils.set_random_lsst_dds_domain()
        self.script = ATCamTakeImage(index=self.index)
        self.atcam = salobj.Controller(SALPY_ATCamera)

    async def cmd_take_images_callback(self, id_data):
        one_exp_time = id_data.data.expTime + self.script.readout_time + self.script_shutter_time
        await asyncio.sleep(one_exp_time*id_data.data.numImages)
        self.atcam.evt_endReadout.put()


class TestATCamTakeImage(unittest.TestCase):

    def test_script_exp_time_scalar(self):
        async def doit():
            harness = Harness()
            exp_time = 5
            harness.atcam.cmd_takeImages.callback = harness.cmd_take_images_callback

            config_kwargs = dict(exp_times=exp_time)
            config_data = SALPY_Script.Script_command_configureC()
            config_data.config = yaml.safe_dump(config_kwargs)
            await harness.script.do_configure(id_data=salobj.CommandIdData(cmd_id=1, data=config_data))
            await harness.script.do_run(id_data=salobj.CommandIdData(cmd_id=2, data=None))

        asyncio.get_event_loop().run_until_complete(doit())

    def test_script_exp_time_array(self):
        async def doit():
            harness = Harness()
            exp_time_arr = (0, 5, 3)
            config_kwargs = dict(exp_times=exp_time_arr)
            config_data = SALPY_Script.Script_command_configureC()
            config_data.config = yaml.safe_dump(config_kwargs)
            await harness.script.do_configure(id_data=salobj.CommandIdData(cmd_id=1, data=config_data))
            await harness.script.do_run(id_data=salobj.CommandIdData(cmd_id=2, data=None))

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == '__main__':
    unittest.main()
