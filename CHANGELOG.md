## v0.2.1 (2026-06-14)

### Fix

- **deps**: cap aiohttp below 4.0 to avoid removed APIs

## v0.2.0 (2026-06-12)

### Feat

- **cloud**: add free-text site name search

### Fix

- redact credentials in verbose debug logs
- **device**: send site_id/site_key for cloud-proxy metric reads

## v0.1.1 (2026-06-10)

### Fix

- **socket**: surface phx_error and join failures instead of hanging
- **socket**: detect half-open connections via aiohttp heartbeat

### Refactor

- emit verbose debug output via logging instead of print

## v0.1.0 (2026-06-01)

Initial release of the SolarAssistant Python client.

### Feat

- Cloud API client: list/filter sites and authorize a site for cloud or local
  connections (`SolarAssistantClient`, `list_sites`, `authorize_site`).
- Device REST client: read and write metrics on a unit, locally or
  cloud-proxied (`DeviceClient`, `get_device_metrics`, `set_metric`).
- Real-time WebSocket streaming with topic filtering (`connect`, `Socket`,
  `Metric`, `TopicFilter`).
