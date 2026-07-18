"""Plugin registry with auto-discovery."""

from __future__ import annotations

import importlib
import sys
from typing import Dict, Type

from pxeos.plugins.base import OSPlugin


class PluginRegistry:

    def __init__(self) -> None:
        self._plugins: Dict[str, Type[OSPlugin]] = {}
        self._instances: Dict[str, OSPlugin] = {}

    def register(self, plugin_cls: Type[OSPlugin]) -> None:
        instance = plugin_cls()
        family = instance.os_family.lower()
        self._plugins[family] = plugin_cls
        self._instances[family] = instance

    def get(self, os_family: str) -> OSPlugin:
        family = os_family.lower()
        if family not in self._instances:
            raise ValueError(
                f"unknown os_family {os_family!r}; "
                f"available: {self.available}"
            )
        return self._instances[family]

    @property
    def available(self) -> list[str]:
        return sorted(self._plugins.keys())

    def discover(self) -> None:
        if sys.version_info >= (3, 12):
            from importlib.metadata import entry_points

            eps = entry_points(group="pxeos.plugins")
        elif sys.version_info >= (3, 10):
            from importlib.metadata import entry_points

            eps = entry_points(group="pxeos.plugins")
        else:
            from importlib.metadata import entry_points

            all_eps = entry_points()
            eps = all_eps.get("pxeos.plugins", [])

        for ep in eps:
            try:
                plugin_cls = ep.load()
                if (
                    isinstance(plugin_cls, type)
                    and issubclass(plugin_cls, OSPlugin)
                    and plugin_cls is not OSPlugin
                ):
                    self.register(plugin_cls)
            except Exception:
                pass

    def load_builtins(self) -> None:
        builtin_modules = [
            "pxeos.plugins.fedora",
            "pxeos.plugins.debian",
            "pxeos.plugins.ubuntu",
            "pxeos.plugins.suse",
            "pxeos.plugins.freebsd",
            "pxeos.plugins.dragonflybsd",
            "pxeos.plugins.openbsd",
            "pxeos.plugins.netbsd",
            "pxeos.plugins.arch",
            "pxeos.plugins.windows",
            "pxeos.plugins.tinycore",
        ]
        for mod_name in builtin_modules:
            try:
                mod = importlib.import_module(mod_name)
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, OSPlugin)
                        and attr is not OSPlugin
                    ):
                        self.register(attr)
            except ImportError:
                pass
