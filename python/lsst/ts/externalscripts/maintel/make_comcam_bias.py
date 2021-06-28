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

__all__ = ["MakeComCamBias"]

import json
import yaml

from lsst.ts import salobj

from lsst.ts.observatory.control.maintel.comcam import ComCam


class MakeComCamBias(salobj.BaseScript):
    """ Take biases and construct a master bias SAL Script.

    This class takes biases with LSSTComCam and constructs
    a master bias calling the bias pipetask via OCPS.
    """

    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="This class takes biases with LSSTComCam and constructs "
                  "a master bias calling the bias pipetask via OCPS.",
        )
        self.comcam = ComCam(domain=self.domain, log=self.log)
        self.ocps = salobj.Remote(domain=self.domain, name="OCPS")

    @classmethod
    def get_schema(cls):
        schema = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/blob/master/python/lsst/ts/externalscripts/>-
        comcam/make_comcam_bias.py
        title: MakeComCamBias v1
        description: Configuration for making a LSSTComCam master bias SAL Script.
        type: object
        additionalProperties: false
        required: [input_collections]
        properties:
            n_bias:
                type: integer
                default: 1
                description: number of biases to take

            detectors:
                type: tuple
                items:
                    type: integer
                    minItems: 1
                default: (0)
                descriptor: Detector IDs

            input_collections:
                type: string
                descriptor: Input collectiosn to pass to the bias pipetask.
        """
        return yaml.safe_load(schema)

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config: `types.SimpleNamespace`
            Configuration data. See `get_schema` for information about data
            structure.
        """
        # Log information about the configuration

        self.log.debug(
            f"n_bias: {config.n_bias}, detectors: {config.detectors}, "
            f"instrument: LSSTComCam. "
        )

        self.config = config

    def set_metadata(self, metadata):
        """Set estimated duration of the script.
        """
        # Temporary number
        metadata.duration = 10

    async def run(self):
        # Should ComCam and OCPS not be enabled here in the script?
        # original notebook says: "When writing a script, the components
        # should (probably) be enabled by a user."
        #await self.comcam.enable()
        
        await salobj.set_summary_state(self.ocps, salobj.State.ENABLED,
                                       settingsToApply="LSSTComCam.yaml")

        # Take config.n_biases biases, and return a list of IDs
        tempBiasList = await self.comcam.take_bias(self.config.n_bias)
        exposures = tuple(tempBiasList)
        # Bias IDs
        await self.checkpoint(f"Biases taken: {tempBiasList}")

        # did the images get archived and are they available to the butler?
        val = await self.comcam.rem.ccarchiver.evt_imageInOODS.aget(timeout=10)
        await self.checkpoint(f"Biases in ccarchiver: {val}")

        # Now run the bias pipetask via the OCPS
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False, pipeline="${CP_PIPE_DIR}/pipelines/cpBias.yaml", version="",
            config=f"-j 8 -i {self.config.input_collections} --register-dataset-types -c isr:doDefect=False",
            data_query=f"instrument='LSSTComCam' AND"
                       f" detector IN {self.config.detectors} AND exposure IN {exposures}"
        )
        if ack.ack != salobj.SalRetCode.CMD_ACK:
            ack.print_vars()

        # Wait for the in-progress acknowledgement with the job identifier.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack, wait_done=False)
        self.log.debug('Received acknowledgement of ocps command')

        ack.print_vars()
        job_id = json.loads(ack.result)["job_id"]

        # Wait for the command completion acknowledgement.
        ack = await self.ocps.cmd_execute.next_ackcmd(ack)
        self.log.debug('Received command completion acknowledgement from ocps')
        if ack.ack != salobj.SalRetCode.CMD_COMPLETE:
            ack.print_vars()
        # Wait for the job result message that matches the job id we're
        # interested in ignoring any others (from other remotes).
        # This obviously needs to follow the first acknowledgement
        # (that returns the, job id) but might as well wait for the second.
        while True:
            msg = await self.ocps.evt_job_result.next(flush=False)
            response = json.loads(msg.result)
            if response["jobId"] == job_id:
                break

        await self.checkpoint(f"Final status: {response}")
