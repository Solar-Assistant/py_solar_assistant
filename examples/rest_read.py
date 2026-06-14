"""REST example: fetch all metrics from a local SolarAssistant device."""

import asyncio

import py_solar_assistant as sa

HOST = "192.168.1.100"
PASSWORD = "your-local-password"


async def main() -> None:
    metrics = await sa.get_device_metrics(HOST, password=PASSWORD)

    print(f"Connected to {HOST} — {len(metrics)} metrics received\n")

    current_device = None
    for m in metrics:
        if m.device != current_device:
            current_device = m.device
            label = m.device if not m.number else f"{m.device} #{m.number}"
            print(f"--- {label} ---")
        unit = f" {m.unit}" if m.unit else ""
        print(f"  {m.name}: {m.value}{unit}")


if __name__ == "__main__":
    asyncio.run(main())
