import os
import salobj
import SALPY_atcamera
import numpy as np
import datetime
import asyncio
from lsst.ts.salscripts.utils import get_atcamera_filename
import logging

logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s] [%(name)-12s:%(lineno)-4d] [%(levelname)-8s]: %(message)s',
                    datefmt='%m-%d %H:%M:%S')


class TakeImageStressTest:
    def __init__(self):
        self.atcamera = salobj.Remote(SALPY_atcamera, f'atcamera')

    async def takeImageLoop(self, nimages):
        for i in range(nimages):
            exposure = 1. + np.random.random() * 5.
            atcamera_fname = get_atcamera_filename()
            take_image_topic = self.atcamera.cmd_takeImages.DataType()
            take_image_topic.numImages = 1
            take_image_topic.expTime = exposure
            take_image_topic.shutter = False
            take_image_topic.imageSequenceName = str(atcamera_fname)
            take_image_topic.science = True

            end_readout = self.atcamera.evt_endReadout.next(flush=True,
                                                            timeout=exposure + 30.)
            take_image_task = self.atcamera.cmd_takeImages.start(take_image_topic)

            image = await asyncio.gather(end_readout, take_image_task)

            logging.info('[%04i/%04i] %s (%+03i, %04i, %s)',
                         i + 1, nimages,
                         image[0].imageName,
                         image[1].ack,
                         image[1].error,
                         image[1].result)


seq = TakeImageStressTest()

loop = asyncio.get_event_loop()

logging.info('Start')
loop.run_until_complete(seq.takeImageLoop(100))
logging.info('Done')
