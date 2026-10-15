"""Deprecated: this module moved to ``tokenops.framework.models``."""

import sys
import warnings

from tokenops.framework import models as _module

warnings.warn(
    "tokenops.control.models moved to tokenops.framework.models; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
