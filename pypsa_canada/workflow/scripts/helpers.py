import copy
import logging
import os
from pathlib import Path

import yaml
from snakemake.utils import update_config

logger = logging.getLogger(__name__)


def load_default_config():
    """
    Load the default configuration file.

    Returns
    -------
    dict
        Default configuration dictionary
    """
    # Get the path to the default config file
    # Try to find it relative to the workflow directory
    try:
        work_dir = Path.cwd()
        print(f"Current work dir:{work_dir}")
        default_config_path = work_dir / "config" / "default_config.yaml"

        if default_config_path.exists():
            with open(default_config_path) as f:
                return yaml.safe_load(f)
        else:
            logger.warning(f"Default config file not found at {default_config_path}")
            return {}
    except Exception as e:
        logger.warning(f"Could not load default config: {e}")
        return {}


def merge_with_defaults(config):
    """
    Merge the provided config with default values.

    Only adds missing keys from defaults, does not overwrite existing values.

    Parameters
    ----------
    config : dict
        User-provided configuration dictionary

    Returns
    -------
    dict
        Merged configuration dictionary
    """
    default_config = load_default_config()
    if default_config:
        # Use snakemake's update_config to merge, but reverse order
        # so user config takes precedence
        merged = copy.deepcopy(default_config)
        update_config(merged, config)
        return merged
    return config


def setup_script_logging(log_path, level=logging.DEBUG):
    """
    Configure logging for a Snakemake script so that ALL terminal output is
    captured in the rule log file.

    This sets ``level`` to DEBUG (capturing every logging level) and tees
    both ``sys.stdout`` and ``sys.stderr`` to ``log_path`` so that
    ``print()`` calls, solver output, and any other writes that bypass the

    Python logging system also appear in the log file.

    Parameters
    ----------
    log_path : str or Path
        Absolute path to the log file (typically ``snakemake.log[0]``).
    level : int, optional
        Logging level, defaults to ``logging.DEBUG``.
    """
    import sys

    log_path = str(log_path)
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    _log_fh = open(log_path, "w", encoding="utf-8", buffering=1)

    class _Tee:
        """Write to both the original stream and the log file."""

        def __init__(self, orig, extra):
            self._orig = orig
            self._extra = extra

        def write(self, s):
            self._orig.write(s)
            self._extra.write(s)

        def flush(self):
            self._orig.flush()
            self._extra.flush()

        def __getattr__(self, a):
            return getattr(self._orig, a)

    sys.stdout = _Tee(sys.stdout, _log_fh)
    sys.stderr = _Tee(sys.stderr, _log_fh)

    logging.basicConfig(
        level=level,
        handlers=[logging.StreamHandler(sys.stdout)],
        format="%(asctime)s %(levelname)s %(message)s",
    )
