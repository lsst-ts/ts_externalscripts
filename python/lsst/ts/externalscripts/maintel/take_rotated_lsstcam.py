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
# along with this program. If not, see <https://www.gnu.org/licenses/>.

__all__ = ["TakeRotatedLSSTCam"]

from lsst.ts.observatory.control.maintel.lsstcam import LSSTCam, LSSTCamUsages

from ..base_take_rotated import BaseTakeRotated


class TakeRotatedLSSTCam(BaseTakeRotated):
    """Take AOS sequences with LSSTCam at different rotator angles.

    Parameters
    ----------
    index : `int`
        Index of Script SAL component.

    Notes
    -----
    **Checkpoints**

    - "Slewing to rotator angle {angle} degrees.": Before slewing to the angle.
    - "Taking images at rotator angle {angle} degrees.": Before taking images.
    """

    def __init__(self, index, descr="Take AOS rotated sequence with LsstCam.") -> None:
        super().__init__(index=index, descr=descr)

        self._camera = None
        self.instrument_name = "LSSTCam"

    @property
    def camera(self):
        return self._camera

    async def configure_camera(self) -> None:
        """Handle creating the camera object and waiting remote to start."""
        if self._camera is None:
            self.log.debug("Creating Camera.")
            self._camera = LSSTCam(
                self.domain, intended_usage=LSSTCamUsages.TakeImage, log=self.log
            )
            await self._camera.start_task
        else:
            self.log.debug("Camera already defined, skipping.")

    def get_instrument_name(self) -> str:
        """Get instrument name.

        Returns
        -------
        instrument_name: `string`
        """
        return self.instrument_name
