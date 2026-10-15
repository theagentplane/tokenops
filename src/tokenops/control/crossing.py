"""Deprecated: this module moved to ``tokenops.capabilities.crossing``."""

import sys
import warnings

from tokenops.capabilities import crossing as _module

warnings.warn(
    "tokenops.control.crossing moved to tokenops.capabilities.crossing; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
