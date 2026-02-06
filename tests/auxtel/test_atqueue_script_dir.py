#!/usr/bin/env python
# This file is part of ts_standardscripts.
#
# Developed for the Vera C. Rubin Observatory Telescope and Site Systems.
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

import os
import unittest

from lsst.ts.externalscripts import get_atqueue_scripts_dir, get_scripts_dir


class TestATQueueScriptDir(unittest.TestCase):
    def setUp(self) -> None:
        self.scripts_path = get_scripts_dir()
        self.atqueue_scripts_path = get_atqueue_scripts_dir()
        return super().setUp()

    def test_atqueue_scripts_path_exists(self):
        assert self.atqueue_scripts_path.is_dir()

    def test_mtqueue_scripts_symlinks_match_scripts_dir(self):
        atqueue_auxtel_scripts_path = self.atqueue_scripts_path / "auxtel"
        auxtel_scripts_path = self.scripts_path / "auxtel"
        # Check that auxtel specifics scripts are present
        assert (
            atqueue_auxtel_scripts_path.is_dir()
            and atqueue_auxtel_scripts_path.is_symlink()
            and not atqueue_auxtel_scripts_path.readlink().is_absolute()
            and atqueue_auxtel_scripts_path.samefile(auxtel_scripts_path)
        )
        # Check that exists a symlink to every common script in atqueue path
        common_script_list = [
            s for s in os.scandir(self.scripts_path) if s.name.endswith(".py")
        ]
        for common_script in common_script_list:
            atqueue_script = self.atqueue_scripts_path / common_script.name
            assert (
                atqueue_script.exists()
                and atqueue_script.is_symlink()
                and not atqueue_script.readlink().is_absolute()
                and atqueue_script.samefile(common_script)
            )
        # Check that there are no extra scripts present
        atqueue_common_script_list = [
            s for s in os.scandir(self.atqueue_scripts_path) if s.name.endswith(".py")
        ]
        assert len(atqueue_common_script_list) == len(common_script_list)


if __name__ == "__main__":
    unittest.main()
