"""Deprecated: this module moved to ``tokenops.framework.engine``."""

import sys
import warnings

from tokenops.framework import engine as _module

warnings.warn(
    "tokenops.control.engine moved to tokenops.framework.engine; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
