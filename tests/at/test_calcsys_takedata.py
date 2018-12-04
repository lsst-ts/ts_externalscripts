import unittest
from unittest.mock import Mock
import asyncio
import numpy as np

from lsst.ts import salobj

from lsst.ts.salscripts.scripts.auxtel import ATCalSysTakeData

import SALPY_Electrometer
import SALPY_ATMonochromator
import SALPY_FiberSpectrograph

np.random.seed(47)

index_gen = salobj.index_generator()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        salobj.test_utils.set_random_lsst_dds_domain()

        self.script = ATCalSysTakeData(index=self.index, descr='Test TakeImageStressTest')

        # Adds controller to Test
        self.electrometer_controller = salobj.Controller(SALPY_Electrometer, 1)
        self.monochromator_controller = salobj.Controller(SALPY_ATMonochromator)
        self.fiberspec_controller = salobj.Controller(SALPY_FiberSpectrograph)

    async def start_scan_dt_callback(self, id_data):
        await asyncio.sleep(1.)
        topic = self.electrometer_controller.evt_detailedState.DataType()
        self.electrometer_controller.evt_detailedState.put(topic)
        await asyncio.sleep(id_data.data.scanDuration)

    async def capture_spect_image_callback(self, id_data):
        await asyncio.sleep(id_data.data.integrationTime)


class TestATCalSysTakeData(unittest.TestCase):

    def test_script(self):
        async def doit():
            harness = Harness()
            wavelength = 600.
            integration_time = 10.

            # Check that configuration fails with TypeError if no parameters sent
            with self.assertRaises(TypeError):
                harness.script.configure()

            harness.script.configure(wavelength=wavelength,
                                     integrationTime=integration_time)

            def callback(data):
                pass

            mono_cmd = harness.monochromator_controller.cmd_updateMonochromatorSetup
            mono_cmd.callback = Mock(wraps=callback)

            el_scan_dt_attr = harness.electrometer_controller.cmd_startScanDt
            el_scan_dt_attr.callback = harness.start_scan_dt_callback

            fs_capture_attr = harness.fiberspec_controller.cmd_captureSpectImage
            fs_capture_attr.callback = harness.capture_spect_image_callback

            await harness.script.run()

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == '__main__':
    unittest.main()
