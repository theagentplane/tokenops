"""Deprecated: this module moved to ``tokenops.framework.boundary``."""

import sys
import warnings

from tokenops.framework import boundary as _module

warnings.warn(
    "tokenops.control.boundary moved to tokenops.framework.boundary; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
