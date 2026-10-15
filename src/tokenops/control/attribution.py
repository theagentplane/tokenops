"""Deprecated: this module moved to ``tokenops.framework.attribution``."""

import sys
import warnings

from tokenops.framework import attribution as _module

warnings.warn(
    "tokenops.control.attribution moved to tokenops.framework.attribution; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
