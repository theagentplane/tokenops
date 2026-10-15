"""Deprecated: this module moved to ``tokenops.framework.usage``."""

import sys
import warnings

from tokenops.framework import usage as _module

warnings.warn(
    "tokenops.control.usage moved to tokenops.framework.usage; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
