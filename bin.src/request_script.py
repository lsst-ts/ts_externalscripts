#!/usr/bin/env python

import argparse
import logging
import asyncio

import salobj
import SALPY_ScriptLoader
import SALPY_Script

from lsst.ts.salscripts.utils import generate_logfile, configure_logging, set_log_levels
from lsst.ts.salscripts import __version__

__all__ = ["main"]


def create_parser():
    """Create parser
    """
    description = ["Utility to request scripts to be run by script loader."]

    parser = argparse.ArgumentParser(usage="run_sequence.py [options]",
                                     description=" ".join(description),
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("-v", "--verbose", dest="verbose", action='count', default=0,
                        help="Set the verbosity for the console logging.")
    parser.add_argument("-c", "--console-format", dest="console_format", default=None,
                        help="Override the console format.")
    parser.add_argument("-s", "--script", dest="script", default=None, type=str,
                        help="Specify the name of the script.")
    parser.add_argument("-e", '--external', dest='external', action='store_true',
                        help="Uses external script rather then internal. Default is internal.")
    parser.add_argument("-l", "--list", dest="list", action="store_true",
                        help="List available scripts.")
    parser.add_argument("--config", dest="script_config", default=None, type=str,
                        help="Filename with the configuration parameters for the requested script.")

    return parser


async def main(args):
    """Load and run a script from script loader.

    Parameters
    ----------
    args

    Returns
    -------

    """
    logfilename = generate_logfile()
    configure_logging(args, logfilename)

    logger = logging.getLogger("script")
    logger.info("logfile=%s", logfilename)

    script_loader = salobj.Remote(SALPY_ScriptLoader)

    request_list_task = await script_loader.cmd_list_available.start(script_loader.cmd_list_available.DataType())

    if request_list_task.ack.ack != script_loader.salinfo.lib.SAL__CMD_COMPLETE:
        raise IOError("Could not get list of scripts from script loader.")

    script_list = await script_loader.evt_available_scripts.next(timeout=1.)

    if args.list:
        logger.info("Listing all available scripts.")

        logger.info('List of external scripts:')
        for script in script_list.external.split(':'):
            logger.info('\t - %s', script)

        logger.info('List of internal scripts:')
        for script in script_list.internal.split(':'):
            logger.info('\t - %s', script)

        return 0

    if not args.external and args.script not in script_list.internal:
        logging.error('Requested script %s not in the list of internal scripts.', args.script)
        return -1
    elif args.external and args.script not in script_list.external:
        logging.error('Requested script %s not in the list of external scripts.', args.script)
        return -1

    # If we arrive at this point, we are good to go

    # Preparing to load script
    load_script_topic = script_loader.cmd_load.DataType()
    load_script_topic.is_standard = not args.external
    load_script_topic.path = args.script
    load_script_topic.config = ""  # Todo: Load configuration from args.config

    info_coro = script_loader.evt_script_info.next(timeout=2)

    task = await script_loader.cmd_load.start(load_script_topic, timeout=30.)

    if task.ack.ack != script_loader.salinfo.lib.SAL__CMD_COMPLETE:
        raise IOError("Could not start script %s on script loader: %i %i %s." % (args.script,
                                                                                 task.ack.ack,
                                                                                 task.ack.error,
                                                                                 task.ack.result))

    script_info = await task

    # Now initialize the remote script communication

    remote_script = salobj.Remote(SALPY_Script, script_info.index)

    # Set the logging to the same level as here

    logging_topic = remote_script.cmd_set_logging.DataType()
    logging_topic.level = set_log_levels(args.verbose)[0]

    task_setlog = await remote_script.cmd_set_logging.start(logging_topic, timeout=5.)

    if task_setlog.ack.ack != script_loader.salinfo.lib.SAL__CMD_COMPLETE:
        logger.warning('Could not set logging level on the script: %i %i %s',
                       task_setlog.ack.ack,
                       task_setlog.ack.error,
                       task_setlog.ack.result)

    task_run = await remote_script.cmd_run.start(remote_script.cmd_run.DataType())

    if task_run.ack.ack == script_loader.salinfo.lib.SAL__CMD_COMPLETE:
        logger.info('Script completed successfully')
    else:
        logger.info('Script failed with %i %i %s',
                    task_run.ack.ack,
                    task_run.ack.error,
                    task_run.ack.result
                    )

if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    loop.run_until_complete(main(args))
