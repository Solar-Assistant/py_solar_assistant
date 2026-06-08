## v0.1.0 (2026-06-01)

Initial release of the SolarAssistant Python client.

### Feat

- Cloud API client: list/filter sites and authorize a site for cloud or local
  connections (`SolarAssistantClient`, `list_sites`, `authorize_site`).
- Device REST client: read and write metrics on a unit, locally or
  cloud-proxied (`DeviceClient`, `get_device_metrics`, `set_metric`).
- Real-time WebSocket streaming with topic filtering (`connect`, `Socket`,
  `Metric`, `TopicFilter`).
