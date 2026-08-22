"""Logging setup for conlang.

Uses rich logging handler when available for colored, structured output.
Falls back to standard logging otherwise.
"""

import logging


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure the conlang logger.

    When ``rich`` is installed, uses :class:`rich.logging.RichHandler` for
    colored output and installs rich traceback rendering.  Falls back to
    standard :func:`logging.basicConfig` otherwise.

    Args:
        level: Logging level (default: INFO).

    Returns:
        Configured logger instance.
    """
    kwargs: dict = {}

    try:
        from rich.logging import RichHandler
        from rich.traceback import install

        install()
    except ImportError:
        pass
    else:
        kwargs["format"] = "%(message)s"
        kwargs["handlers"] = [RichHandler()]

    logging.basicConfig(datefmt="%m/%d %H:%M:%S", level=level, **kwargs)
    return logging.getLogger("conlang")
