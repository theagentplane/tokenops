"""Deprecated: this module moved to ``tokenops.framework.policies.concurrency_cap``."""

import sys
import warnings

from tokenops.framework.policies import concurrency_cap as _module

warnings.warn(
    "tokenops.control.policies.concurrency_cap moved to tokenops.framework.policies.concurrency_cap; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
