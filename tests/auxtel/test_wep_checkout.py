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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import unittest

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.auxtel import WepCheckout


class TestWepCheckout(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):

    async def basic_make_script(self, index):

        self.script = WepCheckout(index=index)

        return (self.script,)

    async def test_configure(self):

        config = {
            "intra_visit_id": "2021110400954",
            "extra_visit_id": "2021110400955",
            "dz": 1.5,
            "side": 192,
            "expected_zern_defocus": 69.856,
            "expected_zern_coma_x": 35.745,
            "expected_zern_coma_y": 70.311,
            "threshold": 20,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.config.intra_visit_id == config["intra_visit_id"]
            assert self.script.config.extra_visit_id == config["extra_visit_id"]
            assert self.script.config.dz == config["dz"]
            assert self.script.config.side == config["side"]
            assert (
                self.script.config.expected_zern_defocus
                == config["expected_zern_defocus"]
            )
            assert (
                self.script.config.expected_zern_coma_x
                == config["expected_zern_coma_x"]
            )
            assert (
                self.script.config.expected_zern_coma_y
                == config["expected_zern_coma_y"]
            )
            assert self.script.config.threshold == config["threshold"]

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "wep_checkout.py"
        await self.check_executable(script_path)
