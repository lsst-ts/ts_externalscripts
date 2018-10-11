import os
import logging
import asyncio
import posixpath
import aiohttp  # $ pip install aiohttp
from contextlib import closing
import datetime

try:
    from urlparse import urlsplit
    from urllib import unquote
except ImportError:  # Python 3
    from urllib.parse import urlsplit, unquote

__all__ = ['url2filename', 'wget', 'get_atcamera_filename']

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
def wget(url, chunk_size=1<<15):
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
    # FIXME: This could probably be an environment variable or something like that.
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
