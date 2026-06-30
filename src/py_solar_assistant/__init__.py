"""Python client for SolarAssistant — cloud API and real-time WebSocket."""

from ._errors import SolarAssistantError
from .cloud import (
    DEFAULT_BASE_URL,
    AuthorizeResponse,
    Site,
    SiteOwner,
    SolarAssistantClient,
    authorize_site,
    list_sites,
)
from .device import (
    DeviceClient,
    DeviceMetric,
    get_device_cpu_temperature,
    get_device_free_storage,
    get_device_metrics,
    get_device_site_id,
    get_device_software_version,
    get_device_system_metrics,
    set_metric,
)
from .socket import (
    ChannelError,
    ConnectError,
    Message,
    Metric,
    Options,
    Socket,
    TopicFilter,
    connect,
)

__version__ = "0.3.0"

__all__ = [  # noqa: RUF022  (grouped by client surface, not sorted alphabetically)
    "__version__",
    # Cloud API
    "DEFAULT_BASE_URL",
    "SolarAssistantClient",
    "SolarAssistantError",
    "Site",
    "SiteOwner",
    "AuthorizeResponse",
    "list_sites",
    "authorize_site",
    # Device REST
    "DeviceClient",
    "DeviceMetric",
    "get_device_metrics",
    "get_device_system_metrics",
    "get_device_site_id",
    "get_device_software_version",
    "get_device_cpu_temperature",
    "get_device_free_storage",
    "set_metric",
    # WebSocket
    "Options",
    "Socket",
    "Metric",
    "Message",
    "TopicFilter",
    "ConnectError",
    "ChannelError",
    "connect",
]
