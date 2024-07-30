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

__all__ = ["BaseTakePTCFlats"]

import abc
import asyncio
import types

import yaml
from lsst.ts import salobj
from lsst.ts.standardscripts.base_block_script import BaseBlockScript
from lsst.ts.xml.enums.Electrometer import UnitToRead


class BaseTakePTCFlats(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base class for taking PTC flats interleaved with darks."""

    def __init__(
        self, index, descr="Base script for taking PTC flats and darks."
    ) -> None:
        super().__init__(index, descr)

        self.electrometer = None
        self.config = None

        self.instrument_setup_time = 0.0
        self.extra_scan_time = 1.0

        self.long_timeout = 30

    @property
    @abc.abstractmethod
    def camera(self):
        raise NotImplementedError()

    async def configure_camera(self):
        """Abstract method to configure the camera, to be implemented
        in subclasses.
        """
        raise NotImplementedError()

    async def configure_electrometer(self, index):
        """Configure the Electrometer remote object."""
        if self.electrometer is None:
            self.log.debug(f"Configuring remote for Electrometer index: {index}")
            self.electrometer = salobj.Remote(
                self.domain, name="Electrometer", index=index
            )
            await self.electrometer.start_task
        else:
            self.log.debug("Electrometer already configured. Ignoring.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/base_take_ptc_flats.yaml
            title: BaseTakePTCFlats
            description: Configuration schema for BaseTakePTCFlats.
            type: object
            properties:
              flats_exp_times:
                description: >
                  A list of exposure times for the flats (sec). Each provided
                  time will be used to take two exposures sequentially.
                type: array
                items:
                  type: number
                  exclusiveMinimum: 0
                minItems: 2
              interleave_darks:
                description: Darks interleave settings.
                type: object
                properties:
                  dark_exp_times:
                    description: >
                      Exposure time for each dark image (sec)
                      or alist of exposure times.
                    anyOf:
                      - type: number
                        minimum: 0
                      - type: array
                        items:
                          type: number
                          minimum: 0
                        minItems: 1
                  n_darks:
                    description: >
                      Number of dark images to interleave between flat pairs.
                    type: integer
                    minimum: 1
              electrometer_scan:
                description: Electrometer scan settings.
                type: object
                properties:
                  index:
                    description: Electrometer index to configure.
                    type: integer
                    minimum: 1
                  mode:
                    description: >
                      Electrometer measurement mode as a string. Valid options
                      are "CURRENT" and "CHARGE".
                    type: string
                    enum: ["CURRENT", "CHARGE"]
                  range:
                    description:  >
                      Electrometer measurement range. -1 for autorange.
                    type: number
                  integration_time:
                    description: Electrometer integration time.
                    type: number
                    exclusiveMinimum: 0
              ignore:
                description: >-
                    CSCs from the camera group to ignore in status check.
                    Name must match those in self.group.components.
                type: array
                items:
                  type: string

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
        """Configure script components including camera and electrometer.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        await self.configure_camera()

        if hasattr(config, "electrometer_scan"):
            await self.configure_electrometer(config.electrometer_scan["index"])

        if hasattr(config, "ignore"):
            for comp in config.ignore:
                if comp in self.camera.components_attr:
                    self.log.debug(f"Ignoring Camera component {comp}.")
                    setattr(self.camera.check, comp, False)
                else:
                    self.log.warning(
                        f"Component {comp} not in CSC Group. "
                        f"Must be one of {self.camera.components_attr}. "
                        f"Ignoring."
                    )

        # Handle interleave darks settings
        if hasattr(config, "interleave_darks"):

            if isinstance(config.interleave_darks["dark_exp_times"], list):
                self.log.warning(
                    "'n_darks' is ignored because 'dark_exp_times' is an array."
                )
                config.interleave_darks["n_darks"] = len(
                    config.interleave_darks["dark_exp_times"]
                )

            if not isinstance(config.interleave_darks["dark_exp_times"], list):
                config.interleave_darks["dark_exp_times"] = [
                    config.interleave_darks["dark_exp_times"]
                ] * (config.interleave_darks["n_darks"])
            else:
                config.interleave_darks["n_darks"] = len(
                    config.interleave_darks["dark_exp_times"]
                )

        self.config = config

        await super().configure(config)

    @abc.abstractmethod
    def get_instrument_name(self):
        """Abstract method to be defined in subclasses to provide the
        instrument name.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_configuration(self) -> dict:
        """Abstract method to get the instrument configuration.

        Returns
        -------
        dict
            Dictionary with instrument configuration.
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_instrument_filter(self) -> str:
        """Abstract method to get the instrument filter configuration.

        Returns
        -------
        str
            Instrument filter configuration.
        """
        raise NotImplementedError()

    async def setup_electrometer(
        self, mode: str, range: float, integration_time: float
    ) -> None:
        """Setup the Electrometer with specified mode, range,
        and integration time.

        Parameters
        ----------
        mode : `str`
            Electrometer measurement mode.
        range : `float`
            Electrometer measurement range. -1 for autorange.
        integration_time : `float`
            Electrometer integration time.
        """
        assert self.electrometer is not None, "Electrometer is not configured."

        electrometer_mode = getattr(UnitToRead, mode).value

        await self.electrometer.cmd_setMode.set_start(
            mode=electrometer_mode,
            timeout=self.long_timeout,
        )
        await self.electrometer.cmd_setRange.set_start(
            setRange=range,
            timeout=self.long_timeout,
        )
        await self.electrometer.cmd_setIntegrationTime.set_start(
            intTime=integration_time,
            timeout=self.long_timeout,
        )
        await self.electrometer.cmd_performZeroCalib.start(timeout=self.long_timeout)
        await self.electrometer.cmd_setDigitalFilter.set_start(
            activateFilter=False,
            activateAvgFilter=False,
            activateMedFilter=False,
            timeout=self.long_timeout,
        )

    def set_metadata(self, metadata: salobj.BaseMsgType) -> None:
        """Set script metadata, including estimated duration."""

        flats_exp_times = self.config.flats_exp_times
        n_flats = len(flats_exp_times)
        n_flat_pairs = n_flats // 2  # Each flat exptime is provided in pairs

        # Initialize total_dark_exptime and total_flat_exptime
        total_dark_exptime = 0
        total_flat_exptime = sum(flats_exp_times)

        # Include electrometer scan overhead if configured
        if hasattr(self.config, "electrometer_scan"):
            total_flat_exptime += n_flat_pairs  # 1 second overhead per pair

        # Calculate dark exposure time if interleaving darks
        if hasattr(self.config, "interleave_darks"):
            dark_exp_times = self.config.interleave_darks["dark_exp_times"]
            n_darks = (
                n_flat_pairs * len(dark_exp_times) * 2
            )  # Two sets of darks per pair of flats
            total_dark_exptime = sum(dark_exp_times) * n_flat_pairs * 2
        else:
            n_darks = 0  # No darks if not interleaving

        # Setup time for the camera (readout and shutter time)
        setup_time_per_image = self.camera.read_out_time + self.camera.shutter_time

        # Total duration calculation
        total_duration = (
            self.instrument_setup_time  # Initial setup time for the instrument
            + total_flat_exptime  # Time for taking all flats
            + total_dark_exptime  # Time for taking all darks
            + setup_time_per_image * (n_flats + n_darks)  # Setup time p/image
        )

        metadata.duration = total_duration
        metadata.instrument = self.get_instrument_name()
        metadata.filter = self.get_instrument_filter()

    async def take_electrometer_scan(self, exposure_time: float | None) -> list[str]:
        """Perform an electrometer scan for the specified duration.

        Parameters
        ----------
        exposure_time : `float` | None
            Exposure time for the electrometer scan (seconds).

        Returns
        -------
        electrometer_exposures : `list`[`str`]
            List of large file URLs indicating where the electrometer
            data is stored.
        """
        self.electrometer.evt_largeFileObjectAvailable.flush()

        electrometer_exposures = []

        if exposure_time is not None:
            try:
                await self.electrometer.cmd_startScanDt.set_start(
                    scanDuration=exposure_time,
                    timeout=exposure_time + self.long_timeout,
                )
            except salobj.AckTimeoutError:
                self.log.exception(
                    "Timed out waiting for the command acknowledgment. Continuing."
                )

            # Ensure a new large file object (LFO) was created
            try:
                lfo = await self.electrometer.evt_largeFileObjectAvailable.next(
                    timeout=exposure_time + self.long_timeout, flush=False
                )
                electrometer_exposures.append(lfo.url)

                # Log the name or URL of the electrometer file
                self.log.info(f"Electrometer scan file created: {lfo.url}")

            except asyncio.TimeoutError:
                raise RuntimeError("Electrometer is not configured.")

        return electrometer_exposures

    async def take_ptc_flats(self):
        if hasattr(self.config, "electrometer_scan"):
            self.log.info(
                f"Setting up electrometer with mode: "
                f"{self.config.electrometer_scan['mode']}, range: "
                f"{self.config.electrometer_scan['range']} and "
                f"integration_time: "
                f"{self.config.electrometer_scan['integration_time']}."
            )
            await self.setup_electrometer(
                mode=self.config.electrometer_scan["mode"],
                range=self.config.electrometer_scan["range"],
                integration_time=self.config.electrometer_scan["integration_time"],
            )

        # Setup instrument filter
        try:
            await self.camera.setup_instrument(filter=self.get_instrument_filter())
        except salobj.AckError:
            self.log.warning(
                f"Filter is already set to {self.get_instrument_filter()}. "
                f"Continuing."
            )

        group_id = self.group_id if self.obs_id is None else self.obs_id

        for i, exp_time in enumerate(self.config.flats_exp_times):
            exp_time_pair = [exp_time, exp_time]

            await self.checkpoint(
                f"Taking pair {i + 1} of {len(self.config.flats_exp_times)}."
            )
            for j, time in enumerate(exp_time_pair):
                if hasattr(self.config, "electrometer_scan"):
                    self.log.info(
                        f"Taking flat {j+1}/2 with exposure time: {time} "
                        f"seconds and scanning electrometer for "
                        f"{time + self.extra_scan_time} seconds."
                    )

                    electrometer_task = self.take_electrometer_scan(
                        time + self.extra_scan_time
                    )

                    flat_task = self.camera.take_flats(
                        exptime=time,
                        nflats=1,
                        group_id=group_id,
                        program=self.program,
                        reason=self.reason,
                    )

                    await asyncio.gather(electrometer_task, flat_task)

                else:
                    self.log.info(
                        f"Taking flat {j+1}/2 with exposure time: {time} seconds."
                    )
                    await self.camera.take_flats(
                        exptime=time,
                        nflats=1,
                        group_id=group_id,
                        program=self.program,
                        reason=self.reason,
                    )

                if hasattr(self.config, "interleave_darks"):
                    for k, dark_exp_time in enumerate(
                        self.config.interleave_darks["dark_exp_times"]
                    ):
                        self.log.info(
                            f"Taking dark {k+1}/{len(self.config.interleave_darks['dark_exp_times'])} "
                            f"for pair {i + 1} of {len(self.config.flats_exp_times)}."
                        )
                        await self.camera.take_darks(
                            exptime=dark_exp_time,
                            ndarks=1,
                            group_id=group_id,
                            program=self.program,
                            reason=self.reason,
                        )

    async def assert_feasibility(self) -> None:
        """Verify that camera is in a feasible state to
        execute the script.
        """
        await self.camera.assert_all_enabled()

    async def run_block(self):
        """Run the block of tasks to take PTC flats sequence."""

        await self.assert_feasibility()
        await self.take_ptc_flats()
