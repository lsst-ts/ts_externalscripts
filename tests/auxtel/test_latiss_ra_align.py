# This file is part of ts_externalscripts.
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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

import asyncio
import logging
import unittest

import astropy.units as u
import numpy as np
import pytest
from astropy.table import QTable
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.auxtel.latiss_ra_align import LatissRAAlign

# Make matplotlib less chatty
logging.getLogger("matplotlib").setLevel(logging.WARNING)
# Make obslsst translators less chatty
logging.getLogger("lsst.obs.lsst.translators").setLevel(logging.WARNING)
logging.getLogger("astro_metadata_translator").setLevel(logging.WARNING)
logging.getLogger("flake8.style_guide").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.propagate = True


def make_zernike_table(z4: float, z7: float, z8: float) -> QTable:
    """Build a minimal 'zernikes' table matching the schema published by
    Rapid Analysis (LatissMonolithTask), with a single 'average' row."""
    table = QTable()
    table["label"] = ["average"]
    table["Z4"] = [z4] * u.nm
    table["Z7"] = [z7] * u.nm
    table["Z8"] = [z8] * u.nm
    return table


class TestLatissRAAlign(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    def setUp(self):
        self.mocks_configured = False

    async def basic_make_script(self, index):
        self.script = LatissRAAlign(index=index, remotes=True)

        # Avoid constructing a real Butler; configure() only (re)creates it
        # if self.butler is None.
        self.script.butler = unittest.mock.MagicMock()

        return (self.script,)

    async def ataos_cmd_offset_callback(self, data):
        """Publishes event from hexapod saying movement completed.
        Also flips the ataos detailed state"""
        logger.debug("Sending hexapod events and ataos events")

        ss_idle = np.uint8(0)
        ss_hexapod = np.uint8(1 << 3)  # Hexapod correction running

        await self.ataos.evt_detailedState.set_write(
            substate=ss_hexapod, force_output=True
        )
        await self.athexapod.evt_positionUpdate.write()
        await self.athexapod.tel_positionStatus.write()
        await self.ataos.evt_detailedState.set_write(
            substate=ss_idle, force_output=True
        )
        return

    async def configure_mocks(self):
        self.mocks_configured = True

        self.end_image_tasks = []
        self.img_cnt_override_list = None

        # Load controllers and required callbacks to simulate
        # telescope/instrument behaviour
        self.atcamera = salobj.Controller(name="ATCamera")
        self.atheaderservice = salobj.Controller(name="ATHeaderService")
        self.atoods = salobj.Controller(name="ATOODS")
        self.ataos = salobj.Controller(name="ATAOS")
        self.athexapod = salobj.Controller(name="ATHexapod")
        self.atptg = salobj.Controller(name="ATPtg")
        self.atmcs = salobj.Controller(name="ATMCS")

        self.atcamera.cmd_takeImages.callback = unittest.mock.AsyncMock(
            wraps=self.cmd_take_images_callback
        )
        self.script.latiss.ready_to_take_data = unittest.mock.AsyncMock(
            return_value=True
        )
        self.script.latiss.setup_atspec = unittest.mock.AsyncMock()

        self.ataos.cmd_offset.callback = unittest.mock.AsyncMock(
            wraps=self.ataos_cmd_offset_callback
        )
        self.script.atcs.offset_xy = unittest.mock.AsyncMock()
        self.script.atcs.add_point_data = unittest.mock.AsyncMock()
        self.script.atcs.get_bore_sight_angle = unittest.mock.AsyncMock(
            return_value=13.5
        )

        self.nimages = 0
        self.date = "20240101"
        self.seq_num_start = 1

    async def close(self):
        """Optional cleanup before closing the scripts and etc."""
        if self.mocks_configured:
            logger.debug("Closing Remotes")
            await asyncio.gather(*self.end_image_tasks, return_exceptions=True)
            await asyncio.gather(
                self.atoods.close(),
                self.atcamera.close(),
                self.atheaderservice.close(),
                self.ataos.close(),
                self.athexapod.close(),
                self.atptg.close(),
                self.atmcs.close(),
            )
            logger.debug("Remotes Closed")

    async def cmd_take_images_callback(self, data):
        one_exp_time = (
            data.expTime
            + self.script.latiss.read_out_time
            + self.script.latiss.shutter_time
        )
        await asyncio.sleep(one_exp_time * data.numImages)
        self.nimages += 1
        self.end_image_tasks.append(asyncio.create_task(self.finish_take_images()))

    async def finish_take_images(self):
        await asyncio.sleep(0.5)
        if not self.img_cnt_override_list:
            imgNum = self.atcamera.cmd_takeImages.callback.await_count - 1
            image_name = f"AT_O_{self.date}_{(imgNum + self.seq_num_start):06d}"
        else:
            imgNum = self.img_cnt_override_list[
                self.atcamera.cmd_takeImages.callback.await_count - 1
            ]
            image_name = f"AT_O_{self.date}_{(imgNum):06d}"

        await self.atcamera.evt_endReadout.set_write(imageName=image_name)
        await asyncio.sleep(0.5)
        await self.atheaderservice.evt_largeFileObjectAvailable.write()
        await asyncio.sleep(1.0)
        await self.atoods.evt_imageInOODS.set_write(obsid=image_name)

    async def test_configure_ra_defaults(self):
        async with self.make_script():
            self.script.atcs = unittest.mock.AsyncMock()
            self.script.latiss = unittest.mock.AsyncMock()

            await self.configure_script()

            assert self.script.ra_timeout == 120.0
            assert self.script.ra_poll_interval == 5.0
            assert self.script.ZERNIKE_DATASET_TYPE == "zernikes"
            assert self.script.ra_collections == ["LATISS/runs/quickLook"]

    async def test_configure_ra_overrides(self):
        async with self.make_script():
            self.script.atcs = unittest.mock.AsyncMock()
            self.script.latiss = unittest.mock.AsyncMock()

            await self.configure_script(
                ra_timeout=30.0,
                ra_poll_interval=1.0,
            )

            assert self.script.ra_timeout == 30.0
            assert self.script.ra_poll_interval == 1.0

    async def test_run_align_parses_zernikes(self):
        async with self.make_script():
            self.script.atcs = unittest.mock.AsyncMock()
            self.script.latiss = unittest.mock.AsyncMock()
            await self.configure_script()

            self.script.intra_visit_id = 2021110400954
            self.script.extra_visit_id = 2021110400955
            self.script.angle = 90.0 - 88.79

            zk_table = make_zernike_table(z4=50.7, z7=30.8, z8=60.1)
            dataset_ref = unittest.mock.MagicMock()
            dataset_ref.dataId = {"visit": self.script.extra_visit_id}
            self.script.butler.query_datasets.return_value = [dataset_ref]
            self.script.butler.get.return_value = zk_table

            results = await self.script.run_align()

            meas_zerns = [-60.1, 30.8, 50.7]
            for i, z in enumerate(results.zernikes):
                with self.subTest(msg="zern comparison", z=z, i=i):
                    assert z == pytest.approx(meas_zerns[i])

            self.script.butler.query_datasets.assert_called_once()
            args, kwargs = self.script.butler.query_datasets.call_args
            assert args[0] == "zernikes"
            assert kwargs["collections"] == ["LATISS/runs/quickLook"]
            assert "2021110400954" in kwargs["where"]
            assert "2021110400955" in kwargs["where"]

            self.script.butler.get.assert_called_once_with(
                "zernikes",
                dataId=dataset_ref.dataId,
                collections=["LATISS/runs/quickLook"],
            )

    async def test_get_zernikes_from_ra_polls_until_found(self):
        async with self.make_script():
            self.script.atcs = unittest.mock.AsyncMock()
            self.script.latiss = unittest.mock.AsyncMock()
            await self.configure_script(ra_poll_interval=0.01, ra_timeout=1.0)

            self.script.intra_visit_id = 100
            self.script.extra_visit_id = 101

            zk_table = make_zernike_table(z4=1.0, z7=2.0, z8=3.0)
            dataset_ref = unittest.mock.MagicMock()
            dataset_ref.dataId = {"visit": 101}

            self.script.butler.query_datasets.side_effect = [[], [], [dataset_ref]]
            self.script.butler.get.return_value = zk_table

            result = await self.script.get_zernikes_from_ra()

            assert result is zk_table
            assert self.script.butler.query_datasets.call_count == 3

    async def test_get_zernikes_from_ra_timeout(self):
        async with self.make_script():
            self.script.atcs = unittest.mock.AsyncMock()
            self.script.latiss = unittest.mock.AsyncMock()
            await self.configure_script(ra_poll_interval=0.01, ra_timeout=0.05)

            self.script.intra_visit_id = 100
            self.script.extra_visit_id = 101

            self.script.butler.query_datasets.return_value = []

            with pytest.raises(TimeoutError):
                await self.script.get_zernikes_from_ra()

    async def test_arun_converges_single_iteration(self):
        async with self.make_script():
            await self.configure_script(threshold=1000.0, coma_threshold=1000.0)
            await self.configure_mocks()

            zk_table = make_zernike_table(z4=0.0, z7=0.0, z8=0.0)
            dataset_ref = unittest.mock.MagicMock()
            dataset_ref.dataId = {"visit": 0}
            self.script.butler.query_datasets.return_value = [dataset_ref]
            self.script.butler.get.return_value = zk_table

            await self.script.arun()

            assert self.script.iterations_executed == 0
            assert self.script.atcs.add_point_data.called

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "auxtel" / "latiss_ra_align.py"
        logger.debug(f"Checking for script in {script_path}")
        await self.check_executable(script_path)
