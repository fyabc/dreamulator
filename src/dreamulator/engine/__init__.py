"""Simulation engines for world building computations."""

from .base import BaseEngine, EngineResult

__all__ = ["BaseEngine", "EngineResult", "get_all_engines"]


def get_all_engines() -> list[type[BaseEngine]]:
    """Discover all concrete engine subclasses.

    Imports all modules in the engine package and collects any BaseEngine
    subclasses that have a non-default name.

    Returns:
        List of engine classes.
    """
    import importlib
    import pkgutil
    from pathlib import Path

    engine_dir = Path(__file__).parent
    engines: list[type[BaseEngine]] = []

    for module_info in pkgutil.iter_modules([str(engine_dir)]):
        if module_info.name == "base":
            continue
        try:
            module = importlib.import_module(f".{module_info.name}", package=__package__)
        except ImportError:
            continue

        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseEngine)
                and attr is not BaseEngine
                and getattr(attr, "name", "base") != "base"
            ):
                engines.append(attr)

    return engines
