import sys
import argparse
import asyncio

import SALPY_Test
from lsst.ts.salobj import Remote, State


async def main(parsed):
    """Start a series of remotes and listen for events from Test components.

    Parameters
    ----------
    parsed : Namespace
        Arguments parsed by argspaser.

    """

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
        remotes_list.append(Remote(SALPY_Test, i+1))
        remotes_list[-1].evt_scalars.callback = get_callback(i+1)
        remotes_list[-1].evt_summaryState.callback = get_callback_summary_state(i+1)
    print("** done")


if __name__ == "__main__":

    arg_parser = argparse.ArgumentParser(prog="run")
    arg_parser.add_argument('n',
                            help="Number of Test components that are part of the test.",
                            type=int)

    parsed = arg_parser.parse_args(sys.argv[1:])

    asyncio.ensure_future(main(parsed))

    print("** waiting")
    asyncio.get_event_loop().run_forever()
