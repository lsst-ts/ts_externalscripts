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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import unittest
import unittest.mock as mock

import pytest
from lsst.ts import salobj
from lsst.ts.externalscripts import get_scripts_dir
from lsst.ts.externalscripts.maintel.take_comcam_guider_image import (
    TakeComCamGuiderImage,
)
from lsst.ts.standardscripts import BaseScriptTestCase


class TestTakeComCamGuiderImage(BaseScriptTestCase, unittest.IsolatedAsyncioTestCase):
    async def basic_make_script(self, index):
        self.script = TakeComCamGuiderImage(index=index)

        self.script.comcam = mock.AsyncMock()

        return [
            self.script,
        ]

    async def test_configure(self):
        config = dict(
            exposure_time=30,
            roi_spec=dict(
                common=dict(
                    rows=50,
                    cols=50,
                    integration_time_millis=100,
                ),
                roi=dict(
                    R00SG0=dict(
                        segment=3,
                        start_row=100,
                        start_col=200,
                    ),
                ),
            ),
        )
        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.exposure_time == 30
            assert self.script.roi_spec is not None
            assert self.script.roi_spec.common.rows == 50
            assert self.script.roi_spec.common.cols == 50
            assert self.script.roi_spec.common.integrationTimeMillis == 100
            assert self.script.roi_spec.roi["R00SG0"].segment == 3
            assert self.script.roi_spec.roi["R00SG0"].startRow == 100
            assert self.script.roi_spec.roi["R00SG0"].startCol == 200

    async def test_configure_fail_if_empty(self):

        async with self.make_script():
            with pytest.raises(
                salobj.ExpectedError, match="'roi_spec' is a required property"
            ):
                await self.configure_script()

    async def test_configure_fail_empty_roi_spec(self):

        config = dict(roi_spec=dict())
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(**config)

    async def test_configure_fail_no_common(self):

        config = dict(
            roi_spec=dict(
                roi=dict(
                    R00SG0=dict(
                        segment=3,
                        start_row=100,
                        start_col=200,
                    ),
                ),
            ),
        )
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(**config)

    async def test_configure_fail_no_roi(self):
        config = dict(
            roi_spec=dict(
                common=dict(
                    rows=50,
                    cols=50,
                    integration_time_millis=100,
                ),
            ),
        )
        async with self.make_script():
            with pytest.raises(salobj.ExpectedError):
                await self.configure_script(**config)

    async def test_run(self):
        reason = "test guider"
        program = "BLOCK-T123"
        note = "this is a test"
        config = dict(
            exposure_time=30,
            reason=reason,
            program=program,
            note=note,
            roi_spec=dict(
                common=dict(
                    rows=50,
                    cols=50,
                    integration_time_millis=100,
                ),
                roi=dict(
                    R00SG0=dict(
                        segment=3,
                        start_row=100,
                        start_col=200,
                    ),
                ),
            ),
        )
        async with self.make_script():
            await self.configure_script(**config)

            await self.run_script()

            self.script.comcam.init_guider.assert_awaited_with(
                roi_spec=self.script.roi_spec
            )
            self.script.comcam.take_engtest.assert_awaited_with(
                n=1,
                exptime=self.script.exposure_time,
                reason=reason,
                program=program,
                group_id=self.script.group_id,
                note=note,
            )

    async def test_executable(self):
        scripts_dir = get_scripts_dir()
        script_path = scripts_dir / "maintel" / "take_comcam_guider_image.py"
        await self.check_executable(script_path)
