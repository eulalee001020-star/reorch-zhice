"""External customer-system adapters."""

from app.adapters.base_adapter import (
    AdapterCapabilities,
    AdapterWritebackResult,
    BaseCustomerAdapter,
)
from app.adapters.csv_adapter import CSVAdapter
from app.adapters.mock_adapter import MockAdapter
from app.adapters.rest_adapter import RESTAdapter, RESTEndpointConfig
from app.adapters.mapping_validator import (
    CanonicalDataset,
    MappingValidationIssue,
    MappingValidationReport,
    validate_canonical_dataset,
    validate_customer_payloads,
)

__all__ = [
    "AdapterCapabilities",
    "AdapterWritebackResult",
    "BaseCustomerAdapter",
    "CSVAdapter",
    "MockAdapter",
    "RESTAdapter",
    "RESTEndpointConfig",
    "CanonicalDataset",
    "MappingValidationIssue",
    "MappingValidationReport",
    "validate_canonical_dataset",
    "validate_customer_payloads",
]
