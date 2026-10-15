"""Deprecated: this module moved to ``tokenops.framework.context``."""

import sys
import warnings

from tokenops.framework import context as _module

warnings.warn(
    "tokenops.control.context moved to tokenops.framework.context; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
