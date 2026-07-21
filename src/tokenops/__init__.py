"""TokenOps control plane and SDK."""

from tokenops.env import load_env

load_env()

__version__ = "0.1.0"

# First-class SDK surface for agents / UIs talking to the plane.
from tokenops.control.client import ControlPlaneClient as ControlPlaneClient

__all__ = ["ControlPlaneClient", "__version__"]
