import sys
import argparse
import asyncio
import logging

import SALPY_Test
from lsst.ts.salobj import Remote, State, AckError


async def main(parsed):
    """Start a series of remotes and send commands to and listen for events
    from Test components.

    Parameters
    ----------
    parsed : Namespace
        Arguments parsed by argspaser.
    """

    log = logging.getLogger(__name__)

    def get_callback(index):
        def print_evt_scalars(data):
            print(f"index[{index}]: {data.int0}")
        return print_evt_scalars

    def get_callback_summary_state(index):
        def print_evt_scalars(data):
            print(f"index[{index}]:state: {State(data.summaryState)!r}")
        return print_evt_scalars

    print(f"** creating {parsed.n} remotes")
    remotes_list = []
    for i in range(parsed.n):
        remotes_list.append(Remote(SALPY_Test, i+1,
                                   include=["scalars", "summaryState",
                                            "setScalars", "setArrays"]))
        remotes_list[-1].evt_scalars.callback = get_callback(i+1)
        remotes_list[-1].evt_summaryState.callback = get_callback_summary_state(i+1)

    print("** start Test CSCs")

    try:
        await asyncio.gather(*[r.cmd_start.start(timeout=1.) for r in remotes_list],
                             return_exceptions=True)
        await asyncio.sleep(0.5)
    except AckError:
        print("** Could not start CSCs... continuing...")

    print("** enable Test CSCs")

    try:
        await asyncio.gather(*[r.cmd_enable.start(timeout=1.) for r in remotes_list],
                             return_exceptions=True)
        await asyncio.sleep(0.5)
    except AckError:
        print("** Could not enable CSCs... continuing...")

    print("**setting values")

    try:
        while True:
            cmd_list = []
            for i in range(len(remotes_list)):
                remotes_list[i].cmd_setScalars.set(int0=int(i)+1)
                cmd_list.append(remotes_list[i].cmd_setScalars.start(timeout=1.))
                cmd_list.append(remotes_list[i].cmd_setArrays.start(timeout=1.))

            print("** setScalars - start")
            await asyncio.gather(*cmd_list)
            print("** setScalars - done")

            await asyncio.sleep(parsed.wait_time)
    except KeyboardInterrupt as e:
        log.exception(e)
        await asyncio.sleep(0.5)

    print("** disable Test CSCs")

    await asyncio.gather(*[r.cmd_disable.start(timeout=1.) for r in remotes_list])
    await asyncio.sleep(0.5)

    print("** put Test CSCs in standby")

    await asyncio.gather(*[r.cmd_standby.start(timeout=1.) for r in remotes_list])
    await asyncio.sleep(0.5)


if __name__ == "__main__":

    arg_parser = argparse.ArgumentParser(prog="run")
    arg_parser.add_argument('n',
                            help="Number of Test components that are part of the test.",
                            type=int)
    arg_parser.add_argument('wait_time',
                            help="Time to wait between commands. If zero, will send commands as "
                                 "fast as it can. But still waits for the commands to be "
                                 "acknowledged.",
                            type=float)

    parsed = arg_parser.parse_args(sys.argv[1:])

    asyncio.get_event_loop().run_until_complete(main(parsed))
