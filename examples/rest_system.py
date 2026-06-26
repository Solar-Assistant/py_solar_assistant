"""REST example: read a SolarAssistant unit's system metrics.

``GET /api/v1/system`` exists only on newer SolarAssistant builds. An older unit
returns ``404``, which raises ``SolarAssistantError`` - catch it to detect old
firmware rather than relying on a special return value.
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
            print(f"{HOST} runs a build without /api/v1/system")
            return
        raise

    print(f"Connected to {HOST} - {len(rows)} system metrics received\n")
    for m in rows:
        unit = f" {m.unit}" if m.unit else ""
        print(f"  {m.name}: {m.value}{unit}")


if __name__ == "__main__":
    asyncio.run(main())
