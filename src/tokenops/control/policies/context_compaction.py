"""Deprecated: this module moved to ``tokenops.framework.policies.context_compaction``."""

import sys
import warnings

from tokenops.framework.policies import context_compaction as _module

warnings.warn(
    "tokenops.control.policies.context_compaction moved to tokenops.framework.policies.context_compaction; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
