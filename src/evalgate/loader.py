"""Import user code from dotted paths (custom scorers and providers)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from evalgate.errors import ConfigError


def load_object(spec: str, root: Path | None = None, *, what: str = "object") -> Any:
    """Load ``package.module:attr`` (or ``package.module.attr``).

    ``root`` (the config directory) is put on ``sys.path`` so project-local modules
    such as ``my_scorers.py`` next to ``evalgate.yaml`` can be imported.
    """
    if ":" in spec:
        module_name, _, attr = spec.partition(":")
    else:
        module_name, _, attr = spec.rpartition(".")
    if not module_name or not attr:
        raise ConfigError(
            f"invalid {what} {spec!r}",
            hint="use the form 'module:name' or 'package.module.name'",
        )
    if root is not None:
        root_str = str(root.resolve())
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(
            f"could not import module {module_name!r} for {what} {spec!r}: {exc}",
            hint="check the module name and that it is importable from the config directory",
        ) from None
    try:
        return getattr(module, attr)
    except AttributeError:
        raise ConfigError(f"module {module_name!r} has no attribute {attr!r} ({what})") from None
