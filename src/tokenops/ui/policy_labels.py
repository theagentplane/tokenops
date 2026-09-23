"""Policy display labels; stored/configured identifiers are never rewritten."""

from tokenops.control.config import POLICY_TEMPLATES


def policy_label(policy_id: str) -> str:
    """Keep the exact ID visible alongside its label.

    Custom/historical event IDs without built-in metadata remain verbatim, not guessed
    or treated as aliases for another policy.
    """
    template = POLICY_TEMPLATES.get(policy_id)
    if template is None:
        return policy_id
    label = f"{template.display_name} ({policy_id})"
    if template.factory is None:
        label += " [temporarily disabled]"
    return label
