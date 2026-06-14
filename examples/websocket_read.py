"""WebSocket example: stream real-time metrics from a local SolarAssistant device."""

import asyncio

import py_solar_assistant as sa

HOST = "192.168.1.100"
PASSWORD = "your-local-password"


def on_metric(m: sa.Metric) -> None:
    label = m.device if not m.number else f"{m.device} #{m.number}"
    unit = f" {m.unit}" if m.unit else ""
    print(f"[{label}] {m.name}: {m.value}{unit}", flush=True)


async def main() -> None:
    opts = sa.Options(local_ip=HOST, password=PASSWORD)

    print(f"Connecting to {HOST} …")
    sock = await sa.connect(opts)
    print("Connected — streaming metrics (Ctrl+C to stop)\n")

    try:
        await sock.subscribe_metrics(on_metric)
        await sock.listen()
    except KeyboardInterrupt:
        pass
    finally:
        await sock.close()


if __name__ == "__main__":
    asyncio.run(main())
