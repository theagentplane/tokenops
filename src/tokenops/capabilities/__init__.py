"""The capabilities layer: governed-run workflows.

Opens runs (:func:`tokenops_run`), wraps model calls (:func:`wrap_complete`), and installs the
Chronicle crossing hook that feeds the governor. Importing this package registers the hook on
``chronicle.default_hooks`` for the whole process.
"""

from tokenops.capabilities.complete_wrapper import wrap_complete
from tokenops.capabilities.crossing import install_crossing_hook, on_crossing
from tokenops.capabilities.ledger_writers import flush_ledger_writes
from tokenops.capabilities.run import TokenOpsBound, agentplane_run_scope, tokenops_run
from tokenops.capabilities.step_observation import make_on_step, step_to_observation
from tokenops.capabilities.stream_wrapper import wrap_stream
from tokenops.framework.message_steering import apply_carry_to_messages, consume_carry

# Process-wide: register the governor hook on chronicle.default_hooks (inherited by every session).
install_crossing_hook()

__all__ = [
    "TokenOpsBound",
    "agentplane_run_scope",
    "apply_carry_to_messages",
    "consume_carry",
    "flush_ledger_writes",
    "install_crossing_hook",
    "make_on_step",
    "on_crossing",
    "step_to_observation",
    "tokenops_run",
    "wrap_complete",
    "wrap_stream",
]
