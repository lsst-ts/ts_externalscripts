__all__ = ["ATCamTakeImage"]

import collections

import numpy as np

from lsst.ts.scriptqueue.base_script import BaseScript
from lsst.ts import salobj

import SALPY_ATCamera


class ATCamTakeImage(BaseScript):
    """ Take a series of images with the ATCamera with set exposure times.

    Parameters
    ----------
    index : `int`
        SAL index of this Script

    Notes
    -----
    **Checkpoints**

    * exposure {n} of {m}: before sending the ATCamera ``takeImages`` command
    """
    def __init__(self, index):
        super().__init__(index=index, descr="Test ATCamTakeImage",
                         remotes_dict=dict(atcamera=salobj.Remote(SALPY_ATCamera)))

        self.readout_time = 2  # readout time (sec)
        self.shutter_time = 1  # time to open or close shutter (sec)
        self.cmd_timeout = 45  # command timeout (sec)
        # large because of an issue with one of the components

    async def configure(self, nimages=1, exp_times=0., shutter=False, image_sequence_name=''):
        """Configure script.

        Parameters
        ----------
        nimages : `int`
            Number of images to be taken on the stress test (>0).
            Ignored if ``exp_times`` is a sequence.
        exp_times : `float` or `List` [ `float` ]
            Exposure times (in seconds) for the image sequence.
            Either a single float (same exposure time for all images)
            or a list with the exposure times of each image.
            If exp_times is a list, nimages is ignored (>= 0.).
        shutter : `bool`
            Open the shutter?
        image_sequence_name : `str`
            Image id.

        Raises
        ------
        ValueError
            If input parameters outside valid ranges.
        """
        self.log.info("Configure started")

        # make exposure time a list with size = nimages, if it is not
        if isinstance(exp_times, collections.Iterable):
            if len(exp_times) == 0:
                raise ValueError(f"exp_times={exp_times}; must provide at least one value")
            self.exp_times = [float(t) for t in exp_times]
        else:
            if nimages < 1:
                raise ValueError(f"nimages={nimages} must be > 0")
            self.exp_times = [float(exp_times)]*nimages

        if np.min(self.exp_times) < 0:
            raise ValueError(f"Exposure times {exp_times} must be >= 0")

        self.shutter = bool(shutter)
        self.imageSequenceName = str(image_sequence_name)

        self.log.info(f"exposure times={self.exp_times}, "
                      f"shutter={self.shutter}, "
                      f"image_name={self.imageSequenceName}")

    def set_metadata(self, metadata):
        nimages = len(self.exp_times)
        mean_exptime = np.mean(self.exp_times)
        metadata.duration = (mean_exptime + self.readout_time +
                             self.shutter_time*2 if self.shutter else 0) * nimages

    async def run(self):
        end_readout_timeout = self.readout_time + self.cmd_timeout
        nimages = len(self.exp_times)
        for i, exposure in enumerate(self.exp_times):
            await self.checkpoint(f"exposure {i+1} of {nimages}")
            self.atcamera.cmd_takeImages.set(numImages=1,
                                             expTime=exposure,
                                             shutter=self.shutter,
                                             imageSequenceName=self.imageSequenceName)
            self.atcamera.evt_endReadout.flush()
            await self.atcamera.cmd_takeImages.start(timeout=exposure+self.cmd_timeout)
            await self.atcamera.evt_endReadout.next(flush=False, timeout=end_readout_timeout)
