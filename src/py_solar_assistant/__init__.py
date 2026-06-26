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
    get_device_metrics,
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

__version__ = "0.2.1"

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
