import asyncio
import csv
import pathlib
from lsst.ts import salobj


async def main():
    moving_timeout = 45
    in_position = None

    def in_position_callback(evt_in_position):
        nonlocal in_position
        in_position = evt_in_position.inPosition
        log_file.write(f"{in_position}\n")

    def log_message_callback(evt_log_message):
        log_file.write(f"{evt_log_message.message}\n")

    def application_callback(tel_actuators):
        csv_writer.writerow({"x1": tel_actuators.calibrated[0],
                             "x2": tel_actuators.calibrated[1],
                             "x3": tel_actuators.calibrated[2],
                             "x4": tel_actuators.calibrated[3],
                             "x5": tel_actuators.calibrated[4],
                             "x6": tel_actuators.calibrated[5]})
    telemetry_file = open(pathlib.Path("~/camera_hexapod_3.1.1.csv").expanduser(), "w", newline="")
    log_file = open(pathlib.Path("~/camera_hexapod_3.1.1.txt").expanduser(), "w")
    csv_writer = csv.DictWriter(telemetry_file, fieldnames=["x1", "x2", "x3", "x4", "x5", "x6"])
    csv_writer.writeheader()

    camera_hexapod = salobj.Remote(domain=salobj.Domain(), name="Hexapod", index=1)
    camera_hexapod.tel_actuators.callback = application_callback
    camera_hexapod.evt_logMessage.callback = log_message_callback
    await salobj.set_summary_state(camera_hexapod, salobj.State.ENABLED, timeout=20)
    camera_hexapod.evt_inPosition.callback = in_position_callback

    await camera_hexapod.cmd_move.set_start(x=0, y=0, z=0, u=0, v=0, w=0, sync=True, timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660,
                                            y=0,
                                            z=7730,
                                            u=0.17,
                                            v=0,
                                            w=0,
                                            sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660,
                                            y=0,
                                            z=7730,
                                            u=-0.17,
                                            v=0, w=0,
                                            sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660,
                                            y=0,
                                            z=7730,
                                            u=0,
                                            v=0.17,
                                            w=0,
                                            sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660,
                                            y=0,
                                            z=7730,
                                            u=0,
                                            v=-0.17,
                                            w=0,
                                            sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660,
                                            y=0,
                                            z=-7730,
                                            u=0.17,
                                            v=0,
                                            w=0,
                                            sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660, y=0, z=-7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660, y=0, z=-7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=5660, y=0, z=-7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=7730, u=0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=-7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=-5660, y=0, z=-7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=7730, u=0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=-7730, u=0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=-7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=-7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=5660, z=-7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=7730, u=0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=-7730, u=0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=-7730, u=-0.17, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=-7730, u=0, v=0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=-5660, z=-7730, u=0, v=-0.17, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)
    await asyncio.sleep(moving_timeout)

    await camera_hexapod.cmd_move.set_start(x=0, y=0, z=0, u=0, v=0, w=0, sync=True,
                                            timeout=moving_timeout)
    while in_position is False:
        await asyncio.sleep(0.1)

    await salobj.set_summary_state(camera_hexapod, salobj.State.STANDBY, timeout=20)
    await camera_hexapod.close()
    telemetry_file.close()
    log_file.close()

if __name__ == "__main__":
    asyncio.run(main())
