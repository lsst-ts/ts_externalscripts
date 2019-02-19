___all__ = ["LaserCoordination"]
"""Contains the coordination scripts.
"""

import SALPY_LinearStage
import SALPY_Electrometer
import SALPY_TunableLaser
from lsst.ts import scriptqueue
from lsst.ts import salobj
import numpy as np


class LaserCoordination(scriptqueue.BaseScript):
    """ES-Coordination-Laser-001: Laser coordination 

    A SAL script that is used for testing two lab LinearStages, the TunableLaser and an Electrometer.
    It propagates the laser at a wavelength while the two linear stages move in a grid pattern in a given
    step increment. At each step, an electrometer will take a reading. The data will then be pushed into
    a csv file and then plotted as coordinate vs. electrometer reading.

    Parameters
    ----------
    index: `int`
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
        self.integration_duration = None
        self.max_linear_stage_position = None
        self.linear_stage_set = False
        self.linear_stage_2_set = lFsalse
        self.electrometer_set = False
        self.tunable_laser_set = False

        self.log.setLevel(10)
        self.put_log_level()

    def set_metadata(self, metadata):
        metadata = {'remotes_set': [self.linear_stage_set,
                    self.linear_stage_2_set, self.electrometer_set, self.tunable_laser_set], 'time': 'NaN'}
        return metadata

    async def run(self):
        
        if not self.tunable_laser_set:
            self.wavelengths = [525, ]
        data_array = []
        set_electrometer_mode_topic = self.electrometer.cmd_setMode.DataType()
        set_electrometer_mode_topic.mode = 1
        set_electrometer_mode_ack = await self.electrometer.cmd_setMode.start(set_electrometer_mode_topic,timeout=10)
        set_electrometer_integration_time = self.electrometer.cmd_setIntegrationTime.DataType()
        set_electrometer_integration_time.intTime = self.integration_duration
        set_electrometer_integration_time_ack = await self.electrometer.cmd_setIntegrationTime.start(set_electrometer_integration_time,timeout=10)
        for wavelength in self.wavelengths:
            for ls_pos in range(1, self.max_linear_stage_position, self.steps):
                move_ls1_topic = self.linear_stage_1.cmd_moveAbsolute.DataType()
                move_ls1_topic.distance = ls_pos
                move_ls1_ack = await self.linear_stage_1.cmd_moveAbsolute.start(move_ls1_topic, timeout=10)
                
                for ls_2_pos in range(1, self.max_linear_stage_position, self.steps):
                    move_ls2_topic = self.linear_stage_2.cmd_moveAbsolute.DataType()
                    move_ls2_topic.distance = ls_2_pos
                    move_ls2_ack = await self.linear_stage_2.cmd_moveAbsolute.start(move_ls2_topic,
                                                                                    timeout=10)
                    if self.electrometer_set:
                        electrometer_data_coro = self.electrometer.evt_largeFileObjectAvailable.next(flush=True,timeout=10)
                        electrometer_scan_topic = self.electrometer.cmd_startScanDt.DataType()
                        electrometer_scan_topic.scanDuration = 1
                        electrometer_scan_ack = await self.electrometer.cmd_startScanDt.start(
                            electrometer_scan_topic, timeout=10)
                        electrometer_data = await electrometer_data_coro
                        data_array.append([wavelength, ls_pos, ls_2_pos, electrometer_data.url])
        with open(f"{self.file_location}/laser_coordination.txt","w") as f:
            f.write("wavelength ls_pos ls_2_pos electrometer_data_url")
            for line in data_array:
                f.write(line)

    async def configure(self, 
                        wanted_remotes,
                        wavelengths,
                        file_location="~",
                        steps=5,
                        max_linear_stage_position=75,
                        integration_duration=0.2):
        """Configures the script.

        Parameters
        ----------
        wanted_remotes: list
            A list of remotes_names that should be used for running the script.
            
            full list:

            * 'linear_stage_1_remote' 
            * 'linear_stage_2_remote' 
            * 'electrometer_remote'
            * 'tunable_laser_remote'

        wavelengths: range
            A range of wavelengths to iterate through.
        steps: int (the default is 5 mm)
            The amount of mm to move the linear stages by.
        """
        self.wanted_remotes = wanted_remotes
        self.wavelengths = range(wavelengths[0], wavelengths[1])
        self.file_location = file_location
        self.steps = steps
        self.max_linear_stage_position = max_linear_stage_position
        self.integration_duration = integration_duration
        if 'linear_stage_1_remote' in self.wanted_remotes:
            self.linear_stage_set = True
        if 'linear_stage_2_remote' in self.wanted_remotes:
            self.linear_stage_2_set = True
        if 'electrometer_remote' in self.wanted_remotes:
            self.electrometer_set = True
        if 'tunable_laser_remote' in self.wanted_remotes:
            self.tunable_laser_set = True
