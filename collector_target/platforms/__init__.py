"""Typed provider adapter boundary and registry."""

from .registry import AdapterRegistry, DEFAULT_ADAPTER_REGISTRY, build_adapter

__all__ = ["AdapterRegistry", "DEFAULT_ADAPTER_REGISTRY", "build_adapter"]
