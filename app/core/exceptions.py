"""Shared exception hierarchy for AlphaScope."""
from __future__ import annotations


class AlphaScopeError(Exception):
    """Base class for all AlphaScope application errors."""


class ProviderError(AlphaScopeError):
    """Base class for market data provider errors."""


class ProviderConnectionError(ProviderError):
    """Raised when a provider fails to connect or drops its connection."""


class ProviderNotConfiguredError(ProviderError):
    """Raised when a provider is selected but missing required configuration (e.g. API key)."""


class UnknownProviderError(ProviderError):
    """Raised when a normalizer receives an event from an unrecognized provider."""


class InvalidSymbolError(AlphaScopeError):
    """Raised when a symbol is not tracked by the current universe."""


class InsufficientDataError(AlphaScopeError):
    """Raised when there is not enough rolling market history to compute an indicator."""


class RiskCalculationError(AlphaScopeError):
    """Raised when a risk or position sizing calculation cannot be performed safely."""
