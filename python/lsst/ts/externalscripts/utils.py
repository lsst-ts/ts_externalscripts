# This file is part of ts_externalscripts
#
# Developed for the LSST Data Management System.
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

import os
import logging
import logging.handlers
import asyncio
import pathlib
import posixpath
import warnings
import time

try:
    import aiohttp  # $ pip install aiohttp
    _with_aiohttp = True
except ModuleNotFoundError:
    warnings.warn('aiohttp is not installed. May limit or prevent use of some utility methods. '
                  'You can install it with $pip install aiohttp')
    _with_aiohttp = False
from contextlib import closing
import datetime

try:
    from urlparse import urlsplit
    from urllib import unquote
except ImportError:  # Python 3
    from urllib.parse import urlsplit, unquote

__all__ = ['get_scripts_dir', 'url2filename', 'wget', 'get_atcamera_filename',
           "EXTENSIVE", "TRACE", "WORDY", "configure_logging",
           "generate_logfile", "set_log_levels"]

# Extra INFO levels
WORDY = 15
# Extra DEBUG levels
EXTENSIVE = 5
TRACE = 2

DETAIL_LEVEL = {
    0: logging.ERROR,
    1: logging.INFO,
    2: WORDY,
    3: logging.DEBUG,
    4: EXTENSIVE,
    5: TRACE
}

MAX_CONSOLE = 3
MIN_FILE = 3
MAX_FILE = 5


def get_scripts_dir():
    """Get the absolute path to the scripts directory.

    Returns
    -------
    scripts_dir : `pathlib.Path`
        Absolute path to the specified scripts directory.
    """
    # 4 for python/lsst/ts/standardscripts
    return pathlib.Path(__file__).resolve().parents[4] / "scripts"


def url2filename(url):
    """Return basename corresponding to url.
    >>> print(url2filename('http://example.com/path/to/file%C3%80?opt=1'))
    fileÀ
    >>> print(url2filename('http://example.com/slash%2fname')) # '/' in name
    Traceback (most recent call last):
    ...
    ValueError
    """
    urlpath = urlsplit(url).path
    basename = posixpath.basename(unquote(urlpath))
    if (os.path.basename(basename) != basename or
            unquote(posixpath.basename(urlpath)) != basename):
        raise ValueError  # reject '%2f' or 'dir%5Cbasename.ext' on Windows
    return basename


@asyncio.coroutine
def wget(url, chunk_size=1 << 15):
    """
    A coroutine method to download images using asyncio.

    Parameters
    ----------
    url
    chunk_size

    Returns
    -------
    filename: string

    """
    if not _with_aiohttp:
        raise ImportError("aiohttp not available.")

    filename = url2filename(url)
    logging.info('downloading %s', filename)
    with closing(aiohttp.ClientSession()) as session:
        response = yield from session.get(url)
        with closing(response), open(filename, 'wb') as file:
            while True:  # save file
                chunk = yield from response.content.read(chunk_size)
                if not chunk:
                    break
                file.write(chunk)
        logging.info('done %s', filename)

    return filename


def get_atcamera_filename(increment=True):
    """
    A utility function to generate file names for ATCamera.
    This function assumes the file created in tmp_file
    was written by this function. No error handling exists should the file be
    modified or created via another method.

    Parameters
    ----------
    increment: bool : Should internal counter be incremented? (Default=True)

    Returns
    -------
    filename: string

    """
    # FIXME: This could probably be an environment variable or something
    tmp_file = '/tmp/atcamera_filename_current.dat'

    def time_stamped(fname_suffix, fmt='AT-O-%Y%m%d-{fname:05}'):
        return datetime.datetime.now().strftime(fmt).format(fname=fname_suffix)

    # today's format
    number = 0  # assume zero for the moment
    file_date = time_stamped(number).split('-')[2]

    # Check to see if a file exists with a past filename
    if os.path.exists(tmp_file):
        # read in the file
        fh = open(tmp_file, 'r')
        first_line = (fh.readline())
        logging.info('Previous line in existing file {}'.format(first_line))

        # check to see if the date is the same
        logging.debug('file_date is: {}'.format(file_date))
        logging.debug('first_line is: {}'.format(first_line))
        if file_date in first_line:
            # grab file number and augment it
            old_num = first_line.split(',')[1]
            logging.debug('Previous Image number was: {}'.format(old_num))
            number = 1+int(old_num) if increment else number
            logging.info('Incrementing from file to: {}'.format(number))
            fh.close()

        # Delete the file
        os.remove(tmp_file)

    # write a file with the new data
    fh = open(tmp_file, 'w')
    lines_of_text = [str(file_date)+','+str(number)]
    fh.writelines(lines_of_text)
    fh.close()

    fname = time_stamped(number)
    logging.info('Newly generated filename: {}'.format(fname))
    return fname


def generate_logfile(basename="sequence"):
    """Generate a log file name based on current time.
    """
    timestr = time.strftime("%Y-%m-%d_%H:%M:%S")
    log_path = os.path.expanduser('~/.{}/log'.format(basename))
    if not os.path.exists(log_path):
        os.makedirs(log_path)
    logfilename = os.path.join(log_path, "%s.%s.log" % (basename, timestr))
    return logfilename


def configure_logging(options, logfilename=None):
    """Configure the logging for the system.

    Parameters
    ----------
    options : argparse.Namespace
        The options returned by the ArgumentParser instance.argparse.
    logfilename : str
        A name, including path, for a log file.
    log_port : int, optional
        An alternate port for the socket logger.
    """
    console_detail, file_detail = set_log_levels(options.verbose)
    console_detail = max(console_detail, 1)
    main_level = max(console_detail, file_detail)

    log_format = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    if options.console_format is None:
        console_format = log_format
    else:
        console_format = options.console_format

    logging.basicConfig(level=DETAIL_LEVEL[main_level], format=console_format)
    logging.captureWarnings(True)
    # Remove existing console logger as it will double up messages
    # when levels match.
    logging.getLogger().removeHandler(logging.getLogger().handlers[0])

    logging.addLevelName(WORDY, 'WORDY')
    logging.addLevelName(EXTENSIVE, 'EXTENSIVE')
    logging.addLevelName(TRACE, 'TRACE')

    ch = logging.StreamHandler()
    ch.setLevel(DETAIL_LEVEL[console_detail])
    ch.setFormatter(logging.Formatter(console_format))
    logging.getLogger().addHandler(ch)

    log_file = logging.FileHandler(logfilename)
    log_file.setFormatter(logging.Formatter(log_format))
    log_file.setLevel(DETAIL_LEVEL[file_detail])
    logging.getLogger().addHandler(log_file)


def set_log_levels(verbose=0):
    """Set detail levels for console and file logging systems.

    This function sets the detail levels for console and file (via socket)
    logging systems. These levels are keys into the DETAIL_LEVEL dictionary.

    Parameters
    ----------
    verbose : int
        The requested verbosity level.

    Returns
    -------
    (int, int)
        A tuple containing:

        * the console detail level
        * the file detail level
    """
    console_detail = MAX_CONSOLE if verbose > MAX_CONSOLE else verbose

    file_detail = MIN_FILE if verbose < MIN_FILE else verbose
    file_detail = MAX_FILE if file_detail > MAX_FILE else file_detail

    return console_detail, file_detail
