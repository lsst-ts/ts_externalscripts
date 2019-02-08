from lsst.ts.salscripts.bobhoskins.script import BobHoskins
from lsst.ts.salobj import index_generator, Controller
from lsst.ts.salobj.test_utils import set_random_lsst_dds_domain
import SALPY_LinearStage
import SALPY_TunableLaser
import SALPY_Electrometer

import pytest
from types import SimpleNamespace


class TestBobHoskins:
    @pytest.fixture(scope="class")
    def bh(self):
        set_random_lsst_dds_domain()
        bh = SimpleNamespace()
        bh.script = BobHoskins(index=next(index_generator()))
        bh.linear_stage_1_controller = Controller(SALPY_LinearStage, 1)
        bh.linear_stage_2_controller = Controller(SALPY_LinearStage, 2)
        bh.electrometer_controller = Controller(SALPY_Electrometer, 1)
        bh.tunable_laser_controller = Controller(SALPY_TunableLaser)
        return bh

    def test_configure(self, bh):
        bh.script.configure(wanted_remotes=[
            'linear_stage_1_remote',
            'linear_stage_2_remote',
            'electrometer_remote',
            'tunable_laser_remote'],
            wavelengths=[550, 575],
            steps=5)
        assert bh.script.wanted_remotes == [
            'linear_stage_1_remote',
            'linear_stage_2_remote',
            'electrometer_remote',
            'tunable_laser_remote']
        assert bh.script.wavelengths == range(550, 575)
        assert bh.script.steps == 5
        assert bh.script.linear_stage_set is True
        assert bh.script.linear_stage_2_set is True
        assert bh.script.electrometer_set is True
        assert bh.script.tunable_laser_set is True

    def test_set_metadata(self, bh):
        pass

    def test_run(self, bh):
        pass
