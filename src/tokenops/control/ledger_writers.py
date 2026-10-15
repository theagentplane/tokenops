"""Deprecated: this module moved to ``tokenops.capabilities.ledger_writers``."""

import sys
import warnings

from tokenops.capabilities import ledger_writers as _module

warnings.warn(
    "tokenops.control.ledger_writers moved to tokenops.capabilities.ledger_writers; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
