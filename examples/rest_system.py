"""REST example: read a SolarAssistant unit's system metrics.

System metrics exist only on newer SolarAssistant builds. A unit that predates
them returns ``404``, which raises ``SolarAssistantError`` - catch it to detect
old firmware rather than relying on a special return value.
"""

import asyncio

import py_solar_assistant as sa

HOST = "192.168.1.100"
PASSWORD = "your-local-password"


async def main() -> None:
    try:
        rows = await sa.get_device_system_metrics(HOST, password=PASSWORD)
    except sa.SolarAssistantError as err:
        if err.status == 404:
            print(f"{HOST} runs a build without system metrics")
            return
        raise

    print(f"Connected to {HOST} - {len(rows)} system metrics received\n")
    for m in rows:
        unit = f" {m.unit}" if m.unit else ""
        print(f"  {m.name}: {m.value}{unit}")


if __name__ == "__main__":
    asyncio.run(main())
