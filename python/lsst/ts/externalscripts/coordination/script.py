__all__ = ["LaserCoordination"]

import SALPY_LinearStage
import SALPY_Electrometer
import SALPY_TunableLaser
from lsst.ts import scriptqueue
from lsst.ts import salobj
import os
import asyncio
import logging
import datetime

log_file = logging.FileHandler("/home/saluser/develop/script.log")
log_file.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
log_file.setLevel(logging.DEBUG)
logging.getLogger().addHandler(log_file)


class LaserCoordination(scriptqueue.BaseScript):
    """ES-Coordination-Laser-001: Laser coordination

    A SAL script that is used for testing two lab LinearStages, the TunableLaser and an Electrometer.
    It propagates the laser at a wavelength while the two linear stages move in a grid pattern in a given
    step increment. At each step, an electrometer will take a reading. The data will then be pushed into
    a csv file and then plotted as coordinate vs. electrometer reading.

    Parameters
    ----------
    index : `int`
        The SAL index of the script.
    descr : `str`
        A description of the script.

    Attributes
    ----------
    wanted_remotes : `list`
    wavelengths : `range`
    steps : `int`
    linear_stage_set : `bool`
    linear_stage_2_set : `bool`
    electrometer_set : `bool`
    tunable_laser_set : `bool`
    scan_duration : `int`
    timeout : `int`

    """
    def __init__(self, index, descr=""):
        super().__init__(index, descr="A laser coordination script", remotes_dict={
            'linear_stage_1': salobj.Remote(SALPY_LinearStage, 1),
            'linear_stage_2': salobj.Remote(SALPY_LinearStage, 2),
            'electrometer': salobj.Remote(SALPY_Electrometer, 1),
            'tunable_laser': salobj.Remote(SALPY_TunableLaser)
        })
        self.wanted_remotes = None
        self.wavelengths = None
        self.steps = None
        self.integration_time = None
        self.max_linear_stage_position = None
        self.linear_stage_set = False
        self.linear_stage_2_set = False
        self.electrometer_set = False
        self.tunable_laser_set = False
        self.scan_duration = None
        self.timeout = None
        self.stablization = False
        self.number_of_scans = None

        self.log.setLevel(10)
        self.put_log_level()
        self.log.debug("END INIT")

    def set_metadata(self, metadata):
        metadata = {'remotes_set': [self.linear_stage_set,
                    self.linear_stage_2_set, self.electrometer_set, self.tunable_laser_set], 'time': 'NaN'}
        return metadata

    async def run(self):

        async def setup_electrometers():
            self.electrometer.cmd_setMode.set(mode=1)
            self.electrometer.cmd_setIntegrationTime.set(intTime=self.integration_time)
            set_electrometer_mode_ack_coro = await self.electrometer.cmd_setMode.start(timeout=self.timeout)
            set_electrometer_integration_time_ack_coro = await self.electrometer.cmd_setIntegrationTime.start(
                timeout=self.timeout)
        setup_tasks = []
        if not self.tunable_laser_set and not self.stablization:
            self.wavelengths = [525, ]
        if self.stablization:
            self.wavelengths = range(0, self.number_of_scans)
            self.linear_stage_set = False
            self.linear_stage_2_set = False
            self.tunable_laser_set = False
            self.electrometer_set = True
            self.scan_duration = 2

        if not self.linear_stage_set:
            self.max_linear_stage_position = 2
            self.steps = 1
        if not self.linear_stage_2_set:
            self.max_linear_stage_position = 2
            self.steps = 1
        if self.tunable_laser_set:
            propagate_state_ack = self.tunable_laser.cmd_startPropagateLaser.start(timeout=self.timeout)
            setup_tasks.append(propagate_state_ack)
        if self.electrometer_set:
            setup_electrometer_ack_coro = setup_electrometers()
            setup_tasks.append(setup_electrometer_ack_coro)
        try:
            data_array = []
            self.log.debug(f"Setting up Script")
            setup_ack = await asyncio.gather(*setup_tasks)
            await self.checkpoint(f"setup complete")
            self.log.debug(f"Finished setting up script")
            for wavelength in self.wavelengths:
                for ls_pos in range(1, self.max_linear_stage_position, self.steps):
                    if self.linear_stage_set:
                        self.linear_stage_1.cmd_moveAbsolute.set(distance=ls_pos)
                        self.log.debug("Moving linear stage 1")
                        move_ls1_ack = await self.linear_stage_1.cmd_moveAbsolute.start(timeout=self.timeout)
                    await self.checkpoint(f"ls 1 pos: {ls_pos}")
                    for ls_2_pos in range(1, self.max_linear_stage_position, self.steps):
                        if self.linear_stage_2_set:
                            self.linear_stage_2.cmd_moveAbsolute.set(distance=ls_2_pos)
                            self.log.debug("moving linear stage 2")
                            move_ls2_ack = await self.linear_stage_2.cmd_moveAbsolute.start(
                                timeout=self.timeout)
                        elif not self.linear_stage_2_set and self.stablization:
                            await asyncio.sleep(10)
                        await self.checkpoint(f"ls 1 pos {ls_pos} ls 2 pos: {ls_2_pos}")
                        if self.electrometer_set:
                            electrometer_data_coro = self.electrometer.evt_largeFileObjectAvailable.next(
                                flush=True, timeout=self.timeout)
                            self.electrometer.cmd_startScanDt.set(scanDuration=self.scan_duration)
                            electrometer_scan_ack = await self.electrometer.cmd_startScanDt.start(
                                timeout=self.timeout)
                            electrometer_data = await electrometer_data_coro
                            await self.checkpoint(f"ls 1 pos {ls_pos} ls 2 pos {ls_2_pos} electr. data")
                            data_array.append([
                                datetime.datetime.now(),
                                wavelength,
                                ls_pos,
                                ls_2_pos,
                                electrometer_data.url])
            if self.tunable_laser_set:
                self.tunable_laser.cmd_stopPropagateLaser.set()
                stop_propagate_ack = await self.tunable_laser.cmd_stopPropagateLaser.start(
                    timeout=self.timeout)
                await self.checkpoint(f"Laser stopped propagating")
            with open(f"{self.file_location}laser_coordination.txt", "w") as f:
                f.write("timestamp wavelength ls_pos ls_2_pos electrometer_data_url\n")
                for line in data_array:
                    f.write(f"{line[0]} {line[1]}, {line[2]}, {line[3]}, {line[4]}\n")
        except Exception as e:
            print(e)
            raise

    async def configure(self,
                        wanted_remotes,
                        wavelengths,
                        file_location="~",
                        steps=5,
                        max_linear_stage_position=75,
                        integration_time=0.2,
                        scan_duration=10,
                        timeout=20,
                        stablization=False,
                        number_of_scans=1440):
        """Configures the script.

        Parameters
        ----------
        wanted_remotes : `list` of `str`
            A list of remotes_names that should be used for running the script.

            full list:

            * 'linear_stage_1_remote'
            * 'linear_stage_2_remote'
            * 'electrometer_remote'
            * 'tunable_laser_remote'

        wavelengths : `range`
            A range of wavelengths to iterate through. Units: Nanometers
        file_location
        steps : `int` (the default is 5 mm)
            The amount of mm to move the linear stages by.
        max_linear_stage_position : `int`
            Units: millimeters
        integration_time : `int`
            Units: seconds
        scan_duration : `float`
            Units: seconds
        timeout : `int`
            Units: seconds
        """
        try:
            self.log.debug("START CONFIG")
            self.wanted_remotes = wanted_remotes
            self.wavelengths = range(wavelengths[0], wavelengths[1])
            self.file_location = os.path.expanduser(file_location)
            self.steps = steps
            self.max_linear_stage_position = max_linear_stage_position
            self.integration_time = integration_time
            self.scan_duration = scan_duration
            self.timeout = timeout
            if 'linear_stage_1_remote' in self.wanted_remotes:
                self.linear_stage_set = True
            if 'linear_stage_2_remote' in self.wanted_remotes:
                self.linear_stage_2_set = True
            if 'electrometer_remote' in self.wanted_remotes:
                self.electrometer_set = True
            if 'tunable_laser_remote' in self.wanted_remotes:
                self.tunable_laser_set = True
            self.stablization = stablization
            self.number_of_scans = number_of_scans
            self.log.debug("END CONFIG")
        except Exception as e:
            self.log.exception(e)
            raise
