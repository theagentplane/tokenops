"""Deprecated: this module moved to ``tokenops.capabilities.chronicle_trace_utils``."""

import sys
import warnings

from tokenops.capabilities import chronicle_trace_utils as _module

warnings.warn(
    "tokenops.control.chronicle_trace_utils moved to tokenops.capabilities.chronicle_trace_utils; the old path is deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
sys.modules[__name__] = _module
