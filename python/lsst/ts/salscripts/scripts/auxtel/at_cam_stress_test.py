#!/usr/bin/env python

__all__ = ["TakeImageStressTest"]

from scriptloader import BaseScript
import salobj
import warnings
try:
    import SALPY_atcamera
except ModuleNotFoundError:
    warnings.warn("Could not load SALPY_atcamera, wont be able to run TakeImageStressTest locally.")
import numpy as np


class TakeImageStressTest(BaseScript):
    """ Take a series of images with the ATCamera with random exposure times.
    """

    def __init__(self, index, descr=""):
        super().__init__(index=index, descr=descr,
                         remotes_dict={'atcamera': salobj.Remote(SALPY_atcamera)})

        self.imageSequenceName = ''
        self.nimages = 1
        self.min_exptime = 1.
        self.max_exptime = 5.
        self.shutter = False

        self.read_out_time = 2.  # the readout time
        self.shutter_time = 1.  # time required to open/close the shutter

    def configure(self, nimages=1, min_exptime=1., max_exptime=5., shutter=False, image_name=''):
        """Configure script.

        Parameters
        ----------
        nimages : Number of images to be taken on the stress test.
        min_exptime : Minimum exposure time (in seconds) to be used for the random algorithm
        max_exptime : Maximum exposure time (in seconds) to be used for the random algorithm
        shutter : Boolean, open shutter?

        Raises
        ------
        salobj.ExpectedError
            If ``nimages < 1`` or ``min_exptime >= max_exptime`` or ``min_exptime/max_exptime < 0``.
        """
        self.log.info("Configure started")

        self.nimages = nimages
        if self.nimages < 1:
            raise salobj.ExpectedError(f"nimages={self.nimages} must be > 0")

        self.min_exptime = min_exptime
        if self.min_exptime < 0:
            raise salobj.ExpectedError(f"min_exptime={self.min_exptime} must be >= 0")

        self.max_exptime = max_exptime
        if self.max_exptime < 0:
            raise salobj.ExpectedError(f"max_exptime={self.max_exptime} must be >= 0")

        if self.max_exptime <= self.min_exptime:
            raise salobj.ExpectedError(f"min_exptime={self.min_exptime}, max_exptime={self.max_exptime}. "
                                       f"max_exptime must be larger than min_exptime.")

        self.shutter = bool(shutter)

        self.imageSequenceName = str(image_name)

        self.log.info(f"nimages={self.nimages}, "
                      f"min_exptime={self.min_exptime}, "
                      f"max_exptime={self.max_exptime}, "
                      f"shutter={self.shutter}"
                      f"image_name={self.imageSequenceName}"
                      )
        self.log.info("Configure succeeded")

    def set_metadata(self, metadata):
        mean_exptime = (self.max_exptime+self.min_exptime)/2.
        metadata.duration = (mean_exptime + self.read_out_time +
                             self.shutter_time*2. if self.shutter else 0.) * self.nimages

    async def run(self):

        await self.checkpoint("start")

        for i in range(self.nimages):
            exposure = self.min_exptime + np.random.random() * self.max_exptime

            take_image_topic = self.atcamera.cmd_takeImages.DataType()
            take_image_topic.numImages = 1
            take_image_topic.expTime = exposure
            take_image_topic.shutter = self.shutter
            take_image_topic.imageSequenceName = str(self.imageSequenceName)

            end_readout_coro = self.atcamera.evt_endReadout.next(timeout=self.read_out_time*2.)

            await self.checkpoint(f"Take image {i+1} of {self.nimages}")

            take_image = await self.atcamera.cmd_takeImages.start(take_image_topic, timeout=exposure+30.)

            if take_image.ack.ack == self.atcamera.salinfo.lib.SAL__CMD_COMPLETE:
                end_readout = await end_readout_coro
                self.log.info("Image %i of %i: %s", i+1, self.nimages, end_readout.imageName)
            else:
                self.log.error("Take Image command failed with %i %i %s",
                               take_image.ack.ack,
                               take_image.ack.error,
                               take_image.ack.result)
                break

        await self.checkpoint("end")


if __name__ == '__main__':
    TakeImageStressTest.main(descr="Make a stress test of the atcamera.")
