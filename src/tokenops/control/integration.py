"""Deprecated: this module moved to ``tokenops.capabilities.integration``."""

import sys
import warnings

from tokenops.capabilities import integration as _module

warnings.warn(
    "tokenops.control.integration moved to tokenops.capabilities.integration; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
