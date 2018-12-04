#!/usr/bin/env python

import argparse
import logging
import asyncio
import yaml

from lsst.ts import salobj
import SALPY_ScriptQueue
# import SALPY_ScriptLoader
# import SALPY_Script

from lsst.ts.salscripts.utils import generate_logfile, configure_logging
from lsst.ts.salscripts import __version__

__all__ = ["main"]

script_state = ['Loading', 'Configured', 'Running', 'Complete', 'Failed', 'Terminated']


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
    parser.add_argument("--show", dest="show", action="store_true",
                        help="Show queued tasks.")
    parser.add_argument("--pause", dest="pause", action="store_true",
                        help="Pause queue.")
    parser.add_argument("--resume", dest="resume", action="store_true",
                        help="Resume queue.")
    parser.add_argument("--stop", dest="stop", default=None, type=int,
                        help="Gently stop running script, giving it a chance to interrupt running tasks.")
    parser.add_argument("--terminate", dest="terminate", default=None, type=int,
                        help="Forcibly terminate running script.")
    parser.add_argument("--remove", dest="remove", default=None, nargs='+', type=int,
                        help="Remove item from queue.")
    parser.add_argument("--requeue", dest="requeue", default=None, nargs='+', type=int,
                        help="Requeue item.")
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

    script_queue = salobj.Remote(SALPY_ScriptQueue, 1)

    # queue_summary_state_coro = script_queue.evt_summaryState.next(flush=True,timeout=10., flush=False)

    # start = await script_queue.cmd_start.start(script_queue.cmd_start.DataType())
    # enable = await script_queue.cmd_enable.start(script_queue.cmd_enable.DataType())

    available_scripts_coro = script_queue.evt_availableScripts.next(flush=True,
                                                                    timeout=10.)

    topic = script_queue.cmd_showAvailableScripts.DataType()
    request_list_task = await script_queue.cmd_showAvailableScripts.start(topic)

    if request_list_task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
        raise IOError("Could not get list of scripts from script loader.")

    script_list = await available_scripts_coro

    if args.list:
        logger.info("Listing all available scripts.")

        logger.info('List of external scripts:')
        for script in script_list.external.split(':'):
            logger.info('\t - %s', script)

        logger.info('List of standard scripts:')
        for script in script_list.standard.split(':'):
            logger.info('\t - %s', script)

        return 0

    if args.pause:
        logger.info("Pausing queue.")
        pause_task = await script_queue.cmd_pause.start(script_queue.cmd_pause.DataType())
        if pause_task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not pause queue. Got %i, %i, %s" % (pause_task.ack.ack,
                                                                     pause_task.ack.error,
                                                                     pause_task.ack.result))

        return 0
    elif args.resume:
        logger.info('Resuming queue.')
        resume_task = await script_queue.cmd_resume.start(script_queue.cmd_resume.DataType())
        if resume_task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not pause queue. Got %i, %i, %s" % (resume_task.ack.ack,
                                                                     resume_task.ack.error,
                                                                     resume_task.ack.result))

        return 0
    elif args.stop is not None:
        logger.info('Stopping script %i.', args.stop)
        topic = script_queue.cmd_stop.DataType()
        topic.salIndex = args.stop
        stop_task = await script_queue.cmd_stop.start(topic)
        if stop_task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not stop script. Got %i, %i, %s" % (stop_task.ack.ack,
                                                                     stop_task.ack.error,
                                                                     stop_task.ack.result))

        return 0

    elif args.terminate is not None:
        logger.info('Terminating script %i.', args.terminate)
        topic = script_queue.cmd_terminate.DataType()
        topic.salIndex = args.terminate
        terminate_task = await script_queue.cmd_terminate.start(topic)
        if terminate_task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not terminate script. Got %i, %i, %s" % (terminate_task.ack.ack,
                                                                          terminate_task.ack.error,
                                                                          terminate_task.ack.result))

        return 0

    elif args.show:
        logger.info("Showing tasks in the queue.")
        queue_coro = script_queue.evt_queue.next(flush=True, timeout=10.)

        topic = script_queue.cmd_showQueue.DataType()
        request_queue = await script_queue.cmd_showQueue.start(topic)

        if request_queue.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not get queue.")

        queue = await queue_coro

        queue_txt = '\nItems on queue:\n' if queue.length > 0 else '\nNo items on queue.'

        for i in range(queue.length):
            info_coro = script_queue.evt_script.next(flush=True,
                                                     timeout=10.)
            topic = script_queue.cmd_showScript.DataType()
            topic.salIndex = queue.salIndices[i]
            await script_queue.cmd_showScript.start(topic)

            info = await info_coro

            s_type = 'Standard' if info.isStandard else 'External'
            queue_txt += '\t[salIndex:%i][%s][path:%s]' \
                         '[duration:%.2f][state:%s]\n' % (queue.salIndices[i],
                                                          s_type,
                                                          info.path,
                                                          info.duration,
                                                          script_state[info.processState - 1]
                                                          )

        queue_txt += '\nItems on past queue:\n' if queue.pastLength > 0 else '\nNo items on past queue.'

        for i in range(queue.pastLength):
            info_coro = script_queue.evt_script.next(flush=True,
                                                     timeout=10.)
            topic = script_queue.cmd_showScript.DataType()
            topic.salIndex = queue.pastSalIndices[i]
            await script_queue.cmd_showScript.start(topic)

            info = await info_coro

            s_type = 'Standard' if info.isStandard else 'External'
            queue_txt += '\t[salIndex:%i][%s][path:%s]' \
                         '[duration:%.2f][state:%s]\n' % (queue.pastSalIndices[i],
                                                          s_type,
                                                          info.path,
                                                          info.duration,
                                                          script_state[info.processState - 1]
                                                          )
        current_running = 'None'
        if queue.currentSalIndex > 0:
            info_coro = script_queue.evt_script.next(flush=True,
                                                     timeout=10.)
            topic = script_queue.cmd_showScript.DataType()
            topic.salIndex = queue.currentSalIndex
            await script_queue.cmd_showScript.start(topic)

            info = await info_coro

            s_type = 'Standard' if info.isStandard else 'External'

            current_running = '[salIndex:%i][%s][path:%s]' \
                              '[duration:%.2f][state:%s]' % (queue.currentSalIndex,
                                                             s_type,
                                                             info.path,
                                                             info.duration,
                                                             script_state[info.processState - 1]
                                                             )

        logger.info('Queue state: %s', 'Running' if queue.running else 'Stopped')
        logger.info('Current running: %s', current_running)
        logger.info('Current queue size: %i', queue.length)
        logger.info('Past queue size: %i', queue.pastLength)
        logger.info(queue_txt)

        return 0

    if not args.external and args.script is not None and args.script not in script_list.standard:
        logging.error('Requested script %s not in the list of internal scripts.', args.script)
        return -1
    elif args.external and args.script is not None and args.script not in script_list.external:
        logging.error('Requested script %s not in the list of external scripts.', args.script)
        return -1

    # If we arrive at this point, we are good to go

    # Reading in input file
    config = ""
    if args.script_config is not None:
        logger.debug("Reading configuration from %s", args.script_config)
        with open(args.script_config, 'r') as stream:
            yconfig = yaml.load(stream)
            config = yaml.safe_dump(yconfig)
            logger.debug('Configuration: %s', config)
    else:
        logger.debug("No configuration file.")

    # Preparing to load script
    if args.script is not None:
        load_script_topic = script_queue.cmd_add.DataType()
        load_script_topic.isStandard = not args.external
        load_script_topic.path = args.script
        load_script_topic.config = config  # Todo: Load configuration from args.config
        load_script_topic.location = 2  # should be last

        # info_coro = script_queue.evt_scriptInfo.next(flush=True,timeout=10)

        task = await script_queue.cmd_add.start(load_script_topic, timeout=30.)

        if task.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
            raise IOError("Could not start script %s on script loader: %i %i %s." % (args.script,
                                                                                     task.ack.ack,
                                                                                     task.ack.error,
                                                                                     task.ack.result))

    if args.requeue is not None:
        for index in args.requeue:
            requeue_topic = script_queue.cmd_requeue.DataType()
            requeue_topic.salIndex = index
            requeue_topic.location = 2  # should be last
            logger.debug('Requeuing %i', index)
            await script_queue.cmd_requeue.start(requeue_topic, timeout=30.)

    if args.remove is not None:
        for index in args.remove:
            remove_topic = script_queue.cmd_remove.DataType()
            remove_topic.salIndex = index
            logger.debug('Removing %i', index)
            remove = await script_queue.cmd_remove.start(remove_topic, timeout=30.)
            logger.debug('%i %i %s', remove.ack.ack, remove.ack.error, remove.ack.result)

    # script_info = await info_coro
    #
    # # Now initialize the remote script communication
    #
    # logger.debug('Got index %i', script_info.ind)
    # remote_script = salobj.Remote(SALPY_Script, script_info.ind)
    #
    # # Set the logging to the same level as here
    #
    # logging_topic = remote_script.cmd_setLogging.DataType()
    # logging_topic.level = set_log_levels(args.verbose)[0]
    #
    # task_setlog = await remote_script.cmd_setLogging.start(logging_topic, timeout=5.)
    #
    # if task_setlog.ack.ack != script_queue.salinfo.lib.SAL__CMD_COMPLETE:
    #     logger.warning('Could not set logging level on the script: %i %i %s',
    #                    task_setlog.ack.ack,
    #                    task_setlog.ack.error,
    #                    task_setlog.ack.result)
    #
    # task_run = await remote_script.cmd_run.start(remote_script.cmd_run.DataType())
    #
    # if task_run.ack.ack == script_queue.salinfo.lib.SAL__CMD_COMPLETE:
    #     logger.info('Script completed successfully')
    # else:
    #     logger.info('Script failed with %i %i %s',
    #                 task_run.ack.ack,
    #                 task_run.ack.error,
    #                 task_run.ack.result
    #                 )

if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()

    loop = asyncio.get_event_loop()

    loop.run_until_complete(main(args))
