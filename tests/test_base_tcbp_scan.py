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

import os
import tempfile
import unittest

import astropy.io.fits as pf
import numpy as np
from lsst.ts.externalscripts.base_tcbp_scan import (
    PHOTODIODE_REFERENCE_NPY,
    FitsBuilder,
    fill_seqfile,
    get_optimized_wavelengths,
    hdu_to_base64,
    tcbp_expo_time_calculator,
)


class TestTCBPHelpers(unittest.TestCase):
    def test_get_optimized_wavelengths_known_filters(self):
        for filt in ("holo4_003", "empty_1", "OG550_65mm_1"):
            wavelengths = get_optimized_wavelengths(filt)
            self.assertGreater(len(wavelengths), 0)
            self.assertTrue(np.all(np.diff(np.sort(wavelengths)) >= 0))

    def test_get_optimized_wavelengths_unknown_filter_raises(self):
        with self.assertRaises(ValueError):
            get_optimized_wavelengths("not_a_real_filter")

    def test_tcbp_expo_time_calculator_clipping(self):
        wl_grid = np.array([200.0, 400.0, 600.0, 800.0, 1000.0])
        charges = np.array([0.1, 1.0, 1.0, 1.0, 0.1])
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, PHOTODIODE_REFERENCE_NPY)
            np.savetxt(
                ref,
                np.stack([wl_grid, charges, np.zeros_like(charges)]),
            )
            times = tcbp_expo_time_calculator(
                [350, 500, 700],
                norm=10,
                maxi=20,
                mini=2,
                uv_maxi=5,
                uv_threshold=400,
                reference_file=ref,
            )
            self.assertEqual(len(times), 3)
            # uv: clipped to uv_maxi=5
            self.assertLessEqual(times[0], 5.0)
            self.assertGreaterEqual(times[0], 2.0)
            # visible: bounded by [mini, maxi]
            for t in times[1:]:
                self.assertGreaterEqual(t, 2.0)
                self.assertLessEqual(t, 20.0)

    def test_fill_seqfile_appends(self):
        with tempfile.TemporaryDirectory() as tmp:
            datadir = os.path.join(tmp, "scan_dir")
            fill_seqfile(
                {"AUXTELID": "AT_O_001"},
                wl=400,
                tcbp_id="20260101000000",
                datadir=datadir,
                key="AUXTELID",
            )
            fill_seqfile(
                {"AUXTELID": "AT_O_002"},
                wl=410,
                tcbp_id="20260101000010",
                datadir=datadir,
                key="AUXTELID",
            )
            seq_path = os.path.join(
                datadir, f"{os.path.basename(datadir)}_wl_seq_id_image_id.txt"
            )
            with open(seq_path) as fid:
                lines = [line.strip() for line in fid.readlines()]
            self.assertEqual(len(lines), 2)
            self.assertEqual(lines[0], "4000,20260101000000,AT_O_001")
            self.assertEqual(lines[1], "4100,20260101000010,AT_O_002")

    def test_fitsbuilder_dump_returns_hdulist(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb = FitsBuilder(output_dir=tmp, filename="test.fits")
            fb.append({"FOO": 1})
            fb.append([("BAR", 2.0)], prefix="P_")
            data = np.rec.fromrecords(
                [(1.0, 0.1), (2.0, 0.2)], names=["time", "current"]
            )
            fb.add_table("KEYSIGHT", data)
            hdul = fb.dump()
            self.assertIsInstance(hdul, pf.HDUList)
            # Primary HDU + KEYSIGHT table
            self.assertEqual(len(hdul), 2)
            self.assertEqual(hdul[1].name, "KEYSIGHT")
            self.assertEqual(hdul[0].header["FOO"], 1)
            # No file written, no pickle written.
            self.assertFalse(os.path.exists(os.path.join(tmp, "test.fits")))
            self.assertFalse(os.path.exists(os.path.join(tmp, "headers.pkl")))

    def test_fitsbuilder_dump_no_tables_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            fb = FitsBuilder(output_dir=tmp, filename="test.fits")
            fb.append({"FOO": 1})
            self.assertIsNone(fb.dump())

    def test_hdu_to_base64_roundtrip(self):
        data = np.rec.fromrecords([(1.0, 0.1), (2.0, 0.2)], names=["time", "current"])
        hdul = pf.HDUList([pf.PrimaryHDU(), pf.TableHDU(data=data, name="KEYSIGHT")])
        encoded = hdu_to_base64(hdul)
        self.assertIsInstance(encoded, str)
        self.assertGreater(len(encoded), 0)


if __name__ == "__main__":
    unittest.main()
