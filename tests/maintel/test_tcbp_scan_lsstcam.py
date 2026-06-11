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

import tempfile
import unittest
import unittest.mock as mock

from lsst.ts import externalscripts, standardscripts
from lsst.ts.externalscripts.maintel.tcbp_scan_lsstcam import TCBPScanLSSTCam


def _make_mock_tcbp():
    tcbp = mock.MagicMock()
    tcbp.tcbp = mock.MagicMock()
    tcbp.tcbp.close_shutter = mock.MagicMock()
    tcbp.tcbp.fill_seqfile = mock.MagicMock()
    tcbp.tcbp.write_fits = mock.MagicMock()
    tcbp.tcbp.seq_id = "20260101000000"
    tcbp.initialize = mock.MagicMock()
    tcbp.set_exposure = mock.MagicMock()
    tcbp.shot = mock.MagicMock()
    # make_fits now returns (hdu, filename); use a real (small) HDUList so
    # hdu_to_base64 can serialise it.
    import astropy.io.fits as pf

    hdu = pf.HDUList([pf.PrimaryHDU()])
    tcbp.make_fits = mock.MagicMock(return_value=(hdu, "dummy.fits"))
    return tcbp


class TestTCBPScanLSSTCam(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = TCBPScanLSSTCam(index=index)
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.start_task = mock.AsyncMock()
        self.script.lsstcam.take_imgtype = mock.AsyncMock(return_value=[1001])
        self.script.lsstcam.setup_instrument = mock.AsyncMock()

        self.tcbp_mock = _make_mock_tcbp()
        self.script.make_tcbp = mock.MagicMock(return_value=self.tcbp_mock)

        return (self.script,)

    async def test_configure(self):
        async with self.make_script():
            await self.configure_script(
                addr_tcbp="http://maintel-tcbp:9001",
                addr_logictimer="http://maintel-tcbp:7912",
                wavelengths=[450, 550],
                lsstcam_filter="r_57",
            )
            assert self.script.wavelengths == [450, 550]
            assert self.script.lsstcam_filter == "r_57"
            self.script.lsstcam.setup_instrument.assert_awaited_once_with(filter="r_57")

    async def test_run_takes_images_and_shots(self):
        with tempfile.TemporaryDirectory() as tmp:
            async with self.make_script():
                await self.configure_script(
                    addr_tcbp="http://maintel-tcbp:9001",
                    addr_logictimer="http://maintel-tcbp:7912",
                    wavelengths=[450, 550, 650, 750],
                    datadir=tmp,
                    tcbp_remote_datadir="/home/dice/data/frames",
                    dark_step=10,
                    pre_expo_time=0,
                    post_expo_time=0,
                    mini=0.1,
                    maxi=0.1,
                    uv_maxi=0.1,
                )
                await self.run_script()

                # 4 wavelengths + 1 dark (only k=0 hits dark_step=10) = 5
                assert self.script.lsstcam.take_imgtype.call_count == 5
                assert self.tcbp_mock.shot.call_count == 4
                # 1 dark + 4 scans worth of remote seq-file writes.
                assert self.tcbp_mock.tcbp.fill_seqfile.call_count == 5
                assert self.tcbp_mock.tcbp.write_fits.call_count == 4
                # Remote datadir should be tcbp_remote_datadir/<basename>.
                first_call = self.tcbp_mock.tcbp.write_fits.call_args_list[0]
                assert first_call.args[2].startswith("/home/dice/data/frames/")

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "tcbp_scan_lsstcam.py"
        await self.check_executable(script_path)


if __name__ == "__main__":
    unittest.main()
