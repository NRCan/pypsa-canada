"""
Deprecation utilities for pypsa_canada

Provides decorators and functions for marking deprecated functionality
with helpful migration messages.
"""

import functools
import warnings
from collections.abc import Callable


def deprecated(
    reason: str | None = None,
    version: str | None = None,
    removed_in: str | None = None,
    alternative: str | None = None,
    category: type = DeprecationWarning,
) -> Callable:
    """
    Decorator to mark functions, methods, or classes as deprecated.

    Parameters
    ----------
    reason : str, optional
        Explanation of why the item is deprecated
    version : str, optional
        Version when deprecation started
    removed_in : str, optional
        Version when the item will be removed
    alternative : str, optional
        Suggested alternative to use instead
    category : Warning class, optional
        Warning category to use (default: DeprecationWarning)

    Returns
    -------
    Callable
        Decorated function with deprecation warning

    Examples
    --------
    >>> @deprecated(
    ...     reason="Use new API",
    ...     version="2.0",
    ...     removed_in="3.0",
    ...     alternative="new_function()"
    ... )
    ... def old_function():
    ...     pass
    """

    def decorator(obj: Callable) -> Callable:
        @functools.wraps(obj)
        def wrapper(*args, **kwargs):
            # Build deprecation message
            msg = f"'{obj.__name__}' is deprecated"

            if version:
                msg += f" since version {version}"

            if removed_in:
                msg += f" and will be removed in version {removed_in}"

            if reason:
                msg += f": {reason}"

            if alternative:
                msg += f"\nUse '{alternative}' instead."

            # Emit warning
            warnings.warn(msg, category=category, stacklevel=2)

            return obj(*args, **kwargs)

        # Mark the wrapper as deprecated for introspection
        wrapper._deprecated = True
        wrapper._deprecation_info = {
            "reason": reason,
            "version": version,
            "removed_in": removed_in,
            "alternative": alternative,
        }

        # Update docstring
        if wrapper.__doc__:
            deprecation_notice = ".. deprecated::"
            if version:
                deprecation_notice += f" {version}"
            deprecation_notice += "\n"
            if reason:
                deprecation_notice += f"   {reason}\n"
            if alternative:
                deprecation_notice += f"   Use {alternative} instead.\n"

            wrapper.__doc__ = f"{deprecation_notice}\n{wrapper.__doc__}"

        return wrapper

    return decorator


def warn_module_deprecated(
    module_name: str,
    reason: str | None = None,
    version: str | None = None,
    removed_in: str | None = None,
    alternative: str | None = None,
) -> None:
    """
    Emit a deprecation warning for an entire module.

    Call this at the top of a deprecated module's __init__.py or main file.

    Parameters
    ----------
    module_name : str
        Name of the deprecated module
    reason : str, optional
        Explanation of why the module is deprecated
    version : str, optional
        Version when deprecation started
    removed_in : str, optional
        Version when the module will be removed
    alternative : str, optional
        Suggested alternative module to use instead

    Examples
    --------
    >>> # At top of deprecated_module.py
    >>> from pypsa_canada.deprecation import warn_module_deprecated
    >>> warn_module_deprecated(
    ...     "deprecated_module",
    ...     reason="Replaced by new implementation",
    ...     version="2.0",
    ...     alternative="new_module"
    ... )
    """
    msg = f"Module '{module_name}' is deprecated"

    if version:
        msg += f" since version {version}"

    if removed_in:
        msg += f" and will be removed in version {removed_in}"

    if reason:
        msg += f": {reason}"

    if alternative:
        msg += f"\nUse '{alternative}' instead."

    warnings.warn(msg, DeprecationWarning, stacklevel=2)


def warn_script_deprecated(
    script_name: str,
    alternative_command: str | None = None,
    details: str | None = None,
    migration_guide: str | None = None,
) -> None:
    """
    Emit a detailed deprecation warning for scripts or CLI tools.

    Designed for user-facing scripts with clear migration paths.

    Parameters
    ----------
    script_name : str
        Name of the deprecated script
    alternative_command : str, optional
        Command to use instead
    details : str, optional
        Additional details about the deprecation
    migration_guide : str, optional
        Path or URL to migration documentation

    Examples
    --------
    >>> warn_script_deprecated(
    ...     "test_constraints.py",
    ...     alternative_command="pytest tests/ -v",
    ...     migration_guide="tests/QUICKSTART.md"
    ... )
    """
    msg = [
        "=" * 80,
        f"DEPRECATION WARNING: {script_name}",
        "=" * 80,
        "This script is deprecated and will be removed in a future version.",
    ]

    if alternative_command:
        msg.append("")
        msg.append("Please use the following instead:")
        msg.append(f"  {alternative_command}")

    if details:
        msg.append("")
        msg.append(details)

    if migration_guide:
        msg.append("")
        msg.append(f"Migration guide: {migration_guide}")

    msg.append("=" * 80)

    # Show warning prominently
    warnings.simplefilter("always", DeprecationWarning)
    warnings.warn("\n" + "\n".join(msg), DeprecationWarning, stacklevel=2)
    warnings.simplefilter("default", DeprecationWarning)


def is_deprecated(obj: Callable) -> bool:
    """
    Check if a function/method is marked as deprecated.

    Parameters
    ----------
    obj : Callable
        Function or method to check

    Returns
    -------
    bool
        True if deprecated, False otherwise

    Examples
    --------
    >>> @deprecated(version="2.0")
    ... def old_func():
    ...     pass
    >>> is_deprecated(old_func)
    True
    """
    return getattr(obj, "_deprecated", False)


def get_deprecation_info(obj: Callable) -> dict | None:
    """
    Get deprecation information for a function/method.

    Parameters
    ----------
    obj : Callable
        Function or method to inspect

    Returns
    -------
    dict or None
        Dictionary with deprecation info, or None if not deprecated

    Examples
    --------
    >>> @deprecated(version="2.0", alternative="new_func")
    ... def old_func():
    ...     pass
    >>> info = get_deprecation_info(old_func)
    >>> info['version']
    '2.0'
    """
    return getattr(obj, "_deprecation_info", None)
