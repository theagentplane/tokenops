"""Deprecated: this module moved to ``tokenops.framework.ledger``."""

import sys
import warnings

from tokenops.framework import ledger as _module

warnings.warn(
    "tokenops.control.ledger moved to tokenops.framework.ledger; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
