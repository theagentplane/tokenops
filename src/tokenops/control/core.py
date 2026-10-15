"""Deprecated: this module moved to ``tokenops.framework.core``."""

import sys
import warnings

from tokenops.framework import core as _module

warnings.warn(
    "tokenops.control.core moved to tokenops.framework.core; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
