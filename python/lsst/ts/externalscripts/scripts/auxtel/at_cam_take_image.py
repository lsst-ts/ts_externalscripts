#!/usr/bin/env python

__all__ = ["ATCamTakeImage"]

import collections

from lsst.ts.scriptqueue.base_script import BaseScript
from lsst.ts import salobj

import SALPY_ATCamera


class ATCamTakeImage(BaseScript):
    """ Take a series of images with the ATCamera with set exposure times.
    """

    def __init__(self, index, descr=""):
        super().__init__(index=index, descr=descr,
                         remotes_dict={'atcamera': salobj.Remote(SALPY_ATCamera)})

        self.imageSequenceName = ''
        self.nimages = 1
        self.exp_times = 0.
        self.max_exptime = 5.
        self.min_exptime = 0.
        self.shutter = False

        self.read_out_time = 2.  # the readout time
        self.shutter_time = 1.  # time required to open/close the shutter
        self.cmd_timeout = 45.  # this timeout is large because of an issue with one of the components.

    async def configure(self, nimages=1, exp_times=0., shutter=False, image_sequence_name=''):
        """Configure script.

        Parameters
        ----------
        nimages : int
            Number of images to be taken on the stress test (>0).
        exp_times : float or list(float)
            Exposure times (in seconds) for the image sequence. Either a single float (same
            exposure time for all images) or a list with the exposure times of each image. If
            exp_times is a list, nimages is ignored (>= 0.).
        shutter : bool
            open shutter?
        image_sequence_name : str
            Image id.

        Raises
        ------
        IOError if input parameters outside valid ranges.
        """
        self.log.info("Configure started")

        self.nimages = nimages
        if self.nimages < 1:
            raise IOError(f"nimages={self.nimages} must be > 0")

        # make exposure time a list with size = nimages, if it is not
        self.exp_times = exp_times

        if not isinstance(self.exp_times, collections.Iterable):
            self.exp_times = [exp_times]*self.nimages

        for etime in self.exp_times:
            if etime < 0.:
                raise IOError(f"exptime={etime} must be >= 0")

        # Fix size of nimages in case exp_times had different size
        self.nimages = len(self.exp_times)

        self.shutter = bool(shutter)

        self.imageSequenceName = str(image_sequence_name)

        self.log.info(f"nimages={self.nimages}, "
                      f"exposure times={self.exp_times}, "
                      f"shutter={self.shutter}"
                      f"image_name={self.imageSequenceName}"
                      )

        self.log.info("Configure completed")

    def set_metadata(self, metadata):
        mean_exptime = (self.max_exptime+self.min_exptime)/2.
        metadata.duration = (mean_exptime + self.read_out_time +
                             self.shutter_time*2. if self.shutter else 0.) * self.nimages

    async def run(self):

        # await self.checkpoint("start")

        for i in range(self.nimages):
            exposure = self.exp_times[i]

            take_image_topic = self.atcamera.cmd_takeImages.DataType()
            take_image_topic.numImages = 1
            take_image_topic.expTime = exposure
            take_image_topic.shutter = self.shutter
            take_image_topic.imageSequenceName = str(self.imageSequenceName)

            end_readout_coro = self.atcamera.evt_endReadout.next(flush=True,
                                                                 timeout=self.read_out_time+self.cmd_timeout)

            # await self.checkpoint(f"Take image {i+1} of {self.nimages}")

            await self.atcamera.cmd_takeImages.start(take_image_topic,
                                                     timeout=exposure+self.cmd_timeout)
            await end_readout_coro

        # await self.checkpoint("end")


if __name__ == '__main__':
    ATCamTakeImage.main(descr="Take sequence of images with ATCam.")
