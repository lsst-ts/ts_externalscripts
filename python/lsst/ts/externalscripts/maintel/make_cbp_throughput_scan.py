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

__all__ = ["MakeCBPThroughputScan"]

import abc
import asyncio
import types

import numpy as np
import pandas as pd
import yaml
from lsst.ts import salobj
from lsst.ts.observatory.control.utils.enums import LaserOpticalConfiguration
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.xml.enums.Electrometer import UnitToRead
from lsst.ts.xml.enums.TunableLaser import LaserDetailedState


class MakeCBPThroughputScan(BaseBlockScript, metaclass=abc.ABCMeta):
    """Class for making CBP throughput scan with CBP calibration system."""

    def __init__(self, index, descr="Script for making CBP throughput scan.") -> None:
        super().__init__(index, descr)

        self.config = None

        self.cbp = None
        self.electrometer_cbp = None
        self.electrometer_cbp_cal = None
        self.tunablelaser = None

        self.long_timeout = 30
        self.long_long_timeout = 60
        self.electrometer_cbp_index = 101
        self.electrometer_cbp_cal_index = 102

        self.laser_warmup = 30

        self.cbp_index = 0

    '''
    @property
    def calsys(self):
        return self.mtcalsys

    async def configure_calsys(self):
        """Handle creating the MTCalsys object and waiting remote to start"""
        if self.mtcalsys is None:
            self.log.debug("Creating MTCalsys.")
            self.mtcalsys = MTCalsys(
                domain=self.domain,
                intended_usage=MTCalsysUsages.StateTransition,
                log=self.log,
            )
            await self.mtcalsys.start_task
        else:
            self.log.debug("MTCalsys already defined, skipping.")
    '''

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/make_cbp_throughput_scan.yaml
            title: MakeCBPThroughputScan
            description: Configuration schema for MakeCBPThroughputScan.
            type: object
            properties:
              wavelength:
                description: >-
                  Center wavelength value in nm, used for configuring the Tunable Laser
                type: number
                default: 700
              set_wavelength_range:
                description: >-
                  If true, set the wavelength range, otherwise, provide wavelength list.
                type: boolean
                default: true
              wavelength_width:
                description: >-
                  Optional. Defines the width of the wavelength scan range to configure the
                  Tunable Laser for the flat-field calibration sequence when using
                  monochromatic light.
                type: number
                default: 400
              wavelength_resolution:
                description: >-
                  Optional. When using a monochromatic light source, it defines the
                  resolution used to sample values within the scan range, which has a width
                  defined by `wavelength_width` and is centered around the `wavelength`
                  attribute.
                type: number
                default: 100
              wavelength_list:
                description: >-
                  Optional. Lists wavelengths to scan in nm.
                type: array
                default: [450]
              electrometer_integration_time:
                description: >-
                  Integration time in seconds (166.67e-6 to 200e-3) for each sample.
                  The integration time (measurement speed) of the analog to digital (A/D)
                  converter, the period of time the input signal is measured (also known as
                  aperture). Due to the time it takes to read the buffer and process the
                  data, this is not the rate at which samples are taken. This is generally
                  specified by the Power Line Cycle (PLC), where 1 PLC for 60Hz is
                  16.67msec. Fast integration=0.01PLC; Medium integration=0.1PLC; Normal
                  (default) integration = 1PLC; High Accuracy integration=10PLC. Here the
                  integration is set in seconds.
                type: number
                default: 0.001
              electrometer_mode:
                description: >-
                  Set electrometer to use different modes. The units recorded will be Amps
                  for `CURRENT`, Volts for `VOLTAGE`, Coulombs for `CHARGE`, and Ohms for
                  `RESISTANCE`.
                type: string
                enum:
                  - CURRENT
                  - CHARGE
                  - VOLTAGE
                  - RESISTANCE
                default: CHARGE
              electrometer_range:
                description: >-
                  Set measurement range, which effects the accuracy of measurements and the
                  max signal that can be measured. The maximum input signal is 105% of the
                  measurement range. It will set the value for the current mode selected.
                  Auto-range will automatically go to the most sensitive (optimized) range
                  to make measurements. It is recommended to use autorange. When the
                  measurement range is changed, a zero correction will be performed.
                  -1 for automatic range. Volts range from 0 to 210 Volts, Current range
                  from 0 to 21e-3 Amps, Resistance from 0 to 100e18 Ohms, Charge from 0 to
                  +2.1e-6 Coulombs.
                type: number
              laser_mode:
                type: integer
                default: 2
              optical_configuration:
                type: string
                enum:
                  - SCU
                  - NO SCU
                  - F1 SCU
                  - F2 SCU
                  - F2 NO SCU
                  - F1 NO SCU
                default: F1 SCU
              nburst:
                type: integer
                default: 5
              cbp_elevation:
                description: CBP elevation in degrees.
                type: number
                default: 0
              cbp_azimuth:
                description: CBP azimuth in degrees.
                type: number
                default: 0
              cbp_mask:
                description: CBP azimuth in degrees.
                type: integer
                default: 4
                minimum: 1
                maximum: 5
              cbp_rotation:
                description: CBP mask rotator angle in degrees.
                type: number
                default: 0
              cbp_focus:
                description: CBP focus position in um.
                type: number
                default: 6000
                minimum: 0
                maximum: 13000
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()

        for properties in base_schema_dict["properties"]:
            schema_dict["properties"][properties] = base_schema_dict["properties"][
                properties
            ]

        return schema_dict

    async def configure(self, config: types.SimpleNamespace):
        """Configure script components including camera.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        self.config = config

        await super().configure(config)

    async def start_system(self):

        self.electrometer_cbp = salobj.Remote(
            name="Electrometer",
            domain=self.domain,
            index=self.electrometer_cbp_index,
        )

        self.electrometer_cbp_cal = salobj.Remote(
            name="Electrometer",
            domain=self.domain,
            index=self.electrometer_cbp_cal_index,
        )

        self.cbp = salobj.Remote(
            name="CBP",
            domain=self.domain,
        )

        self.tunablelaser = salobj.Remote(
            name="TunableLaser",
            domain=self.domain,
        )

        await self.electrometer_cbp.start_task
        await salobj.set_summary_state(self.electrometer_cbp, salobj.State.ENABLED)

        await self.electrometer_cbp_cal.start_task
        await salobj.set_summary_state(self.electrometer_cbp_cal, salobj.State.ENABLED)

        await self.cbp.start_task
        await salobj.set_summary_state(self.cbp, salobj.State.ENABLED)

        await self.tunablelaser.start_task
        await salobj.set_summary_state(self.tunablelaser, salobj.State.ENABLED)

    async def setup_cbp(
        self,
        azimuth: float,
        elevation: float,
        mask: int,
        focus: float,
        rotation: float,
    ) -> None:
        """Perform all steps for preparing the CBP for measurements.

        Parameters
        ----------
        az : `float`
            Azimuth of CBP in degrees
        el : `float`
            Elevation of CBP in degrees
        mask : `int`
            Mask number to use
        focus: `float`
            Focus position in um
        rot: `int`
            Rotator position of mask in degrees
            Default 0
        """
        timeout = 60
        await self.cbp.cmd_move.set_start(
            azimuth=azimuth, elevation=elevation, timeout=timeout
        )
        if focus is not None:
            await self.cbp.cmd_setFocus.set_start(focus=focus, timeout=timeout)
        if mask is not None:
            await self.cbp.cmd_changeMask.set_start(mask=mask, timeout=timeout)
        if rotation is not None:
            await self.cbp.cmd_changeMaskRotation.set_start(
                mask_rotation=rotation, timeout=timeout
            )

    async def setup_electrometer(
        self, electrometer, mode: str, range: float, integration_time: float
    ) -> None:
        """Setup all electrometers.

        Parameters
        ----------
        mode : `str`
            Electrometer measurement mode.
        range : `float`
            Electrometer measurement range. -1 for autorange.
        integration_time : `float`
            Electrometer measurement range.
        """
        electrometer_mode = getattr(UnitToRead, mode).value

        await electrometer.cmd_setMode.set_start(
            mode=electrometer_mode,
            timeout=self.long_timeout,
        )
        await electrometer.cmd_setRange.set_start(
            setRange=range,
            timeout=self.long_timeout,
        )
        await electrometer.cmd_setIntegrationTime.set_start(
            intTime=integration_time,
            timeout=self.long_timeout,
        )
        await electrometer.cmd_performZeroCalib.start(timeout=self.long_timeout)
        """
        await electrometer.cmd_setDigitalFilter.set_start(
            activateFilter=False,
            activateAvgFilter=False,
            activateMedFilter=False,
            timeout=self.long_timeout,
        )
        """

    async def setup_laser(
        self,
        mode: LaserDetailedState,
        wavelength: float,
        optical_configuration: LaserOpticalConfiguration = "F1_SCU",
        use_projector: bool = True,
    ) -> None:
        """Perform all steps for preparing the laser for monochromatic flats.
        This includes confirming that the thermal system is
        turned on and set at the right temperature. It also checks
        the interlockState to confirm it's ready to propagate.

        Parameters
        ----------
        mode : LaserDetailedState
            Mode of the TunableLaser
            Options: CONTINUOUS, BURST
        wavelength : `float`
            Wavelength fo the laser in nm
        optical_configuration : LaserOpticalConfiguration
            Output of laser
            Default LaserOpticalConfiguration.SCU
        use_projector : `bool`
            identifies if you are using the projector while
            changing the wavelength
            Default True
        """
        # TO-DO: DM-45693 implement thermal system checks

        if mode in {
            LaserDetailedState.NONPROPAGATING_CONTINUOUS_MODE,
            LaserDetailedState.PROPAGATING_CONTINUOUS_MODE,
        }:
            await self.tunablelaser.cmd_setContinuousMode.start(
                timeout=self.long_timeout
            )
        elif mode in {
            LaserDetailedState.NONPROPAGATING_BURST_MODE,
            LaserDetailedState.PROPAGATING_BURST_MODE,
        }:
            await self.tunablelaser.cmd_setBurstMode.start(timeout=self.long_timeout)
        else:
            raise RuntimeError(
                f"{mode} not an acceptable LaserDetailedState [CONTINOUS, BURST, TRIGGER]"
            )

        await self.change_laser_optical_configuration(optical_configuration)
        await self.change_laser_wavelength(wavelength)

    async def change_laser_optical_configuration(
        self, optical_configuration: LaserOpticalConfiguration
    ) -> None:
        """Change the output of the laser.

        Parameters
        ----------
        optical_configuration : LaserOpticalConfiguration
        """
        assert optical_configuration in list(LaserOpticalConfiguration)

        current_configuration = await self.tunablelaser.evt_opticalConfiguration.aget()
        if current_configuration.configuration != optical_configuration:
            self.log.debug(
                f"Changing optical configuration from {current_configuration} to {optical_configuration}"
            )
            await self.tunablelaser.cmd_setOpticalConfiguration.set_start(
                configuration=optical_configuration, timeout=self.long_timeout
            )

        else:
            self.log.debug("Laser Optical Configuration already in place.")

    async def change_laser_wavelength(
        self,
        wavelength: int,
    ) -> None:
        """Change the TunableLaser wavelength setting

        Parameters
        ----------
        wavelength : `float`
            wavelength of the laser in nm
        use_projector : `bool`
            identifies if you are using the projector while
            changing the wavelength.
            Default True
        """
        task_wavelength = self.tunablelaser.cmd_changeWavelength.set_start(
            wavelength=int(wavelength), timeout=self.long_long_timeout
        )
        await task_wavelength

    async def setup_calibration(self):
        """Setup calibration system"""
        """
        await self.setup_cbp(
            self.config.cbp_azimuth,
            self.config.cbp_elevation,
            self.config.cbp_mask,
            self.config.cbp_focus,
            self.config.cbp_rotation,
        )
        """
        await self.setup_laser(
            self.config.laser_mode,
            self.config.wavelength,
            self.config.optical_configuration,
        )

        await self.laser_start_propagate()

        await self.setup_electrometer(
            self.electrometer_cbp,
            self.config.electrometer_mode,
            self.config.electrometer_range,
            self.config.electrometer_integration_time,
        )

        await self.setup_electrometer(
            self.electrometer_cbp_cal,
            self.config.electrometer_mode,
            self.config.electrometer_range,
            self.config.electrometer_integration_time,
        )

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""

        scan_time = 30

        # Total duration calculation
        total_duration = (
            scan_time
            * self.config.wavelength_width
            * 2
            / self.config.wavelength_resolution
        )

        metadata.duration = total_duration

    async def laser_start_propagate(self) -> None:
        """Start the propagation of the Tunable Laser"""

        laser_state = await self.tunablelaser.evt_detailedState.next(
            flush=False, timeout=self.long_timeout
        )
        self.log.debug(f"laser state is: {laser_state}")

        if laser_state.detailedState not in {
            LaserDetailedState.PROPAGATING_CONTINUOUS_MODE,
            LaserDetailedState.PROPAGATING_BURST_MODE,
        }:
            try:
                await self.tunablelaser.cmd_startPropagateLaser.start(
                    timeout=self.laser_warmup
                )
                laser_state = await self.tunablelaser.evt_detailedState.next(
                    flush=False, timeout=self.long_timeout
                )
                self.log.info(f"Laser state: {laser_state.detailedState}")
            except asyncio.TimeoutError:
                raise RuntimeError(
                    "Tunable Laser did not start propagating when commanded"
                )

    def get_durations(self, npulse, t_dark_min=0.0001, max_pulses=6000):

        if npulse > max_pulses:
            nburst = int(self.config.nburst * npulse / max_pulses)
            npulse = max_pulses
        else:
            nburst = self.config.nburst

        burst_duration = npulse * 1e-3
        if burst_duration < 1:
            burst_duration = 1

        if burst_duration / 2 > t_dark_min:
            delay_before = burst_duration / 2
            delay_after = burst_duration * 3 / 2
        else:
            delay_before = t_dark_min
            delay_after = burst_duration + t_dark_min

        duration = (
            nburst * (burst_duration + delay_before + delay_after)
            + delay_before
            + delay_after
        )
        return duration, delay_before, delay_after

    async def _calculate_electrometer_exposure_times(
        self,
        wavelengths,
    ) -> list[float | None]:
        """Calculates the optimal exposure time for the electrometer

        Parameters
        ----------
        exptime : `list`
            List of Camera exposure times
        use_electrometer : `bool`
            Identifies if the electrometer will be used in the exposure

        Returns
        -------
        `list`[`float` | `None`]
            Exposure times for the electrometer
        """

        # TODO (DM-44777): Update optimized exposure times
        electrometer_buffer_size = 16667
        electrometer_integration_overhead = 0.00254
        electrometer_time_separation_vs_integration = 3.07

        electrometer_exptimes = []
        pulses = []
        delay_before = []
        delay_after = []

        for wavelength in wavelengths:
            npulse = 2000
            pulses.append(npulse)

            exptime, delay_before_temp, delay_after_temp = self.get_durations(npulse)

            delay_before.append(delay_before_temp)
            delay_after.append(delay_after_temp)

            time_sep = (
                self.config.electrometer_integration_time
                * electrometer_time_separation_vs_integration
            ) + electrometer_integration_overhead
            max_exp_time = electrometer_buffer_size * time_sep
            if exptime > max_exp_time:
                electrometer_exptimes.append(max_exp_time)
                self.log.info(f"Electrometer exposure time reduced to {max_exp_time}")
            else:
                electrometer_exptimes.append(exptime)

        data = {
            "wavelength": wavelengths,
            "exposure_time": electrometer_exptimes,
            "npulses": pulses,
            "delay_before": delay_before,
            "delay_after": delay_after,
        }
        return pd.DataFrame(data)

    async def take_bursts(
        self,
        duration=30,
        delay_before=5,
        delay_after=5,
        t_dark_min=0.0001,
        max_pulses=1000,
        wait_time=10,
    ):
        await asyncio.sleep(wait_time)
        await asyncio.sleep(5)
        await asyncio.sleep(delay_before)
        for n in range(self.config.nburst):
            await asyncio.sleep(delay_before)
            await self.tunablelaser.cmd_triggerBurst.start()
            await asyncio.sleep(delay_after)
        await asyncio.sleep(delay_after)

    async def _take_data(
        self,
        electrometer_exposure_time: float | None,
        delay_before: float = 5,
        delay_after: float = 5,
    ) -> dict:

        exposures_done: asyncio.Future = asyncio.Future()

        electrometer_exposure_coroutine_cbp = self.take_electrometer_scan(
            self.electrometer_cbp,
            exposure_time=electrometer_exposure_time,
            exposures_done=exposures_done,
        )

        electrometer_exposure_coroutine_cbp_cal = self.take_electrometer_scan(
            self.electrometer_cbp_cal,
            exposure_time=electrometer_exposure_time,
            exposures_done=exposures_done,
        )

        laser_burst_coroutine = self.take_bursts(
            delay_before=delay_before,
            delay_after=delay_after,
            wait_time=0,
        )

        try:

            electrometer_exposure_task_cbp = asyncio.create_task(
                electrometer_exposure_coroutine_cbp
            )

            electrometer_exposure_task_cbp_cal = asyncio.create_task(
                electrometer_exposure_coroutine_cbp_cal
            )

            laser_burst_task = asyncio.create_task(laser_burst_coroutine)

        finally:
            await asyncio.gather(
                laser_burst_task,
                electrometer_exposure_task_cbp,
                electrometer_exposure_task_cbp_cal,
            )

    async def take_electrometer_scan(
        self,
        electrometer,
        exposure_time: float | None,
        exposures_done: asyncio.Future,
    ) -> list[str]:
        """Perform an electrometer scan for the specified duration.

        Parameters
        ----------
        exposure_time : `float`
            Exposure time for the fiber spectrum (seconds).
        exposures_done : `asyncio.Future`
            A future indicating when the camera exposures where complete.

        Returns
        -------
        electrometer_exposures : `list`[`str`]
            List of large file urls.
        """

        electrometer.evt_largeFileObjectAvailable.flush()

        electrometer_exposures = list()

        if exposure_time is not None:

            try:
                await electrometer.cmd_startScanDt.set_start(
                    scanDuration=exposure_time,
                    timeout=exposure_time + self.long_timeout,
                )
            except salobj.AckTimeoutError:
                self.log.exception("Timed out waiting for the command ack. Continuing.")

            # Make sure that a new lfo was created
            try:
                lfo = await electrometer.evt_largeFileObjectAvailable.next(
                    timeout=self.long_timeout, flush=False
                )
                electrometer_exposures.append(lfo.url)
            except asyncio.TimeoutError:
                # TODO (DM-44634): Remove this work around to electrometer
                # going to FAULT when issue is resolved.
                self.log.warning(
                    "Time out waiting for electrometer data. Making sure electrometer "
                    "is in enabled state and continuing."
                )
                await salobj.set_summary_state(electrometer, salobj.State.ENABLED)
                await self.setup_electrometer(
                    electrometer,
                    self.config.electrometer_mode,
                    self.config.electrometer_range,
                    self.config.electrometer_integration_time,
                )
        return electrometer_exposures

    async def take_calibration_sequence(self):
        """Take the CBP calibration sequence."""

        calibration_summary = {"steps": []}

        if self.config.set_wavelength_range:
            wavelength = float(self.config.wavelength)
            wavelength_width = float(self.config.wavelength_width)
            wavelength_resolution = float(self.config.wavelength_resolution)
            wavelength_start = wavelength - wavelength_width / 2.0
            wavelength_end = wavelength + wavelength_width / 2.0

            calibration_wavelengths = np.arange(
                wavelength_start, wavelength_end, wavelength_resolution
            )
        else:
            calibration_wavelengths = self.config.wavelength_list

        exposure_table = await self._calculate_electrometer_exposure_times(
            wavelengths=calibration_wavelengths,
        )

        self.log.info(f"Raw exposure table: {exposure_table}")

        shuffled_exposure_table = exposure_table.sample(frac=1).reset_index(drop=True)

        self.log.info(f"Order to take data in: {shuffled_exposure_table}")

        for i, exposure in shuffled_exposure_table.iterrows():
            self.log.debug(f"exposure is {exposure}")
            self.log.debug(f"Changing wavelength to {exposure.wavelength=}.")
            await self.change_laser_wavelength(wavelength=exposure.wavelength)
            await self.tunablelaser.cmd_setBurstMode.set_start(
                count=int(exposure.npulses)
            )

            self.log.info(
                f"Taking data sequence with wavelength {exposure.wavelength=} nm."
            )
            await self._take_data(
                electrometer_exposure_time=exposure.exposure_time,
                delay_before=exposure.delay_before,
                delay_after=exposure.delay_after,
            )
            step = dict(
                wavelength=exposure.wavelength,
            )

            calibration_summary["steps"].append(step)
        self.log.info(f"Calibration summary is {calibration_summary}")

    async def run_block(self):
        """Run the block of tasks to take CBP calibration sequence."""

        await self.start_system()
        await self.setup_calibration()
        await self.take_calibration_sequence()
