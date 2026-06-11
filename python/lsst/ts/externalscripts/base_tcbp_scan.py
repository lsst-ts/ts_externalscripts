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

__all__ = [
    "BaseTCBPScan",
    "TravelingCBP",
    "FitsBuilder",
    "ProxyWithCompletion",
    "get_optimized_wavelengths",
    "tcbp_expo_time_calculator",
    "fill_seqfile",
    "hdu_to_base64",
    "KNOWN_OPTIMIZED_FILTERS",
    "PHOTODIODE_REFERENCE_NPY",
    "DEFAULT_TCBP_REMOTE_DATADIR",
]

import abc
import asyncio
import base64
import concurrent.futures
import datetime
import io
import os
from importlib import resources
from xmlrpc.client import ServerProxy

import astropy.io.fits as pf
import numpy as np
import yaml
from lsst.ts.standardscripts.base_block_script import BaseBlockScript

PHOTODIODE_REFERENCE_NPY = "photodiode_charges_pinhole75um_slit20.dat"
DEFAULT_TCBP_REMOTE_DATADIR = "/home/dice/data/frames"
KNOWN_OPTIMIZED_FILTERS = frozenset({"holo", "empty", "og550", "bg40", "quadnotch"})


def hdu_to_base64(hdulist):
    """Serialise an :class:`astropy.io.fits.HDUList` to a base64 string.

    Suitable for transport over XML-RPC, which cannot carry raw binary blobs.
    """
    buf = io.BytesIO()
    hdulist.writeto(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


class ProxyWithCompletion(ServerProxy):
    """XML-RPC ServerProxy subclass that exposes the remote method list via
    ``dir()``."""

    def __dir__(self):
        return self.system.listMethods()


def get_optimized_wavelengths(filt):
    """Return the optimized wavelength grid (nm) for a given filter/grating.

    Parameters
    ----------
    filt : str
        Filter/grating identifier.

    Returns
    -------
    numpy.ndarray
        Sorted array of unique wavelengths in nm.
    """
    if filt == "holo4_003":
        return np.concatenate([np.arange(300, 450, 4), np.arange(450, 1150, 10)])
    elif filt == "empty_1":
        return np.concatenate([np.arange(300, 450, 4), np.arange(450, 1150, 10)])
    elif filt == "prism":
        return np.concatenate([np.arange(300, 450, 4), np.arange(450, 1150, 10)])
    elif filt == "nonanotch":
        wavelengths = np.concatenate(
            [
                np.arange(300, 1140, 5),
                np.arange(330, 340, 1),  # band1 edge1
                np.arange(378, 388, 1),  # band1 edge2
                np.arange(390, 400, 1),  # band2 edge1
                np.arange(418, 428, 1),  # band2 edge1
                np.arange(485, 495, 1),  # band3 edge1
                np.arange(510, 520, 1),  # band3 edge2
                np.arange(525, 535, 1),  # band4 edge1
                np.arange(540, 550, 1),  # band4 edge2
                np.arange(555, 565, 1),  # band5 edge1
                np.arange(574, 584, 1),  # band5 edge2
                np.arange(589, 599, 1),  # band6 edge1
                np.arange(619, 629, 1),  # band6 edge2
                np.arange(634, 644, 1),  # band7 edge1
                np.arange(653, 663, 1),  # band7 edge2
                np.arange(832, 842, 1),  # band8 edge1
                np.arange(872, 882, 1),  # band8 edge2
                np.arange(902, 912, 1),  # band9 edge1
                np.arange(965, 975, 1),  # band9 edge2
            ]
        )
        return np.sort(np.unique(wavelengths))
    elif filt == "OG550_65mm_1":
        return np.concatenate(
            [np.arange(300, 520, 20), np.arange(520, 600, 2), np.arange(600, 1150, 10)]
        )
    elif filt == "BG40_65mm_1":
        return np.concatenate(
            [
                np.arange(300, 450, 4),
                np.arange(450, 560, 10),
                np.arange(560, 700, 10),
                np.arange(700, 1150, 50),
            ]
        )
    elif filt == "quadnotch":
        wavelengths = np.concatenate(
            [
                np.arange(300, 682, 2),
                np.arange(344, 348, 1),
                np.arange(390, 398, 1),
                np.arange(410, 416, 1),
                np.arange(476, 484, 1),
                np.arange(490, 497, 1),
                np.arange(518, 526, 1),
                np.arange(535, 542, 1),
                np.arange(590, 598, 1),
                np.arange(650, 656, 1),
            ]
        )
        return np.sort(np.unique(wavelengths))
    elif filt == "u_24":
        return [
            300,
            302,
            304,
            306,
            308,
            310,
            312,
            314,
            316,
            318,
            320,
            322,
            324,
            326,
            328,
            330,
            335,
            340,
            345,
            350,
            355,
            360,
            365,
            370,
            375,
            377,
            379,
            381,
            383,
            385,
            387,
            389,
            391,
            393,
            395,
            397,
            399,
            401,
            403,
            405,
        ]
    elif filt == "g_6":
        return [
            385,
            387,
            389,
            391,
            393,
            395,
            397,
            399,
            401,
            403,
            405,
            407,
            409,
            411,
            413,
            415,
            420,
            425,
            430,
            435,
            440,
            445,
            450,
            455,
            460,
            465,
            470,
            475,
            480,
            485,
            490,
            495,
            500,
            505,
            510,
            515,
            520,
            525,
            530,
            532,
            534,
            536,
            538,
            540,
            542,
            544,
            546,
            548,
            550,
            552,
            554,
            556,
            558,
            560,
            562,
            564,
            566,
            568,
            570,
            1000,
            1020,
            1040,
            1060,
            1080,
            1100,
            1120,
            1140,
            1160,
            1180,
        ]
    elif filt == "r_57":
        return [
            535,
            537,
            539,
            541,
            543,
            545,
            547,
            549,
            551,
            553,
            555,
            557,
            559,
            561,
            563,
            565,
            570,
            575,
            580,
            585,
            590,
            595,
            600,
            605,
            610,
            615,
            620,
            625,
            630,
            635,
            640,
            645,
            650,
            655,
            660,
            665,
            670,
            675,
            677,
            679,
            681,
            683,
            685,
            687,
            689,
            691,
            693,
            695,
            697,
            699,
            701,
            703,
            705,
        ]
    elif filt == "i_39":
        return [
            665,
            667,
            669,
            671,
            673,
            675,
            677,
            679,
            681,
            683,
            685,
            687,
            689,
            691,
            693,
            695,
            697,
            699,
            701,
            703,
            705,
            710,
            715,
            720,
            725,
            730,
            735,
            740,
            745,
            750,
            755,
            760,
            765,
            770,
            775,
            780,
            785,
            790,
            795,
            800,
            802,
            804,
            806,
            808,
            810,
            812,
            814,
            816,
            818,
            820,
            822,
            824,
            826,
            828,
            830,
            832,
            834,
            836,
            838,
            840,
        ]
    elif filt == "z_20":
        return [
            800,
            802,
            804,
            806,
            808,
            810,
            812,
            814,
            816,
            818,
            820,
            822,
            824,
            826,
            828,
            830,
            835,
            840,
            845,
            850,
            855,
            860,
            865,
            870,
            875,
            880,
            885,
            890,
            895,
            900,
            905,
            910,
            912,
            914,
            916,
            918,
            920,
            922,
            924,
            926,
            928,
            930,
            932,
            934,
            936,
            938,
            940,
        ]
    elif filt == "y_10":
        return [
            905,
            907,
            909,
            911,
            913,
            915,
            917,
            919,
            921,
            923,
            925,
            927,
            929,
            931,
            933,
            935,
            937,
            939,
            941,
            943,
            945,
            950,
            955,
            960,
            965,
            970,
            975,
            980,
            985,
            990,
            995,
            1000,
            1005,
            1010,
            1015,
            1020,
            1025,
            1030,
            1035,
            1040,
            1045,
            1050,
            1055,
            1060,
            1065,
            1070,
            1075,
            1080,
            1085,
            1090,
            1095,
            1100,
            1105,
            1110,
            1115,
            1120,
        ]
    else:
        raise ValueError(
            f"Filter {filt!r} not recognized. Implement optimized wavelength "
            "sampling for this filter or pass an explicit wavelengths list."
        )


def _photodiode_reference_path():
    """Resolve the path to the bundled photodiode reference file."""
    return resources.files("lsst.ts.externalscripts").joinpath(
        "data", "external_data", PHOTODIODE_REFERENCE_NPY
    )


def tcbp_expo_time_calculator(
    wl,
    norm=10,
    maxi=60,
    mini=1,
    uv_maxi=30,
    uv_threshold=360,
    reference_file=None,
):
    """Compute exposure time(s) that normalise the CBP flux at each wavelength.

    The exposure time is derived by scaling a reference photodiode charge
    spectrum so that the integrated charge equals *norm* (arbitrary units).

    Parameters
    ----------
    wl : float or array-like
        Wavelength(s) in nm.
    norm : float
        Target normalised charge (default 10).
    maxi : float
        Maximum allowed exposure time in seconds.
    mini : float
        Minimum allowed exposure time in seconds.
    uv_maxi : float
        Maximum exposure time below *uv_threshold* (default 30 s).
    uv_threshold : float or None
        Wavelength threshold in nm below which *uv_maxi* is applied.
    reference_file : str or os.PathLike, optional
        Override the bundled reference npy file (mainly for tests).

    Returns
    -------
    numpy.ndarray
        Clipped exposure times in seconds, one per input wavelength.
    """
    if reference_file is None:
        reference_file = _photodiode_reference_path()
    wavelengths, charges, _ = np.loadtxt(reference_file)
    denominator = norm * np.mean(charges) / charges
    wl_array = np.atleast_1d(wl).astype(float)
    times = np.clip(np.interp(wl_array, wavelengths, denominator), mini, maxi)
    if uv_threshold is not None:
        ind_uv = wl_array < uv_threshold
        if np.any(ind_uv):
            times[ind_uv] = np.clip(
                np.interp(wl_array[ind_uv], wavelengths, denominator), mini, uv_maxi
            )
    return times


def fill_seqfile(image_id, wl, tcbp_id, datadir, key="IMAGEID"):
    """Append one scan entry (wavelength, TCBP sequence ID, image ID) to the
    sequence file.

    Parameters
    ----------
    image_id : dict
        Dictionary containing the camera image identifier under *key*.
    wl : float
        Wavelength in nm (stored as ``int(wl) * 10``, i.e. in 0.1 nm units).
    tcbp_id : str
        TCBP sequence identifier (timestamp-derived string).
    datadir : str
        Path to the output directory for this scan.
    key : str
        Dict key used to look up the camera identifier.
    """
    if not os.path.exists(datadir):
        os.makedirs(datadir)
    reponame = os.path.basename(os.path.normpath(datadir))
    param_path = os.path.join(datadir, f"{reponame}_wl_seq_id_image_id.txt")
    with open(param_path, "a+") as param_file:
        param_file.write(str(round(int(wl) * 10)))
        param_file.write(",")
        param_file.write(str(tcbp_id))
        param_file.write(",")
        param_file.write(str(image_id[key]))
        param_file.write("\n")


class FitsBuilder:
    """Assemble FITS headers + binary tables from TCBP/LogicTimer telemetry."""

    def __init__(self, output_dir, filename="TEST"):
        self.output_dir = output_dir
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        self.headers = {}
        self.tables = {}
        self.filename = filename

    def append(self, hdr_element, suffix="", prefix=""):
        """Append a header element (dict or list of (key, value) pairs)."""
        if hdr_element is None:
            return
        if isinstance(hdr_element, dict):
            keys = [prefix + k + suffix for k in hdr_element.keys()]
            self.headers.update(dict(zip(keys, hdr_element.values())))
        elif isinstance(hdr_element, list):
            for hdr_el in hdr_element:
                self.headers[prefix + hdr_el[0] + suffix] = str(hdr_el[1])
        else:
            raise ValueError("hdr_element must be dict or list")

    def add_table(self, tablename, data):
        """Register a numpy recarray as a named FITS binary table extension."""
        self.tables[tablename] = data

    def dump(self):
        """Build and return the in-memory FITS HDUList.

        Returns
        -------
        astropy.io.fits.HDUList or None
            HDUList containing a primary HDU (with the merged header) plus a
            :class:`~astropy.io.fits.TableHDU` for every registered table.
            Returns ``None`` if no tables have been added.
        """
        if not self.tables:
            return None

        common_header = pf.Header(list(zip(self.headers.keys(), self.headers.values())))
        hdul = pf.HDUList(pf.PrimaryHDU(header=pf.Header(common_header)))
        for tablename, data in self.tables.items():
            hdul.append(pf.TableHDU(data=data, name=tablename))
        return hdul

    def write_fits(self, output_dir=None):
        """Build the HDUList and write it to disk locally."""
        if output_dir is None:
            output_dir = self.output_dir
        if not os.path.isdir(output_dir):
            os.makedirs(output_dir)
        hdu = self.dump()
        if hdu is None:
            return None
        filename = os.path.join(output_dir, self.filename)
        hdu.writeto(filename, overwrite=True)
        return filename


def _make_nt_from_data(d):
    names = list(d.keys())
    return np.rec.fromarrays([d[n] for n in names], names=names)


def _populate_fitsbuilder(full_data, frequency, image_id, fitsbuilder):
    """Populate *fitsbuilder* with TCBP + LogicTimer telemetry."""
    fitsbuilder.append(image_id)

    for instrument, payload in full_data["tcbp"].items():
        fitsbuilder.append(payload[1], prefix=instrument)
        data = payload[3]
        if data:
            if instrument in ("keysight", "keithley"):
                nt_data = np.rec.fromrecords(
                    [(res[1], res[0]) for res in data], names=["time", "current"]
                )
            else:
                nt_data = _make_nt_from_data(data)
            fitsbuilder.add_table(instrument.upper(), nt_data)

    nt_data_lt = np.rec.fromrecords(
        [(res[0], res[1]) for res in full_data["logictimer"]],
        names=["timing", "pinstate"],
    )
    fitsbuilder.add_table("TIMING", nt_data_lt)
    fitsbuilder.append({"clockfrequency": frequency, "unit": "clock ticks"})


class TravelingCBP:
    """High-level interface to the TCBP instrument.

    Wraps the two XML-RPC servers (TCBP and LogicTimer) and provides methods
    to configure an exposure, trigger a simultaneous acquisition, and write
    the result to a FITS file.

    Parameters
    ----------
    addr_tcbp : str
        URL of the TCBP XML-RPC server.
    addr_logictimer : str
        URL of the LogicTimer XML-RPC server.
    log : logging.Logger, optional
        Logger to use for status messages.
    proxy_factory : callable, optional
        Factory that returns an XML-RPC proxy given (address, allow_none).
        Defaults to :class:`ProxyWithCompletion`. Mainly for tests.
    """

    def __init__(
        self,
        addr_tcbp,
        addr_logictimer,
        log=None,
        proxy_factory=None,
    ):
        if proxy_factory is None:
            proxy_factory = lambda addr, allow_none: ProxyWithCompletion(  # noqa: E731
                addr, allow_none=allow_none
            )
        self.tcbp = proxy_factory(addr_tcbp, True)
        self.logictimer = proxy_factory(addr_logictimer, True)
        self.log = log
        self.wl = None
        self.full_data = None
        self.filename = None

    def _info(self, msg):
        if self.log is not None:
            self.log.info(msg)

    def _warn(self, msg):
        if self.log is not None:
            self.log.warning(msg)

    def initialize(self):
        """Initialise the LogicTimer line configuration and the TCBP."""
        self.logictimer.enable_lines(["0r", "1b", "2r"])
        self.tcbp.initialize()

    def get_logictimer_data(self):
        """Retrieve timing data from the LogicTimer.

        Returns
        -------
        numpy.recarray
            Record array with fields ``timing`` and ``pinstate``.
            Returns ``[(-1, -1)]`` if the retrieval fails.
        """
        try:
            return np.rec.fromrecords(
                self.logictimer.get_data(), names=["timing", "pinstate"]
            )
        except Exception:
            self._warn("Failed to retrieve data from DigitalAnalyser")
            return np.rec.fromrecords([(-1, -1)], names=["timing", "pinstate"])

    def set_exposure(self, wl, expo_time, pre_expo_time, post_expo_time):
        """Configure the wavelength and exposure timing on both servers."""
        self.wl = float(wl)

        logictimer_duration = float(expo_time + pre_expo_time + post_expo_time + 0.5)
        self.logictimer.set_duration(logictimer_duration)

        self.tcbp.set_wavelength(float(wl))
        self.tcbp.set_exposure(
            float(expo_time), float(pre_expo_time), float(post_expo_time)
        )

        self._info(
            f"set exposure done — wavelength: {wl} nm, "
            f"expo={expo_time}s pre_expo={pre_expo_time}s "
            f"post_expo={post_expo_time}s, "
            f"logictimer duration: {self.logictimer.get_duration()}"
        )

    def shot(self):
        """Trigger a simultaneous TCBP and LogicTimer acquisition."""
        self._info("start acquisition")
        now = datetime.datetime.now().isoformat()
        seq_id = now.replace("-", "").replace("T", "").replace(":", "")[:14]
        self.tcbp.seq_id = seq_id

        with concurrent.futures.ThreadPoolExecutor() as executor:
            t1 = executor.submit(self.get_logictimer_data)
            t2 = executor.submit(self.tcbp.shot)

        logictimer_data = t1.result()
        t2.result()
        tcbp_data = self.tcbp.get_data()
        self.full_data = {"tcbp": tcbp_data, "logictimer": logictimer_data}

        self._info("tcbp acquisition done")

    def make_fits(self, image_id, datadir):
        """Build the FITS HDUList for the last acquisition (no disk write).

        The caller is responsible for writing the HDU and updating the seq
        file — typically by handing the base64-encoded HDU to the TCBP
        server's ``write_fits`` XML-RPC method.

        Parameters
        ----------
        image_id : dict
            Dictionary containing the camera image id.
        datadir : str
            Output directory used as ``FitsBuilder.output_dir`` (only relevant
            if a caller later chooses to write locally).

        Returns
        -------
        tuple
            ``(hdu, filename)`` where ``hdu`` is the in-memory
            :class:`astropy.io.fits.HDUList` and ``filename`` is the basename
            ``<wl*10>_<seq_id>.fits``.
        """
        clockfrequency = self.logictimer.get_frequency()

        self.filename = f"{int(self.wl) * 10}_{self.tcbp.seq_id}.fits"
        fitsbuilder = FitsBuilder(output_dir=datadir, filename=self.filename)
        _populate_fitsbuilder(
            full_data=self.full_data,
            frequency=clockfrequency,
            image_id=image_id,
            fitsbuilder=fitsbuilder,
        )
        hdu = fitsbuilder.dump()
        self._info(f"make tcbp hdu done. Filename = {self.filename}")
        return hdu, self.filename


class BaseTCBPScan(BaseBlockScript, metaclass=abc.ABCMeta):
    """Base SAL Script that drives a wavelength scan using the Traveling CBP.

    Subclasses configure a specific camera (LATISS or LSSTCam) and implement
    :meth:`take_camera_image` and :meth:`get_image_id_dict`.

    Parameters
    ----------
    index : int
        Index of the Script SAL component.
    descr : str
        Human-readable description.
    """

    def __init__(self, index, descr="Run a TCBP wavelength scan."):
        super().__init__(index=index, descr=descr)

        self.tcbp_class = None
        self.config = None

        # Filled in during configure().
        self.wavelengths = None
        self.datadir = None
        self.tcbp_remote_datadir = None
        self.dark_step = None
        self.pre_expo_time = None
        self.post_expo_time = None
        self.norm = None
        self.mini = None
        self.maxi = None
        self.uv_maxi = None
        self.uv_threshold = None
        self.n_expo = None
        self.reason = None
        self.program = None
        self.img_type = None
        self.close_shutter_before = None

    @classmethod
    def get_schema(cls):
        schema_yaml = """
            $schema: http://json-schema.org/draft-07/schema#
            $id: https://github.com/lsst-ts/ts_externalscripts/base_tcbp_scan.yaml
            title: BaseTCBPScan v1
            description: Configuration for BaseTCBPScan.
            type: object
            properties:
              addr_tcbp:
                description: URL of the TCBP XML-RPC server.
                type: string
              addr_logictimer:
                description: URL of the LogicTimer XML-RPC server.
                type: string
              wavelengths:
                description: >-
                  Explicit list of wavelengths in nm. If omitted, the
                  subclass derives a default grid from its camera filter
                  (see :meth:`default_filter_for_optimized_wavelengths`).
                type: array
                items:
                  type: number
              datadir:
                description: >-
                  Local output directory used as the basename for the seq-id
                  file written remotely. If omitted, a timestamped directory
                  name is generated.
                anyOf:
                  - type: string
                  - type: "null"
                default: null
              tcbp_remote_datadir:
                description: >-
                  Path on the TCBP computer where FITS files are written by
                  the TCBP server's ``write_fits`` XML-RPC method.
                type: string
                default: /home/dice/data/frames
              pre_expo_time:
                description: Pre-exposure shutter delay (s).
                type: number
                default: 2
              post_expo_time:
                description: Post-exposure shutter delay (s).
                type: number
                default: 1
              norm:
                description: Target normalised charge for exposure scaling.
                type: number
                default: 10
              mini:
                description: Minimum TCBP exposure time (s).
                type: number
                default: 1
              maxi:
                description: Maximum TCBP exposure time (s).
                type: number
                default: 100
              uv_maxi:
                description: Maximum TCBP exposure time below uv_threshold (s).
                type: number
                default: 30
              uv_threshold:
                description: Wavelength below which uv_maxi applies (nm).
                anyOf:
                  - type: number
                  - type: "null"
                default: 360
              dark_step:
                description: Take a dark every N wavelengths.
                type: integer
                minimum: 1
                default: 10
              n_expo:
                description: Number of camera exposures per wavelength.
                type: integer
                minimum: 1
                default: 1
              img_type:
                description: Image type passed to the camera.
                type: string
                default: CBP
              close_shutter_before:
                description: Close the TCBP shutter before starting the scan.
                type: boolean
                default: true
            required:
              - addr_tcbp
              - addr_logictimer
            additionalProperties: false
        """
        schema_dict = yaml.safe_load(schema_yaml)

        base_schema_dict = super().get_schema()
        for prop in base_schema_dict["properties"]:
            schema_dict["properties"][prop] = base_schema_dict["properties"][prop]

        return schema_dict

    @abc.abstractmethod
    async def configure_camera(self):
        """Configure the camera + TCS objects (subclass responsibility)."""
        raise NotImplementedError

    @abc.abstractmethod
    async def take_camera_image(self, exptime, n_expo, reason, program):
        """Trigger a camera exposure and return the (first) image ID."""
        raise NotImplementedError

    def get_image_id_key(self):
        """Header key used to record the camera image id."""
        return "IMAGEID"

    def make_tcbp(self):
        """Construct the TravelingCBP object. Override for tests."""
        return TravelingCBP(
            addr_tcbp=self.config.addr_tcbp,
            addr_logictimer=self.config.addr_logictimer,
            log=self.log,
        )

    def default_filter_for_optimized_wavelengths(self, config):
        """Return the filter name used to pick the default wavelength grid.

        Subclasses override this to map their own camera filter/grating config
        onto one of the keys understood by :func:`get_optimized_wavelengths`.
        The default returns ``"empty"`` (i.e. the broad UV+visible grid).
        """
        return "empty_1"

    def datadir_tag(self, config):
        """Return a short tag identifying this scan in the auto-generated
        directory name. Subclasses override to include their filter info."""
        return self.default_filter_for_optimized_wavelengths(config)

    def _resolve_wavelengths(self, config):
        if getattr(config, "wavelengths", None):
            return list(config.wavelengths)
        return list(
            get_optimized_wavelengths(
                self.default_filter_for_optimized_wavelengths(config)
            )
        )

    async def configure(self, config):
        """Set up internal state and bring up the TCBP + camera."""
        await super().configure(config)
        self.config = config

        await self.configure_camera()

        if self.tcbp_class is None:
            self.log.debug("Initialising TravelingCBP.")
            self.tcbp_class = self.make_tcbp()
            await asyncio.to_thread(self.tcbp_class.initialize)

        self.wavelengths = self._resolve_wavelengths(config)
        self.pre_expo_time = config.pre_expo_time
        self.post_expo_time = config.post_expo_time
        self.norm = config.norm
        self.mini = config.mini
        self.maxi = config.maxi
        self.uv_maxi = config.uv_maxi
        self.uv_threshold = config.uv_threshold
        self.dark_step = config.dark_step
        self.n_expo = config.n_expo
        self.img_type = config.img_type
        # `reason` and `program` come from BaseBlockScript; default to "scan"
        # if the user did not provide them.
        if self.reason is None:
            self.reason = "scan"
        if self.program is None:
            self.program = "scan"
        self.close_shutter_before = config.close_shutter_before

        if config.datadir:
            self.datadir = config.datadir
        else:
            date = datetime.datetime.now().strftime("%Y%m%d")
            reponame = f"{date}_scan_pinhole75um_slit20_{self.datadir_tag(config)}"
            self.datadir = reponame

        self.tcbp_remote_datadir = os.path.join(
            config.tcbp_remote_datadir, os.path.basename(self.datadir.rstrip("/"))
        )

        self.log.info(
            f"TCBP scan configured: {len(self.wavelengths)} wavelengths, "
            f"local datadir={self.datadir}, "
            f"remote TCBP datadir={self.tcbp_remote_datadir}"
        )

    def set_metadata(self, metadata):
        """Estimate scan duration."""
        per_wl = self.maxi + self.pre_expo_time + self.post_expo_time + 1.0
        n_darks = max(1, len(self.wavelengths) // self.dark_step)
        metadata.duration = per_wl * (len(self.wavelengths) + n_darks)

    def compute_exposure_time(self, wl):
        """Compute the TCBP exposure time for a single wavelength."""
        return float(
            tcbp_expo_time_calculator(
                float(wl),
                norm=self.norm,
                maxi=self.maxi,
                mini=self.mini,
                uv_maxi=self.uv_maxi,
                uv_threshold=self.uv_threshold,
            )[0]
        )

    async def acquire_one(self, exptime_camera, reason):
        """Trigger a camera exposure and a TCBP shot concurrently."""
        results = await asyncio.gather(
            self.take_camera_image(
                exptime=exptime_camera,
                n_expo=self.n_expo,
                reason=reason,
                program=self.program,
            ),
            asyncio.to_thread(self.tcbp_class.shot),
        )
        return results[0]

    async def run_block(self):
        """Iterate over the wavelength grid, taking interleaved darks."""
        if self.close_shutter_before:
            await asyncio.to_thread(self.tcbp_class.tcbp.close_shutter)

        for k, wl in enumerate(self.wavelengths):
            reason = f"{self.reason}_{int(wl)}"

            expo_time = self.compute_exposure_time(float(wl))
            expo_time_camera = expo_time + self.pre_expo_time + self.post_expo_time

            await asyncio.to_thread(
                self.tcbp_class.set_exposure,
                float(wl),
                expo_time,
                self.pre_expo_time,
                self.post_expo_time,
            )

            if k % self.dark_step == 0:
                self.log.info(f"taking {expo_time_camera}s dark...")
                aux_id = await self.take_camera_image(
                    exptime=expo_time_camera,
                    n_expo=self.n_expo,
                    reason=reason,
                    program=self.program,
                )
                image_id_dict = self.get_image_id_dict(aux_id)
                await asyncio.to_thread(
                    self.tcbp_class.tcbp.fill_seqfile,
                    image_id_dict,
                    -1,
                    -1,
                    self.tcbp_remote_datadir,
                )
                await asyncio.sleep(5.0)

            aux_id = await self.acquire_one(expo_time_camera, reason)

            image_id_dict = self.get_image_id_dict(aux_id)
            tcbp_hdu, filename = await asyncio.to_thread(
                self.tcbp_class.make_fits,
                image_id_dict,
                self.datadir,
            )
            await asyncio.to_thread(
                self.tcbp_class.tcbp.fill_seqfile,
                image_id_dict,
                float(wl),
                self.tcbp_class.tcbp.seq_id,
                self.tcbp_remote_datadir,
            )
            await asyncio.to_thread(
                self.tcbp_class.tcbp.write_fits,
                hdu_to_base64(tcbp_hdu),
                filename,
                self.tcbp_remote_datadir,
            )

            await asyncio.sleep(1.0)

    def get_image_id_dict(self, image_id):
        """Convert a camera return value into a header dict.

        Subclasses may override; the default extracts the first element from
        a list/tuple, mirroring ``LATISS.take_imgtype``'s return shape.
        """
        first = image_id[0] if isinstance(image_id, (list, tuple)) else image_id
        return {self.get_image_id_key(): str(first)}
