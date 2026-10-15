"""Deprecated: this module moved to ``tokenops.framework.policies.time_budget``."""

import sys
import warnings

from tokenops.framework.policies import time_budget as _module

warnings.warn(
    "tokenops.control.policies.time_budget moved to tokenops.framework.policies.time_budget; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
