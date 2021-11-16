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

import pathlib
import unittest

from lsst.ts import externalscripts


class TestUtils(unittest.TestCase):
    def test_get_scripts_dir(self):
        scripts_dir = externalscripts.get_scripts_dir()
        assert scripts_dir.is_dir()

        pkg_path = pathlib.Path(__file__).resolve().parent.parent
        predicted_path = pkg_path / "scripts"
        assert scripts_dir.samefile(predicted_path)
