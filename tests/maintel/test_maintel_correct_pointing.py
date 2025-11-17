import unittest
import unittest.mock as mock

import numpy as np
import pytest
from astropy.table import Table
from lsst.ts import externalscripts, salobj, standardscripts
from lsst.ts.externalscripts.maintel.correct_pointing import CorrectPointing


class TestCorrectPointing(
    standardscripts.BaseScriptTestCase, unittest.IsolatedAsyncioTestCase
):
    async def basic_make_script(self, index):
        self.script = CorrectPointing(index=index)

        self.mock_mtcs()
        self.mock_camera()
        self.mock_consdb()

        return (self.script,)

    def mock_mtcs(self):
        """Mock MTCS instance and its methods."""
        self.script.mtcs = mock.AsyncMock()
        self.script.mtcs.assert_liveliness = mock.AsyncMock()
        self.script.mtcs.assert_all_enabled = mock.AsyncMock()
        self.script.mtcs.offset_radec = mock.AsyncMock()
        self.script.mtcs.fast_timeout = 5.0

        self.script.mtcs.rem = mock.Mock()
        self.script.mtcs.rem.mtptg = mock.Mock()

        mock_current_target = mock.AsyncMock()
        mock_current_target.ra = 0.5
        mock_current_target.declination = -0.3
        self.script.mtcs.rem.mtptg.evt_currentTarget = mock.Mock()
        self.script.mtcs.rem.mtptg.evt_currentTarget.aget = mock.AsyncMock(
            return_value=mock_current_target
        )

    def mock_camera(self):
        """Mock camera instance and its methods."""
        self.script.lsstcam = mock.AsyncMock()
        self.script.lsstcam.assert_liveliness = mock.AsyncMock()
        self.script.lsstcam.assert_all_enabled = mock.AsyncMock()
        self.script.lsstcam.take_acq = mock.AsyncMock(return_value=[123456])
        self.script.lsstcam.read_out_time = 2.0
        self.script.lsstcam.shutter_time = 1.0

    def mock_consdb(self):
        """Mock ConsDB client and its methods."""
        self.script.consdb_client = mock.Mock()
        self.script.consdb_client.wait_for_row_to_exist = mock.Mock(
            side_effect=self.mock_consdb_wait_for_row
        )

    def mock_consdb_wait_for_row(self, query, timeout, poll_frequency_hz=2):
        """Mock ConsDB wait_for_row_to_exist with realistic WCS solution.

        Returns an Astropy Table with s_ra and s_dec columns.
        """
        # Return a table with WCS solution close to target for default case
        return Table(rows=[[28.65432, -17.12345]], names=["s_ra", "s_dec"])

    async def test_configure(self):
        config = {
            "exposure_time": 3.0,
            "tolerance_arcsec": 0.5,
            "max_iterations": 7,
            "consdb_timeout": 90.0,
            "consdb_max_retries": 5,
        }

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.exposure_time == 3.0
            assert self.script.tolerance_arcsec == 0.5
            assert self.script.max_iterations == 7
            assert self.script.consdb_timeout == 90.0
            assert self.script.consdb_max_retries == 5

    async def test_configure_defaults(self):
        config = {}

        async with self.make_script():
            await self.configure_script(**config)

            assert self.script.exposure_time == 2.0
            assert self.script.tolerance_arcsec == 1.0
            assert self.script.max_iterations == 5
            assert self.script.consdb_timeout == 60.0
            assert self.script.consdb_max_retries == 3

    async def test_invalid_configuration(self):
        bad_configs = [
            {"exposure_time": 0.1},
            {"tolerance_arcsec": 0.0},
            {"max_iterations": 0},
            {"consdb_timeout": 5.0},
            {"consdb_max_retries": 0},
        ]

        async with self.make_script():
            for bad_config in bad_configs:
                with pytest.raises(salobj.ExpectedError):
                    await self.configure_script(**bad_config)

    async def test_get_target_coordinates(self):
        async with self.make_script():
            await self.configure_script()

            ra_rad, dec_rad = await self.script.get_target_coordinates()

            assert ra_rad == 0.5
            assert dec_rad == -0.3
            self.script.mtcs.rem.mtptg.evt_currentTarget.aget.assert_called_once()

    async def test_get_target_coordinates_timeout(self):
        async with self.make_script():
            await self.configure_script()

            self.script.mtcs.rem.mtptg.evt_currentTarget.aget = mock.AsyncMock(
                side_effect=TimeoutError()
            )

            with pytest.raises(
                RuntimeError, match="Could not determine current target"
            ):
                await self.script.get_target_coordinates()

    async def test_calculate_offset(self):
        async with self.make_script():
            await self.configure_script()

            target_ra_deg = 30.0
            target_dec_deg = -20.0
            measured_ra_deg = 30.001
            measured_dec_deg = -20.001

            offset_ra, offset_dec, magnitude = self.script.calculate_offset(
                target_ra_deg, target_dec_deg, measured_ra_deg, measured_dec_deg
            )

            assert offset_ra > 0
            assert offset_dec < 0
            assert magnitude > 0
            assert magnitude == pytest.approx(
                np.sqrt(offset_ra**2 + offset_dec**2), rel=1e-6
            )

    async def test_calculate_offset_zero(self):
        async with self.make_script():
            await self.configure_script()

            target_ra_deg = 30.0
            target_dec_deg = -20.0

            offset_ra, offset_dec, magnitude = self.script.calculate_offset(
                target_ra_deg, target_dec_deg, target_ra_deg, target_dec_deg
            )

            assert offset_ra == 0.0
            assert offset_dec == 0.0
            assert magnitude == 0.0

    async def test_apply_pointing_offset(self):
        async with self.make_script():
            await self.configure_script()

            offset_ra_arcsec = 2.5
            offset_dec_arcsec = -1.8

            await self.script.apply_pointing_offset(offset_ra_arcsec, offset_dec_arcsec)

            self.script.mtcs.offset_radec.assert_called_once_with(
                ra=offset_ra_arcsec, dec=offset_dec_arcsec, absorb=True
            )

    async def test_get_measured_coordinates_from_consdb(self):
        async with self.make_script():
            await self.configure_script()

            exposure_id = 123456

            ra_deg, dec_deg = await self.script.get_measured_coordinates_from_consdb(
                exposure_id
            )

            assert ra_deg == 28.65432
            assert dec_deg == -17.12345
            assert self.script.consdb_client.wait_for_row_to_exist.call_count == 1

    async def test_run_converges_immediately(self):
        async with self.make_script():
            await self.configure_script(tolerance_arcsec=1000.0)

            mock_current_target = mock.AsyncMock()
            mock_current_target.ra = np.deg2rad(28.65)
            mock_current_target.declination = np.deg2rad(-17.12)
            self.script.mtcs.rem.mtptg.evt_currentTarget.aget = mock.AsyncMock(
                return_value=mock_current_target
            )

            await self.script.run()

            assert self.script.lsstcam.take_acq.call_count == 1
            self.script.mtcs.offset_radec.assert_not_called()

    async def test_run_converges_after_correction(self):
        async with self.make_script():
            await self.configure_script(tolerance_arcsec=1.0, max_iterations=3)

            mock_current_target = mock.AsyncMock()
            mock_current_target.ra = np.deg2rad(28.0)
            mock_current_target.declination = np.deg2rad(-17.0)
            self.script.mtcs.rem.mtptg.evt_currentTarget.aget = mock.AsyncMock(
                return_value=mock_current_target
            )

            # Mock different WCS solutions for each iteration
            consdb_responses = [
                (28.65, -17.12),  # First exposure: large offset
                (28.0001, -17.00005),  # Second exposure: within tolerance
            ]
            consdb_call_count = [0]

            def mock_consdb_responses(query, timeout, poll_frequency_hz=2):
                """Return different WCS solutions for each call."""
                iteration_index = consdb_call_count[0]
                iteration_index = min(iteration_index, len(consdb_responses) - 1)
                ra, dec = consdb_responses[iteration_index]

                consdb_call_count[0] += 1

                return Table(rows=[[ra, dec]], names=["s_ra", "s_dec"])

            self.script.consdb_client.wait_for_row_to_exist = mock.Mock(
                side_effect=mock_consdb_responses
            )

            await self.script.run()

            assert self.script.lsstcam.take_acq.call_count == 2
            assert self.script.mtcs.offset_radec.call_count == 1
            # Verify offset_radec was called with absorb=True
            self.script.mtcs.offset_radec.assert_called_with(
                ra=mock.ANY, dec=mock.ANY, absorb=True
            )

    async def test_run_fails_max_iterations(self):
        async with self.make_script():
            await self.configure_script(tolerance_arcsec=0.1, max_iterations=2)

            mock_current_target = mock.AsyncMock()
            mock_current_target.ra = np.deg2rad(28.0)
            mock_current_target.declination = np.deg2rad(-17.0)
            self.script.mtcs.rem.mtptg.evt_currentTarget.aget = mock.AsyncMock(
                return_value=mock_current_target
            )

            with pytest.raises(RuntimeError, match="Failed to correct pointing"):
                await self.script.run()

            assert self.script.lsstcam.take_acq.call_count == 2
            assert self.script.mtcs.offset_radec.call_count == 2
            for call in self.script.mtcs.offset_radec.call_args_list:
                assert call.kwargs["absorb"] is True

    async def test_executable(self):
        scripts_dir = externalscripts.get_scripts_dir()
        script_path = scripts_dir / "maintel" / "correct_pointing.py"
        await self.check_executable(script_path)
