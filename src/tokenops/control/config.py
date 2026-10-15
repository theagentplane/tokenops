"""Deprecated: this module moved to ``tokenops.framework.config``."""

import sys
import warnings

from tokenops.framework import config as _module

warnings.warn(
    "tokenops.control.config moved to tokenops.framework.config; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
