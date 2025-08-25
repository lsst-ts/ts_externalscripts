# This file is part of ts_standardscripts
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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["OffsetAndTakeImagesLSSTCam"]

import abc
import collections

import yaml
from lsst.ts import salobj
from lsst.ts.idl.enums.Script import ScriptState
from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages
from lsst.ts.observatory.control.maintel.mtcs import MTCS, MTCSUsages


class OffsetAndTakeImagesLSSTCam(salobj.BaseScript, metaclass=abc.ABCMeta):
    """Offset and take images script for lsstcam. This script accepts a
    sequence of offset positions and takes a series of images at each offset
    position. Finally, it resets all applied offsets.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----

    This class requires one of the following properties ["offset_azel",
    "offset_xy", "offset_rot"] to be provided
    in the yaml in order to be configured. Providing more than one of the above
    properties will result in a Validation Error and the script will fail in
    the Configuration State.

    Each offset array (e.g., az/el for offset_azel) is paired by index: the
    first `az` and first `el` are applied together as a single offset, the
    second az and el as the next, and so on. The script will iterate through
    these pairs in order.

        Example:
            offset_azel:
            az: [-5, 10, -10]
            el: [5, -10, 5]

        This configuration will apply the following sequence of offsets:
            1. az = -5, el = 5
            2. az = 10, el = -10
            3. az = -10, el = 5
    """

    def __init__(self, index, descr=""):
        super().__init__(index=index, descr=descr)

        self.config = None
        self.mtcs = None
        self.lsstcam = None

    def _validate_offset_array_lengths(
        self, offset_name: str, config_obj: object, keys: list[str]
    ) -> None:
        offset = getattr(config_obj, offset_name, None)
        if offset is None:
            return

        for key in keys:
            if key not in offset:
                raise ValueError(f"{offset_name} is missing required key: '{key}'")

        lengths = [len(offset[key]) for key in keys]
        if len(set(lengths)) != 1:
            raise ValueError(
                f"All arrays in {offset_name} must have the same length."
                f"Got lengths: {dict(zip(keys, lengths))}"
            )

    async def configure_tcs(self) -> None:
        if self.mtcs is None:
            self.log.debug("Creating MTCS.")
            self.mtcs = MTCS(
                domain=self.domain,
                log=self.log,
                intended_usage=MTCSUsages.Slew,
            )
            await self.mtcs.start_task
        else:
            self.log.debug("MTCS already defined, skipping.")

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self.lsstcam is None:
            self.log.debug("Creating Camera.")
            self.lsstcam = LSSTCam(
                self.domain,
                intended_usage=LSSTCamUsages.TakeImage,
                log=self.log,
            )
            await self.lsstcam.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/offset_and_take_images_lsstcam.yaml
            title: OffsetAndTakeSequenceLSSTCam v1
            description: Configuration for OffsetAndTakeSequenceLSSTCam script.
            type: object
            properties:
              offset_azel:
                type: object
                description: Offset in local AzEl coordinates.
                properties:
                    az:
                        description: Offset in azimuth (arcsec).
                        type: array
                        items:
                            type: number
                    el:
                        description: Offset in elevation (arcsec).
                        type: array
                        items:
                            type: number
                required: ["az","el"]
              offset_xy:
                type: object
                description: Offset in the detector X/Y plane.
                properties:
                    x:
                        description: Offset in camera x-axis (arcsec).
                        type: array
                        items:
                            type: number
                    y:
                        description: Offset in camera y-axis (arcsec).
                        type: array
                        items:
                            type: number
                required: ["x","y"]
              offset_rot:
                type: object
                description: Offset rotator angle. Note that these offsets cannot
                    be relative. They do not accumulate.
                properties:
                    rot:
                        description: Offset rotator (degrees).
                        type: array
                        items:
                            type: number
                required: ["rot"]
              relative:
                description: If True (default), each offset is applied relative to the current
                    position, so offsets accumulate. If False, each offset is applied relative
                    to the original (un-offset) position, so offsets do not accumulate.
                type: boolean
                default: True
              exp_times:
                description: Exposure time(s) in seconds. For each offset position, one
                    image will be taken for each value in exp_times. If a single value is
                    provided, one image with that exposure time is taken at each offset.
                anyOf:
                  - type: array
                    minItems: 1
                    items:
                      type: number
                      minimum: 0
                  - type: number
                    minimum: 0
              image_type:
                description: Image type (a.k.a. IMGTYPE). Limit options to either OBJECT or ACQ.
                type: string
                enum: ["OBJECT", "ACQ"]
                default: "ACQ"
              reset_offsets_when_finished:
                description: Boolean parameter to reset the offsets on script completion.
                type: boolean
                default: True
              program:
                description: >-
                    Name of the program this dataset belongs to.
                type: string
              reason:
                description: Optional reason for taking the data.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              note:
                description: A descriptive note about the image being taken.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              ignore:
                  description: >-
                    CSCs from the groups to ignore in status check. Name must
                    match those in self.tcs.components, e.g.; mthexapod_1, atdome.
                  type: array
                  items:
                    type: string
            additionalProperties: false
            required:
                - exp_times
                - program
            oneOf:
                - required: ["offset_azel"]
                - required: ["offset_xy"]
                - required: ["offset_rot"]
        """
        return yaml.safe_load(schema_yaml)

    async def configure(self, config):
        """Configure script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Script configuration, as defined by `schema`.
        """

        self.offset_azel = getattr(config, "offset_azel", None)
        self.offset_xy = getattr(config, "offset_xy", None)
        self.offset_rot = getattr(config, "offset_rot", None)

        self._validate_offset_array_lengths("offset_azel", config, ["az", "el"])
        self._validate_offset_array_lengths("offset_xy", config, ["x", "y"])

        self.relative = config.relative

        if isinstance(config.exp_times, collections.abc.Iterable):
            self.exp_times = config.exp_times
        else:
            self.exp_times = [config.exp_times]
        self.image_type = config.image_type
        self.program = config.program
        self.reason = config.reason
        self.note = config.note

        self.reset_offsets_when_finished = config.reset_offsets_when_finished

        await self.configure_tcs()
        await self.configure_camera()

        if hasattr(config, "ignore"):
            self.log.debug("Ignoring TCS components.")
            self.mtcs.disable_checks_for_components(components=config.ignore)

    def set_metadata(self, metadata):
        metadata.duration = 10

    async def assert_feasibility(self) -> None:
        """Verify that the telescope is in a feasible state to
        execute the script.
        """

        await self.mtcs.assert_all_enabled()
        await self.lsstcam.assert_all_enabled()

    async def take_images(self):
        for exptime in self.exp_times:
            await self.lsstcam.take_imgtype(
                self.image_type,
                exptime,
                1,
                n_snaps=1,
                reason=self.reason,
                program=self.program,
                group_id=self.group_id,
                note=self.note,
            )

    async def offset_and_take_images(self):
        if self.offset_azel is not None:
            keys = ["az", "el"]
            offset_data = self.offset_azel
            offset_fn = self.mtcs.offset_azel
            label = "azel"
        elif self.offset_xy is not None:
            keys = ["x", "y"]
            offset_data = self.offset_xy
            offset_fn = self.mtcs.offset_xy
            label = "xy"
        elif self.offset_rot is not None:
            keys = ["rot"]
            offset_data = self.offset_rot
            offset_fn = self.mtcs.offset_rot
            label = "rot"

        n_offset_positions = len(offset_data[keys[0]])

        for i in range(n_offset_positions):
            offset_kwargs = {key: offset_data[key][i] for key in keys}
            if label != "rot":
                offset_kwargs.update(
                    {
                        "relative": self.relative,
                        "absorb": False,
                    }
                )
            await self.checkpoint(
                f"Offset type: {label} Step: {i+1} of {n_offset_positions}: {offset_kwargs}"
            )
            await offset_fn(**offset_kwargs)

            await self.take_images()

    async def reset_offsets(self):
        self.log.info("Resetting offsets")
        await self.mtcs.reset_offsets(
            absorbed=False,
            non_absorbed=True,
        )

    async def run(self):
        await self.assert_feasibility()
        await self.offset_and_take_images()
        if self.reset_offsets_when_finished:
            await self.reset_offsets()

    async def cleanup(self):
        if self.state.state != ScriptState.ENDING:
            # abnormal termination
            self.log.info(
                f"Terminating with state={self.state.state}: resetting offsets."
            )
            try:
                await self.reset_offsets()
            except Exception:
                self.log.exception("Unexpected exception while resetting offsets.")
