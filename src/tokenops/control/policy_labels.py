"""Deprecated: this module moved to ``tokenops.framework.policy_labels``."""

import sys
import warnings

from tokenops.framework import policy_labels as _module

warnings.warn(
    "tokenops.control.policy_labels moved to tokenops.framework.policy_labels; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
