"""Deprecated: this module moved to ``tokenops.framework.policies.output_runaway``."""

import sys
import warnings

from tokenops.framework.policies import output_runaway as _module

warnings.warn(
    "tokenops.control.policies.output_runaway moved to tokenops.framework.policies.output_runaway; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
