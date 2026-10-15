"""Deprecated: this module moved to ``tokenops.framework.policies.tool_fix``."""

import sys
import warnings

from tokenops.framework.policies import tool_fix as _module

warnings.warn(
    "tokenops.control.policies.tool_fix moved to tokenops.framework.policies.tool_fix; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
