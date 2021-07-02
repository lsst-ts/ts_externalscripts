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

__all__ = ["MakeLatissBias"]

import json
import yaml
import os

from lsst.ts import salobj

from lsst.ts.observatory.control.auxtel.latiss import LATISS
from ..base_make_bias import BaseMakeBias


class MakeLatissBias(BaseMakeBias):
    """ Take biases and construct a master bias SAL Script.

    This class takes biases with LATISS and constructs
    a master bias calling the bias pipetask via OCPS.
    """

    def __init__(self, index=1):
        super().__init__(
            index=index,
            descr="This class takes biases with Auxtel-LATISS and constructs "
                  "a master bias calling the bias pipetask via OCPS.",
        )
        self.latiss = LATISS(domain=self.domain, log=self.log)
        self.ocps = salobj.Remote(domain=self.domain, name="OCPS")

    @classmethod
    def get_schema(cls):
        schema = """
        $schema: http://json-schema.org/draft-07/schema#
        $id: https://github.com/lsst-ts/ts_externalscripts/python/lsst/ts/\
                externalscripts/auxtel/make_latiss_bias.py
        title: MakeLatissBias v1
        description: Configuration for making a LATISS bias SAL Script.
        type: object
        """
        schema_dict = yaml.safe_load(schema)

        base_schema_dict = super(MakeLatissBias, cls).get_schema()

        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

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
            f"instrument: LATISS. "
        )

        self.config = config

    def set_metadata(self, metadata):
        """Set estimated duration of the script.
        """
        # Temporary number
        metadata.duration = 10

    async def arun(self, checkpoint=False):

        # Take config.n_biases biases, and return a list of IDs
        if checkpoint:
            await self.checkpoint(f"Taking {self.config.n_bias} biases")
        exposures = tuple(await self.latiss.take_bias(self.config.n_bias))

        if checkpoint:
            # Bias IDs
            await self.checkpoint(f"Biases taken: {exposures}")

        # did the images get archived and are they available to the butler?
        val = await self.comcam.rem.atarchiver.evt_imageInOODS.aget(timeout=20)

        if checkpoint:
            await self.checkpoint(f"Biases in archiver: {val}")

        # Check　if val corresponds to last image
        obs_id = int(val.obsid.split('_')[-2] + val.obsid.split('_')[-1])

        # if they are not the same, wait for a couple of more events
        max_counter = 5
        counter = 0
        while obs_id != exposures[-1]:
            val = await self.comcam.rem.atarchiver.evt_imageInOODS.aget(timeout=20)
            obs_id = int(val.obsid.split('_')[-2] + val.obsid.split('_')[-1])
            if counter == max_counter:
                self.log.info("Warning: last image not found in archiver yet")
                break
            counter += 1

        self.ocps.evt_job_result.flush()

        # Now run the bias pipetask via the OCPS
        ack = await self.ocps.cmd_execute.set_start(
            wait_done=False, pipeline="${CP_PIPE_DIR}/pipelines/cpBias.yaml", version="",
            config=f"-j 8 -i {self.config.input_collections} --register-dataset-types -c isr:doDefect=False",
            data_query=f"instrument='LATISS' AND"
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
            msg = await self.ocps.evt_job_result.next(flush=False, timeout=600)
            response = json.loads(msg.result)
            if response["jobId"] == job_id:
                break

        self.log.info(f"Final status: {response}")

        # Certify the bias, if the job completed successfully
        if not response['phase'] == 'completed':
            raise RuntimeError(f"Bias creation not completed successfully: {response['phase']}")
        else:
            self.log.info("Certifying bias")
            # certify the bias
            REPO = "/repo/LATISS"
            # This is the output collection where the OCPS puts the biases
            BIAS_DIR = f"u/ocps/{job_id}"
            CAL_DIR = self.config.calib_dir
            cmd = f"butler certify-calibrations {REPO} {BIAS_DIR} {CAL_DIR} "
            "--begin-date 1980-01-01 --end-date 2050-01-01 bias"
            os.system(cmd)
            self.log.info("Finished running command for certifying bias")
