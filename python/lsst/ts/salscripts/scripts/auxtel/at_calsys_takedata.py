#!/usr/bin/env python

import asyncio

from lsst.ts.scriptqueue.base_script import BaseScript
from lsst.ts.salobj import Remote

import SALPY_Electrometer
import SALPY_ATMonochromator
import SALPY_FiberSpectrograph

__all__ = ["ATCalSysTakeData"]


class ATCalSysTakeData(BaseScript):
    """
    """

    def __init__(self, index, descr=""):
        super().__init__(index=index, descr=descr,
                         remotes_dict={'electrometer': Remote(SALPY_Electrometer, 1),
                                       'monochromator': Remote(SALPY_ATMonochromator),
                                       'fiber_spectrograph': Remote(SALPY_FiberSpectrograph)})
        self.cmd_timeout = 10.

        self.wavelength = 0.
        self.integrationTime = 0.
        self.gratingType = 1
        self.fontEntranceSlitWidth = 4
        self.fontExitSlitWidth = 2
        self.imageType = 'TEST'
        self.lamp = 'lamp'
        self.spectrometer_delay = 1.

    async def configure(self, wavelength, integrationTime,
                        gratingType=1,
                        fontExitSlitWidth=4.,
                        fontEntranceSlitWidth=2.,
                        imageType='test',
                        lamp='lamp',
                        spectrometer_delay=1.
                        ):
        """Configure script.

        Values can be passes as iterables or single values. At the end, a consistency check runs and
        performs a size check against wavelength and integrationsTime. All items with size = 1 will
        be expanded to match the size of wavelength and integrationTime. If len(wavelength) > 1 and
        len(integrationTime) == 1, integrationTime is expanded so they have the same size or the
        other way around.

        Parameters
        ----------
        wavelength
        integrationTime
        gratingType
        fontExitSlitWidth
        fontEntranceSlitWidth
        imageType
        lamp
        spectrometer_delay

        Raises
        ------
            If len(wavelength) > 1 and len(integrationTime) > 1 and len(wavelength) != len(integrationTime).
            or
            If components are passed with non-matching sizes.

        """

        self.log.info("Configure started")

        self.set_as_list('wavelength', wavelength)
        self.set_as_list("integrationTime", integrationTime)
        self.set_as_list("gratingType", gratingType)
        self.set_as_list("fontEntranceSlitWidth", fontEntranceSlitWidth)
        self.set_as_list("fontExitSlitWidth", fontExitSlitWidth)
        self.set_as_list("imageType", imageType)
        self.set_as_list("lamp", lamp)
        self.set_as_list("spectrometer_delay", spectrometer_delay)

        # Check and fix consistency
        self.check_consistency()

        self.log.info("Configure completed")

    def set_metadata(self, metadata):
        """Compute estimated duration based on number of components plus number of
        state transitions.

        Parameters
        ----------
        metadata : SAPY_Script.Script_logevent_metadataC
        """

        duration = 0.
        metadata.duration = duration

    async def run(self):
        """Run script."""

        # await self.checkpoint("start")

        for i in range(len(self.wavelength)):

            # await self.checkpoint("setup monochromator")

            cmd = getattr(self.monochromator, f"cmd_changeWavelength")
            topic = cmd.DataType()
            topic.wavelength = self.wavelength[i]
            await cmd.start(topic, timeout=self.cmd_timeout)

            cmd = getattr(self.monochromator, f"cmd_changeSlitWidth")
            topic = cmd.DataType()
            topic.slit = 2
            topic.slitWidth = self.fontExitSlitWidth[i]
            await cmd.start(topic, timeout=self.cmd_timeout)

            topic = cmd.DataType()
            topic.slit = 1
            topic.slitWidth = self.fontEntranceSlitWidth[i]
            await cmd.start(topic, timeout=self.cmd_timeout)

            cmd = getattr(self.monochromator, f"cmd_cmd_selectGrating")
            topic = cmd.DataType()
            topic.gratingType = self.gratingType[i]

            # FIXME: This command does not work!
            # await cmd.start(topic, timeout=self.cmd_timeout)

            # await self.checkpoint("take data")

            ecapture_topic = self.electrometer.cmd_startScanDt.DataType()
            ecapture_topic.scanDuration = self.integrationTime[i] + self.spectrometer_delay[i]*2.

            task1_capture = self.electrometer.cmd_startScanDt.start(ecapture_topic)
            task2_capture = self.start_after(i)

            await asyncio.gather(task1_capture, task2_capture)

    def set_as_list(self, attribute_name, value):
        """

        Parameters
        ----------
        attribute_name
        value
        """
        if isinstance(value, list):
            setattr(self, attribute_name, value)
        else:
            setattr(self, attribute_name, [value])

    def check_consistency(self):
        """Check size consistency.

        Raises
        ------
        IOError
            If size of input does not matches.

        """
        w_size = len(self.wavelength)
        et_size = len(self.integrationTime)

        if ((w_size > 1) and
                (et_size > 1) and
                (w_size != et_size)):
            raise IOError("Size of wavelength[%i] and integrationTime[%i] does not match",
                          (len(self.wavelength),
                           len(self.integrationTime)))

        if w_size == 1 and et_size > 1:
            self.wavelength = [self.wavelength for i in range(et_size)]
            w_size = et_size
        elif w_size > 1 and et_size == 1:
            self.integrationTime = [self.integrationTime for i in range(w_size)]
            et_size = w_size

        attr_list = ['gratingType',
                     'fontEntranceSlitWidth',
                     'fontExitSlitWidth',
                     'imageType',
                     'lamp']
        for attr in attr_list:
            if len(getattr(self, attr)) == 1:
                setattr(self, attr, [getattr(self, attr)[0] for i in range(w_size)])
            elif len(getattr(self, attr)) != w_size:
                raise IOError(f'Size of {attr} does not match reference size {w_size}.')

    async def start_after(self, index):
        """
        Utility function to start taking data with the spectrometer `self.spectrometer_delay`
        after electrometer.

        Parameters
        ----------
        index : int

        Returns
        -------
        cmd_captureSpectImage.start : coro
        """
        await self.electrometer.evt_detailedState.next(flush=True,
                                                       timeout=self.cmd_timeout)
        await asyncio.sleep(self.spectrometer_delay[index])

        capture_topic = self.fiber_spectrograph.cmd_captureSpectImage.DataType()
        capture_topic.imageType = self.imageType[index]
        capture_topic.integrationTime = self.integrationTime[index]
        capture_topic.lamp = self.lamp[index]

        timeout = self.integrationTime[index]+self.cmd_timeout

        return await self.fiber_spectrograph.cmd_captureSpectImage.start(capture_topic,
                                                                         timeout=timeout)


if __name__ == '__main__':
    ATCalSysTakeData.main(descr="Configure and take data from the AT CalSystem.")
