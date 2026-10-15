"""Deprecated: this module moved to ``tokenops.framework.pricing``."""

import sys
import warnings

from tokenops.framework import pricing as _module

warnings.warn(
    "tokenops.control.pricing moved to tokenops.framework.pricing; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
