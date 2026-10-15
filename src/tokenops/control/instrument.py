"""Deprecated: this module moved to ``tokenops.interfaces.instrument``."""

import sys
import warnings

from tokenops.interfaces import instrument as _module

warnings.warn(
    "tokenops.control.instrument moved to tokenops.interfaces.instrument; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
