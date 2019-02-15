import numpy as np
import pandas as pd
from lsst.ts import scriptqueue
from lsst.ts.salobj import Remote
import SALPY_Electrometer
import SALPY_TunableLaser

class LaserCharacterization(scriptqueue.BaseScript):
    def __init__(self,index):
        super().__init__(index=index,descr="Laser Characterizationscript",remotes_dict={'electrometer': Remote(SALPY_Electrometer,1), 'tunable_laser': Remote(SALPY_TunableLaser),'electrometer_2': Remote(SALPY_Electrometer,2)})

    def configure(self,wavelengths,exposure_time,mode):
        self.wavelengths = range(wavelengths[0],wavelengths[1])
        self.exposure_time = exposure_time
        self.mode = 1

    def metadata(self,struct):
        return {}

    async def run(self):
        # propagate_laser
            # set wavelength in loop
            # Read electrometer
        # save CSV file
        # Stop propagation of laser
        wavelength_list = []
        electrometer_data_links = []
        set_mode = getattr(self.electrometer,"cmd_setMode").DataType()
        set_mode.mode = self.mode
        set_mode_ack = getattr(self.electrometer,"cmd_setMode").start(set_mode, timeout=10)
        if set_mode_ack.ack.ack is not 303:
            raise ValueError("Script does not know what to do")
        start_propagation = getattr(self.tunable_laser,"cmd_startPropagateLaser").DataType()
        start_propagation_ack = await getattr(self.tunable_laser,"cmd_startPropagateLaser").start(start_propagation,timeout=10)
        if start_propagation_ack is not 303:
            raise ValueError("Script does not know what to do")
        for wavelength in self.wavelengths:
            change_wavelength = getattr(self.tunable_laser,"cmd_changeWavelength").DataType()
            change_wavelength_ack = await getattr(self.tunable_laser,"cmd_changeWavelength").start(change_wavelength,timeout=10)
            if change_wavelength_ack.ack.ack is not 303:
                raise ValueError("Script does not know what to do")
            start_scan_dt = getattr(self.electrometer,"cmd_startScanDt").DataType()
            start_scan_dt.scanDuration = self.exposure_time
            start_scan_dt_ack = await getattr(self.electrometer,"cmd_startScanDt").start(start_scan_dt,timeout=10)
            if start_scan_dt_ack.ack.ack is not 303:
                raise ValueError("Script does not know what to do")
           electrometer_scan_data = await getattr(self.electrometer,"evt_largeFileObjectAvailable").next(flush=False,timeout=10)
           wavelength_list.append(wavelength)
           electrometer_data_links.append(electrometer_scan_data.url)
        df = pd.DataFrame({'wavelength': wavelength_list, 'electrometer_data_link': electrometer_data_links})
        df.to_csv(path_or_buf="script_data_to_plot.csv",index=False)
        stop_propagate = getattr(self.tunable_laser,"cmd_stopPropagateLaser").DataType()
        stop_propagate_ack = await getattr(self.tunable_laser,"cmd_stopPropagateLaser").start(stop_propagate,timeout=10)
        if stop_propagate_ack.ack.ack is not 303:
            raise ValueError("Script does not know what to do at this point")
