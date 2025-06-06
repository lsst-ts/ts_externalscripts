# This file is part of ts_standardscripts
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import contextlib
import logging
import os
import tempfile
import unittest

import lsst.daf.butler as dafButler
import pytest
from lsst.ts import salobj
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.auxtel import LatissAcquire
from lsst.ts.observatory.control.auxtel import ATCS, LATISS, ATCSUsages, LATISSUsages
from lsst.ts.standardscripts import BaseScriptTestCase
from lsst.ts.xml.enums.Script import ScriptState
from lsst.utils import getPackageDir

logger = logging.getLogger(__name__)
logger.propagate = True

# Declare the local path that has the information to build a
# local gen3 butler database

DATAPATH = "/repo/LATISS"  # summit and TTS
try:
    butler = dafButler.Butler(
        DATAPATH, instrument="LATISS", collections="LATISS/raw/all"
    )
    DATA_AVAILABLE = True

except FileNotFoundError:
    logger.warning("Data unavailable, certain tests will be skipped")
    DATA_AVAILABLE = False

    DATAPATH = (tempfile.TemporaryDirectory(prefix="butler-repo")).name
    butler_config_path = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
        "butler_seed.yaml",
    )
    dafButler.Butler(
        dafButler.Butler.makeRepo(DATAPATH, config=butler_config_path), writeable=True
    )

except PermissionError:
    logger.warning(
        "Data unavailable due to permissions (at a minimum),"
        " certain tests will be skipped"
    )
    DATA_AVAILABLE = False
    DATAPATH = (tempfile.TemporaryDirectory(prefix="butler-repo")).name
    butler_config_path = os.path.join(
        getPackageDir("ts_externalscripts"),
        "tests",
        "data",
        "auxtel",
        "butler_seed.yaml",
    )
    dafButler.Butler(
        dafButler.Butler.makeRepo(DATAPATH, config=butler_config_path), writeable=True
    )


