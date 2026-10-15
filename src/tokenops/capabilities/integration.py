"""The in-process integration surface in one place (the 1.0 module, kept for its import path).

The pieces live in :mod:`tokenops.capabilities.step_observation`,
:mod:`tokenops.capabilities.complete_wrapper`, :mod:`tokenops.capabilities.stream_wrapper` and
:mod:`tokenops.framework.message_steering`.
"""

from tokenops.capabilities.complete_wrapper import wrap_complete
from tokenops.capabilities.step_observation import make_on_step, step_to_observation
from tokenops.capabilities.stream_wrapper import wrap_stream
from tokenops.framework.message_steering import apply_carry_to_messages, consume_carry

__all__ = [
    "apply_carry_to_messages",
    "consume_carry",
    "make_on_step",
    "step_to_observation",
    "wrap_complete",
    "wrap_stream",
]
