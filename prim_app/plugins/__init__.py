"""Camera plugin system."""

import importlib
from typing import Any

from .camera_plugin_interface import CameraPluginInterface


def load_plugin(name: str, **kwargs: Any) -> CameraPluginInterface:
    """Dynamically load a camera plugin by name."""
    module_name = f"prim_app.plugins.{name}_plugin"
    module = importlib.import_module(module_name)
    for attr in dir(module):
        obj = getattr(module, attr)
        if isinstance(obj, type) and issubclass(obj, CameraPluginInterface) and obj is not CameraPluginInterface:
            return obj(**kwargs)
    raise ValueError(f"No camera plugin found in {module_name}")


__all__ = ["CameraPluginInterface", "load_plugin"]
