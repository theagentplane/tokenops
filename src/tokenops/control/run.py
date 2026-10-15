"""Deprecated: this module moved to ``tokenops.capabilities.run``."""

import sys
import warnings

from tokenops.capabilities import run as _module

warnings.warn(
    "tokenops.control.run moved to tokenops.capabilities.run; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
