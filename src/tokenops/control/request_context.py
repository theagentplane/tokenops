"""Deprecated: this module moved to ``tokenops.framework.request_context``."""

import sys
import warnings

from tokenops.framework import request_context as _module

warnings.warn(
    "tokenops.control.request_context moved to tokenops.framework.request_context; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
