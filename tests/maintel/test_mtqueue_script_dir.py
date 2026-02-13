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

from lsst.ts.externalscripts import get_mtqueue_scripts_dir, get_scripts_dir


class TestMTQueueScriptDir(unittest.TestCase):
    def setUp(self) -> None:
        self.scripts_path = get_scripts_dir()
        self.mtqueue_scripts_path = get_mtqueue_scripts_dir()
        return super().setUp()

    def test_mtqueue_scripts_path_exists(self):
        assert self.mtqueue_scripts_path.is_dir()

    def test_mtqueue_scripts_symlinks_match_scripts_dir(self):
        mtqueue_maintel_scripts_path = self.mtqueue_scripts_path / "maintel"
        maintel_scripts_path = self.scripts_path / "maintel"
        # Check that maintel specifics scripts are present
        assert (
            mtqueue_maintel_scripts_path.is_dir()
            and mtqueue_maintel_scripts_path.is_symlink()
            and not mtqueue_maintel_scripts_path.readlink().is_absolute()
            and mtqueue_maintel_scripts_path.samefile(maintel_scripts_path)
        )
        # Check that exists a symlink to every common script in mtqueue path
        common_script_list = [
            s for s in os.scandir(self.scripts_path) if s.name.endswith(".py")
        ]
        for common_script in common_script_list:
            mtqueue_script = self.mtqueue_scripts_path / common_script.name
            assert (
                mtqueue_script.exists()
                and mtqueue_script.is_symlink()
                and not mtqueue_script.readlink().is_absolute()
                and mtqueue_script.samefile(common_script)
            )
        # Check that there are no extra scripts present
        mtqueue_common_script_list = [
            s for s in os.scandir(self.mtqueue_scripts_path) if s.name.endswith(".py")
        ]
        assert len(mtqueue_common_script_list) == len(common_script_list)


if __name__ == "__main__":
    unittest.main()
