"""External customer-system adapters."""

from app.adapters.base_adapter import (
    AdapterCapabilities,
    AdapterWritebackResult,
    BaseCustomerAdapter,
)
from app.adapters.csv_adapter import CSVAdapter
from app.adapters.mock_adapter import MockAdapter
from app.adapters.rest_adapter import RESTAdapter, RESTEndpointConfig

__all__ = [
    "AdapterCapabilities",
    "AdapterWritebackResult",
    "BaseCustomerAdapter",
    "CSVAdapter",
    "MockAdapter",
    "RESTAdapter",
    "RESTEndpointConfig",
]
