"""WebSocket example: write a setting on a local SolarAssistant device.

Topic format matches the read topic, e.g. 'inverter_1/power_mode'.

Usage:
    python websocket_set.py inverter_1/power_mode "Off grid with relay"
"""
import asyncio
import sys

import py_solar_assistant as sa

HOST = "192.168.1.100"
PASSWORD = "your-local-password"


async def main() -> None:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <topic> <value>")
        print(f"  e.g. {sys.argv[0]} inverter_1/power_mode 'Off grid with relay'")
        sys.exit(1)

    topic, value = sys.argv[1], sys.argv[2]
    opts = sa.Options(local_ip=HOST, password=PASSWORD)

    print(f"Connecting to {HOST} …")
    sock = await sa.connect(opts)
    print(f"Connected\n")

    try:
        await sock.set_setting(topic, value)
        print(f"✓ Saved {topic!r} = {value!r}")
    except ValueError as e:
        print(f"✗ Error: {e}")
    finally:
        await sock.close()


if __name__ == "__main__":
    asyncio.run(main())