class TestLatissAcquire(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.remotes_needed = True

    async def basic_make_script(self, index):
        self.script = LatissAcquire(index=index, add_remotes=self.remotes_needed)
        self.script.atcs = ATCS(
            domain=self.script.domain,
            intended_usage=ATCSUsages.DryTest,
            log=self.script.log,
        )
        self.script.latiss = LATISS(
            domain=self.script.domain,
            intended_usage=LATISSUsages.DryTest,
            log=self.script.log,
        )

        # Mock the method that returns the BestEffortIsr class if it is
        # not available for import
        self.script.get_best_effort_isr = unittest.mock.Mock()

        return (self.script,)

    async def setup_mocks_arun(self):
        self.script.execute_acquisition = unittest.mock.AsyncMock()
        self.script.atcs.slew_object = unittest.mock.AsyncMock()
        self.script.atcs.slew_icrs = unittest.mock.AsyncMock()
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock()
        self.script.latiss.get_setup = unittest.mock.AsyncMock()
        self.script.latiss.take_acq = unittest.mock.AsyncMock()

    async def setup_execute_acquisition_mocks(self):
        self.script.latiss.rem.atoods = unittest.mock.AsyncMock()
        self.script.latiss.rem.atoods.evt_imageInOODS.attach_mock(
            unittest.mock.Mock(),
            "flush",
        )
        self.script.latiss.take_acq = unittest.mock.AsyncMock()
        self.script.get_next_image_data_id = unittest.mock.AsyncMock(
            return_value=self.acq_image_id
        )
        self.script.find_offset = unittest.mock.AsyncMock(
            return_value=self.find_offset_return_value
        )
        self.script.atcs.offset_xy = unittest.mock.AsyncMock()

    async def test_executable(self):
        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_acquire.py"
        await self.check_executable(script_path)

    async def test_valid_configurations(self):
        # Set of valid configurations to test, considering different possible
        # combinations of configuration parameters
        configs_good = [
            dict(object_name="HR8799", program="test_program", reason="test_reason"),
            dict(
                object_name="HR8799",
                object_ra="23 07 28.71",
                object_dec="+21 08 03.31",
                program="test_program",
                reason="test_reason",
            ),
            dict(
                object_name="HR8799",
                program="test_program",
                reason="test_reason",
                rot_value=90,
                rot_type="PhysicalSky",
            ),
            dict(
                object_name="HR8799",
                program="test_program",
                reason="test_reason",
                time_on_target=300,
            ),
            dict(
                object_name="HR8799",
                program="test_program",
                reason="test_reason",
                do_user_final_position=True,
                user_final_x=1700,
                user_final_y=100,
            ),
            dict(do_reacquire=True, program="test_program", reason="test_reason"),
        ]

        self.remotes_needed = False
        async with self.make_script():
            for config in configs_good:
                await self.configure_script(**config)

                default_values = dict(
                    acq_filter=self.script.acq_filter,
                    acq_grating=self.script.acq_grating,
                    acq_exposure_time=self.script.acq_exposure_time,
                    max_acq_iter=self.script.max_acq_iter,
                    target_pointing_tolerance=self.script.target_pointing_tolerance,
                    target_pointing_verification=self.script.target_pointing_verification,
                    rot_value=self.script.rot_value,
                    rot_type=self.script.rot_type,
                    time_on_target=self.script.time_on_target,
                    estimated_slew_time=self.script.estimated_slew_time,
                    do_user_final_position=self.script.do_user_final_position,
                    do_reacquire=self.script.do_reacquire,
                    user_final_x=self.script.user_final_x,
                    user_final_y=self.script.user_final_y,
                    reason=self.script.reason,
                    program=self.script.program,
                )

                self.assert_config(default_values, config)

    async def test_invalid_configurations(self):
        # Set of invalid configurations to test, these should fail to configure
        configs_bad = [
            dict(),
            dict(
                object_ra="23 07 28.71",
                object_dec="+21 08 03.31",
                program="test_program",
                reason="test_reason",
            ),
            dict(
                object_name="HR8799",
                do_manual_focus_position=[0],
                program="test_program",
                reason="test_reason",
            ),
            dict(
                object_name="HR8799",
                rot_type="SkyPhysical",
                program="test_program",
                reason="test_reason",
            ),
            dict(
                object_name="HR8799",
                program="test_program",
                reason="test_reason",
                do_user_final_position=True,
            ),
            dict(
                object_name="HR8799",
                program="test_program",
                reason="test_reason",
                do_user_final_position=True,
                user_final_x=1500,
            ),
        ]

        self.remotes_needed = False
        async with self.make_script():
            for config in configs_bad:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**config)

                    assert self.state.state == ScriptState.CONFIGURE_FAILED

    async def test_arun(self):
        async with self.make_configured_dry_script():
            await self.setup_mocks_arun()

            await self.script.arun()

            self.script.atcs.slew_object.assert_awaited_once()
            self.script.execute_acquisition.assert_awaited_once()
            self.script.latiss.setup_atspec.assert_awaited_once()
            self.script.latiss.take_acq.assert_awaited_once()

    async def test_arun_reacquire(self):
        async with self.make_configured_dry_script(do_reacquire=True):
            await self.setup_mocks_arun()

            await self.script.arun()

            self.script.atcs.slew_object.assert_not_awaited()
            self.script.execute_acquisition.assert_awaited_once()
            self.script.latiss.setup_atspec.assert_awaited_once()
            self.script.latiss.take_acq.assert_awaited_once()

    async def test_execute_acquisition(self):
        async with self.make_configured_dry_script():
            self.acq_image_id = dict(seq_num=123, day_obs=20000101)
            self.find_offset_return_value = (1.0, 1.0)

            await self.setup_execute_acquisition_mocks()

            await self.script.execute_acquisition(
                self.script.target_position_x, self.script.target_position_y
            )

            self.assert_execute_acquisition()

    async def test_execute_acquisition_fail_on_max_iters(self):
        async with self.make_configured_dry_script():
            self.acq_image_id = dict(seq_num=123, day_obs=20000101)
            self.find_offset_return_value = (10.0, 10.0)

            await self.setup_execute_acquisition_mocks()

            with pytest.raises(RuntimeError):
                await self.script.execute_acquisition(
                    self.script.target_position_x, self.script.target_position_y
                )

            self.assert_execute_acquisition_fail_on_max_iters()

    def assert_config(self, default_values, config):
        configured_values = dict(
            object_name=self.script.object_name,
            object_ra=self.script.object_ra,
            object_dec=self.script.object_dec,
            acq_filter=self.script.acq_filter,
            acq_grating=self.script.acq_grating,
            acq_exposure_time=self.script.acq_exposure_time,
            max_acq_iter=self.script.max_acq_iter,
            target_pointing_tolerance=self.script.target_pointing_tolerance,
            target_pointing_verification=self.script.target_pointing_verification,
            rot_value=self.script.rot_value,
            rot_type=self.script.rot_type,
            time_on_target=self.script.time_on_target,
            estimated_slew_time=self.script.estimated_slew_time,
            do_user_final_position=self.script.do_user_final_position,
            user_final_x=self.script.user_final_x,
            user_final_y=self.script.user_final_y,
            do_reacquire=self.script.do_reacquire,
            reason=self.script.reason,
            program=self.script.program,
        )

        for parameter in default_values:
            with self.subTest(config=config, parameter=parameter):
                assert (
                    config.get(parameter, default_values.get(parameter))
                    == configured_values[parameter]
                )

    def assert_execute_acquisition(self):
        self.script.latiss.rem.atoods.evt_imageInOODS.flush.assert_called_once()

        take_acq_calls = [
            unittest.mock.call(
                exptime=2,
                n=1,
                group_id=self.script.group_id,
                reason=self.script.reason,
                program=self.script.program,
            ),
        ]

        self.script.get_next_image_data_id.assert_awaited_once()
        self.script.latiss.take_acq.assert_has_awaits(take_acq_calls)
        self.script.find_offset.assert_awaited_once_with(
            self.acq_image_id,
            self.script.target_position_x,
            self.script.target_position_y,
        )

    def assert_execute_acquisition_fail_on_max_iters(self):
        mocks_list = [
            self.script.latiss.rem.atoods.evt_imageInOODS.flush,
            self.script.get_next_image_data_id,
            self.script.latiss.take_acq,
            self.script.find_offset,
            self.script.atcs.offset_xy,
        ]

        for mock in mocks_list:
            assert mock.call_count == self.script.max_acq_iter

    async def set_test_configuration(self, **kwargs):
        test_configuration = self._generate_configuration(**kwargs)

        await self.configure_script(**test_configuration)

        return test_configuration

    def _generate_configuration(self, **kwargs):
        """Generate configuration.

        Parameters
        ----------
        None

        Returns
        -------
        configuration : `dict`
            Script configuration.
        """
        configuration = dict(
            object_name="HR8799", program="test_program", reason="test_reason"
        )
        configuration.update(**kwargs)

        return configuration

    @contextlib.asynccontextmanager
    async def make_configured_dry_script(self, **kwargs):
        """Construct script without remotes.

        This is useful for developing fast unit tests for methods that do not
        require DDS communication or when mocking the remote's behavior.
        """
        self.remotes_needed = False
        async with self.make_script():
            test_configuration = await self.set_test_configuration(**kwargs)

            self.script.atcs.rem.ataos = unittest.mock.AsyncMock()
            self.script.atcs.rem.atptg = unittest.mock.AsyncMock()
            self.script.latiss.rem.atspectrograph = unittest.mock.AsyncMock()

            yield test_configuration
