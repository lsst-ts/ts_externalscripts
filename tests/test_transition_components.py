import unittest
from unittest.mock import Mock
import asyncio
import numpy as np

from lsst.ts import salobj

from lsst.ts.salscripts.scripts import TransitionComponents

import SALPY_Test

np.random.seed(47)

index_gen = salobj.index_generator()


class Harness:
    def __init__(self):
        self.index = next(index_gen)

        self.test_index = next(index_gen)

        salobj.test_utils.set_random_lsst_dds_domain()

        self.script = TransitionComponents(index=self.index, descr='Test TransitionComponents')

        # Adds controller to Test
        self.test_controller = salobj.Controller(SALPY_Test, self.test_index)


class TestTransitionComponents(unittest.TestCase):

    def test_transition_components(self):

        async def doit():
            harness = Harness()

            component = [('Test', harness.test_index)]
            invalid_transition_to = ['FOO']
            valid_transition_up = ['start', 'enable']
            valid_transition_down = ['disable', 'standby']

            # Check that configuration fails with TypeError if no parameters sent
            with self.assertRaises(TypeError):
                harness.script.configure()

            # Check that configuration fails with IOError with empty set
            with self.assertRaises(IOError):
                harness.script.configure(components=[], transition_to=[])

            # Check that configuration fails with IOError with empty set
            with self.assertRaises(IOError):
                harness.script.configure(components=[], transition_to=[])

            with self.assertRaises(IOError):
                harness.script.configure(components=component, transition_to=[])

            with self.assertRaises(IOError):
                harness.script.configure(components=component, transition_to=invalid_transition_to)

            # This shall work
            harness.script.configure(components=component, transition_to=valid_transition_up)

            def callback(data):
                pass

            # adds callback to Test state transitions
            harness.test_controller.cmd_start.callback = Mock(wraps=callback)
            harness.test_controller.cmd_enable.callback = Mock(wraps=callback)
            harness.test_controller.cmd_disable.callback = Mock(wraps=callback)
            harness.test_controller.cmd_standby.callback = Mock(wraps=callback)

            await harness.script.run()

            harness.script.configure(components=component, transition_to=valid_transition_down)

            await harness.script.run()

            harness.test_controller.cmd_start.callback.assert_called()
            harness.test_controller.cmd_enable.callback.assert_called()
            harness.test_controller.cmd_disable.callback.assert_called()
            harness.test_controller.cmd_standby.callback.assert_called()

        asyncio.get_event_loop().run_until_complete(doit())


if __name__ == '__main__':
    unittest.main()
