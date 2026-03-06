"""Tests for interface module structure.

The interface implementations (CLI, Server, Email, Telegram) are Phase 6
deliverables.  These tests verify the package structure is in place and
the modules are importable, so Phase 6 has a clean starting point.
"""

from __future__ import annotations

import importlib

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Module importability
# ═══════════════════════════════════════════════════════════════════════════════

class TestInterfaceModulesExist:
    """Verify every interface module can be imported without errors."""

    @pytest.mark.parametrize("module_name", [
        "ira.interfaces",
        "ira.interfaces.cli",
        "ira.interfaces.server",
        "ira.interfaces.email_processor",
        "ira.interfaces.telegram_bot",
    ])
    def test_module_importable(self, module_name: str):
        mod = importlib.import_module(module_name)
        assert mod is not None


# ═══════════════════════════════════════════════════════════════════════════════
# Package __init__
# ═══════════════════════════════════════════════════════════════════════════════

class TestInterfacesPackage:
    def test_package_has_init(self):
        import ira.interfaces
        assert hasattr(ira.interfaces, "__name__")
        assert ira.interfaces.__name__ == "ira.interfaces"
