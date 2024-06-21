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

__all__ = ["TrackTargetSched"]

from lsst.ts.observatory.control.utils import RotType
from lsst.ts.standardscripts.base_track_target import SlewType
from lsst.ts.standardscripts.base_track_target_and_take_image import (
    BaseTrackTargetAndTakeImage,
)
from lsst.ts.standardscripts.maintel import TrackTarget


class TrackTargetSched(TrackTarget):
    """Track target using the scheduler

    This script implements a simple visit consisting of slewing to a target
    and start tracking.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.
    add_remotes : `bool` (optional)
        Create remotes to control components (default: `True`)? If False, the
        script will not work for normal operations. Useful for unit testing.
    """

    @classmethod
    def get_schema(cls):
        # Get the base schema from BaseTrackTargetAndTakeImage so this script
        # is compatible with the scheduler
        schema_dict = BaseTrackTargetAndTakeImage.get_base_schema()
        schema_dict[
            "$id"
        ] = "https://github.com/lsst-ts/ts_externalscripts/maintel/track_target_sched.py"
        schema_dict["title"] = "TrackTargetSched v1"
        schema_dict["description"] = "Configuration for TrackTargetSched."

        schema_dict["ignore"] = dict(
            description=(
                "CSCs from the group to ignore in status check. "
                "Name must match those in self.group.components, e.g.; mtmount."
            ),
            type="array",
            items=dict(type="string"),
        )

        return schema_dict

    async def configure(self, config):
        """Configure the script.

        Parameters
        ----------
        config : `types.SimpleNamespace`
            Configuration
        """

        self.config = config

        self.config.rot_type = RotType.Physical
        self.config.track_for = sum(self.config.exp_times)
        self.config.offset = dict(x=0, y=0)
        self.config.differential_tracking = dict(dra=0.0, ddec=0.0)
        self.config.rot_value = self.config.rot_sky
        self.config.stop_when_done = False

        self.slew_type = SlewType.ICRS
        self.config.slew_icrs = dict(ra=self.config.ra, dec=self.config.dec)

        if hasattr(self.config, "ignore"):
            for comp in self.config.ignore:
                if comp not in self.tcs.components_attr:
                    self.log.warning(
                        f"Component {comp} not in CSC Group. "
                        f"Must be one of {self.tcs.components_attr}. Ignoring."
                    )
                else:
                    self.log.debug(f"Ignoring component {comp}.")
                    setattr(self.tcs.check, comp, False)
