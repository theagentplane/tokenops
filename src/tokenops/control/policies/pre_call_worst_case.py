"""Deprecated: this module moved to ``tokenops.framework.policies.pre_call_worst_case``."""

import sys
import warnings

from tokenops.framework.policies import pre_call_worst_case as _module

warnings.warn(
    "tokenops.control.policies.pre_call_worst_case moved to tokenops.framework.policies.pre_call_worst_case; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
