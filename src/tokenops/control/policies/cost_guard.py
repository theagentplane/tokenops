"""Deprecated: this module moved to ``tokenops.framework.policies.cost_guard``."""

import sys
import warnings

from tokenops.framework.policies import cost_guard as _module

warnings.warn(
    "tokenops.control.policies.cost_guard moved to tokenops.framework.policies.cost_guard; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
