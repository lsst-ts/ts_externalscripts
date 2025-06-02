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

import contextlib
import unittest

import pytest
from lsst.ts import salobj
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.maintel import OffsetAndTakeImagesLSSTCam
from lsst.ts.idl.enums.Script import ScriptState
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages
from lsst.ts.standardscripts import BaseScriptTestCase


class TestOffsetAndTakeImagesLSSTCam(
    BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = OffsetAndTakeImagesLSSTCam(index=index)

        return (self.script,)

    @contextlib.asynccontextmanager
    async def make_dry_script(self):
        async with self.make_script():
            self.script.mtcs = MTCS(
                domain=self.script.domain,
                intended_usage=MTCSUsages.DryTest,
                log=self.script.log,
            )

            self.script.lsstcam = LSSTCam(
                domain=self.script.domain,
                intended_usage=LSSTCamUsages.DryTest,
                log=self.script.log,
            )

            self.script.mtcs.reset_offsets = unittest.mock.AsyncMock()
            self.script.mtcs.offset_azel = unittest.mock.AsyncMock()
            self.script.mtcs.offset_xy = unittest.mock.AsyncMock()
            self.script.mtcs.offset_rot = unittest.mock.AsyncMock()
            self.script.lsstcam.take_imgtype = unittest.mock.AsyncMock()
            yield

    async def test_valid_configurations(self):
        # Set of valid configurations to test, considering different possible
        # combinations of configuration parameters
        configs_good = [
            dict(
                offset_azel=dict(az=[180, 100], el=[60, 50]),
                exp_times=[1, 1, 1],
                program="Test_program",
            ),
            dict(
                offset_azel=dict(az=[180, 100], el=[60, 50]),
                exp_times=[1, 1, 1],
                program="Test_program",
                relative=False,
                image_type="OBJECT",
                reason="test_reason",
                note="test_note",
                ignore=["mtaos"],
            ),
            dict(
                offset_xy=dict(x=[180], y=[60]),
                exp_times=1,
                program="Test_program",
            ),
            dict(
                offset_rot=dict(rot=[180]),
                exp_times=[1, 1],
                program="Test_program",
            ),
        ]

        async with self.make_script():
            for config in configs_good:
                await self.configure_script(**config)

                default_values = dict(
                    image_type="ACQ",
                    relative=True,
                    reset_offsets_when_finished=True,
                )

                self.assert_config(default_values, config)

    async def test_invalid_configurations(self):
        # Set of invalid configurations to test, these should fail to configure
        configs_bad = [
            dict(),
            dict(offset_azel=dict(az=[180, 100], el=[60, 50])),
            dict(
                offset_azel=dict(az=[180, 100], el=[60]),
                exp_times=[1],
                program="test_program",
            ),
        ]

        self.remotes_needed = False
        async with self.make_script():
            for config in configs_bad:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**config)

                    assert self.state.state == ScriptState.CONFIGURE_FAILED

    def assert_config(self, default_values, config):
        configured_values = dict(
            offset_azel=self.script.offset_azel,
            offset_xy=self.script.offset_xy,
            offset_rot=self.script.offset_rot,
            exp_times=self.script.exp_times,
            image_type=self.script.image_type,
            relative=self.script.relative,
            program=self.script.program,
            reason=self.script.reason,
            note=self.script.note,
            reset_offsets_when_finished=self.script.reset_offsets_when_finished,
        )

        for parameter in default_values:
            with self.subTest(config=config, parameter=parameter):
                assert (
                    config.get(parameter, default_values.get(parameter))
                    == configured_values[parameter]
                )

    async def test_run_offset_azel(self):
        async with self.make_dry_script():
            offset_azel = dict(az=[180, 100], el=[60, 50])
            exp_times = [1, 1, 1]
            await self.configure_script(
                offset_azel=offset_azel,
                exp_times=exp_times,
                program="Test_program",
            )

            await self.run_script()

            assert self.script.mtcs.offset_azel.await_count == len(offset_azel["az"])
            assert self.script.lsstcam.take_imgtype.await_count == len(
                offset_azel["az"]
            ) * len(exp_times)
            self.script.mtcs.reset_offsets.assert_awaited_once()

    async def test_run_offset_xy(self):
        async with self.make_dry_script():
            offset_xy = dict(x=[180, 100], y=[0, 0])
            exp_times = [1, 1, 1]
            await self.configure_script(
                offset_xy=offset_xy,
                exp_times=exp_times,
                program="Test_program",
            )

            await self.run_script()

            assert self.script.mtcs.offset_xy.await_count == len(offset_xy["x"])
            assert self.script.lsstcam.take_imgtype.await_count == len(
                offset_xy["x"]
            ) * len(exp_times)
            self.script.mtcs.reset_offsets.assert_awaited_once()

    async def test_run_offset_rot(self):
        async with self.make_dry_script():
            offset_rot = dict(rot=[3, 6])
            exp_times = [1, 1, 1]
            await self.configure_script(
                offset_rot=offset_rot,
                exp_times=exp_times,
                program="Test_program",
            )

            await self.run_script()

            assert self.script.mtcs.offset_rot.await_count == len(offset_rot["rot"])
            assert self.script.lsstcam.take_imgtype.await_count == len(
                offset_rot["rot"]
            ) * len(exp_times)
            self.script.mtcs.reset_offsets.assert_awaited_once()

    async def test_executable(self):
        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "maintel" / "offset_and_take_images_lsstcam.py"
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
