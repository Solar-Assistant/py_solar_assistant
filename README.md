# py_solar_assistant

Python client for SolarAssistant. Also available in [Go](https://github.com/Solar-Assistant/go_solar_assistant).

## Installation

```bash
pip install py-solar-assistant
```

Requires Python 3.12+.

## Cloud API

Interact with the SolarAssistant cloud API. All endpoints require an API key — generate one at [solar-assistant.io/user/edit#api](https://solar-assistant.io/user/edit#api).

```python
from py_solar_assistant import SolarAssistantClient, list_sites, authorize_site

async with SolarAssistantClient("<api_key>") as client:
    sites = await list_sites(client)
```

### List sites

```python
sites = await list_sites(client)
```

Filter by inverter, battery, name, and more:

```python
sites = await list_sites(client, inverter="srne", limit=50, offset=20)
```

Common filters:

| Key | Example |
|-----|---------|
| `name` | `name="my-site"` |
| `inverter` | `inverter="srne"` |
| `battery` | `battery="daly"` |
| `inverter_params_output_power` | `inverter_params_output_power="5000"` |
| `last_seen_after` | `last_seen_after="2026-01-01"` |
| `build_date_after` | `build_date_after="2026-02-26"` |
| `limit` | `limit=50` |
| `offset` | `offset=20` |

### Authorize a site

Returns a short-lived token and connection details for a site. The token works for both cloud and local connections.

```python
auth = await authorize_site(client, site_id)
# auth.host, auth.site_id, auth.site_key, auth.token, auth.local_ip
```

---

## Device — REST

Read and write metrics directly on a SolarAssistant unit via REST.

### Local connection

```python
from py_solar_assistant import DeviceClient

async with DeviceClient("192.168.1.100", password="<web-password>") as c:
    ...
```

### Cloud-proxied connection

First obtain connection details via [authorize_site](#authorize-a-site):

```python
async with DeviceClient(
    auth.host,
    token=auth.token,
    site_id=auth.site_id,
    site_key=auth.site_key,
    scheme="https",
) as c:
    ...
```

### Read metrics

```python
# All metrics
metrics = await c.get_metrics()

# Filtered by topic glob — multiple topics are fetched and deduplicated
metrics = await c.get_metrics("battery_1/*", "total/pv_power")
```

### Write a metric

```python
await c.set_metric("inverter_1/charge_current_limit", "20")
```

### Standalone functions

For one-off calls without connection reuse:

```python
from py_solar_assistant import get_device_metrics, set_metric

metrics = await get_device_metrics("192.168.1.100", password="<web-password>")
await set_metric("192.168.1.100", "inverter_1/charge_current_limit", "20", password="<web-password>")
```

---

## Device — WebSocket

Stream live metrics via WebSocket.

### Cloud connection

First obtain connection details via [authorize_site](#authorize-a-site):

```python
import asyncio
from py_solar_assistant import SolarAssistantClient, authorize_site, connect, Options

async def main():
    async with SolarAssistantClient("<api_key>") as client:
        auth = await authorize_site(client, site_id)

    sock = await connect(Options(
        host=auth.host,
        token=auth.token,
        site_id=auth.site_id,
        site_key=auth.site_key,
        local_ip=auth.local_ip,  # if set, tries local network first and falls back to cloud
    ))

    await sock.subscribe_metrics(
        lambda m: print(f"{m.device}/{m.name} = {m.value} {m.unit}")
    )
    try:
        await sock.listen()  # blocks until disconnected
    finally:
        await sock.close()

asyncio.run(main())
```

### Direct local connection (no cloud)

Connect using the unit's web password, no cloud account required:

```python
sock = await connect(Options(
    local_ip="192.168.1.100",
    password="<web-password>",
))
```

### Topic filters

Subscribe to specific topics with optional server-side throttling:

```python
from py_solar_assistant import TopicFilter

await sock.subscribe_metrics(
    handler,
    TopicFilter(topic="total/*"),
    TopicFilter(topic="inverter_*/load_power"),
    TopicFilter(topic="battery_*/voltage", max_frequency_s=10),
)
```

If no filters are passed the server applies a default set of common metrics:

```
total/*
battery_*/voltage
battery_*/state_of_charge
battery_*/power
battery_*/temperature
inverter_*/pv_power
inverter_*/load_power
inverter_*/grid_power
inverter_*/device_mode
inverter_*/temperature
```

Only metrics in groups `Info`, `Status`, and `Settings` are sent.

### Write a setting

Send a setting change over the WebSocket and wait for the result:

```python
await sock.set_setting("inverter_1/power_mode", "Off grid with relay")
```

Raises `ValueError` if the device rejects the value.

### Options

| Field | Type | Description |
|-------|------|-------------|
| `host` | `str` | Hostname or `host:port` of the cloud proxy. |
| `token` | `str` | JWT from `authorize_site`. Required for cloud and local-fallback connections. |
| `password` | `str` | Web password for direct local connections. |
| `site_id` | `int` | Required for cloud connections. |
| `site_key` | `str` | Required for cloud connections. |
| `local_ip` | `str` | If set, tries local network first and falls back to `host`. |
| `verbose` | `bool` | Log all WebSocket frames at DEBUG level (via Python `logging`). |

### Advanced: raw channel messages

```python
sock.subscribe("*", "*", lambda msg: print(msg.topic, msg.event, msg.payload))
```

## Examples

Runnable scripts are in the [`examples/`](examples/) folder:

| Script | Description |
|--------|-------------|
| [`rest_read.py`](examples/rest_read.py) | Fetch all metrics once via REST and print them grouped by device |
| [`rest_set.py`](examples/rest_set.py) | Write a metric value via REST |
| [`websocket_read.py`](examples/websocket_read.py) | Stream live metrics via WebSocket until Ctrl+C |
| [`websocket_set.py`](examples/websocket_set.py) | Write a setting via WebSocket |

## License

Apache 2.0 — see [LICENSE](LICENSE).

This licence covers the Python client library in this repository only. The SolarAssistant platform — including the downloadable device software and cloud infrastructure — is proprietary and distributed under separate terms.
