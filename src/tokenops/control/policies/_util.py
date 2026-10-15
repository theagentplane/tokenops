"""Deprecated: this module moved to ``tokenops.framework.policies._util``."""

import sys
import warnings

from tokenops.framework.policies import _util as _module

warnings.warn(
    "tokenops.control.policies._util moved to tokenops.framework.policies._util; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
