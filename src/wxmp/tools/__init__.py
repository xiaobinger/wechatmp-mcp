# -*- coding: utf-8 -*-
"""Importing this package registers every MCP tool."""

from . import account, drafts, health, material, records, tietu  # noqa: F401

__all__ = ["account", "drafts", "health", "material", "records", "tietu"]