"""Deprecated: this module moved to ``tokenops.interfaces.http``."""

import sys
import warnings

from tokenops.interfaces import http as _module

warnings.warn(
    "tokenops.control.http moved to tokenops.interfaces.http; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
