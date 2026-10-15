"""Deprecated: the policies moved to ``tokenops.framework.policies``."""

import warnings

from tokenops.framework.policies import *  # noqa: F401,F403

warnings.warn(
    "tokenops.control.policies moved to tokenops.framework.policies; the old path is "
    "deprecated and will be removed in 2.0",
    DeprecationWarning,
    stacklevel=2,
)
