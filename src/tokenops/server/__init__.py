"""Standalone TokenOps control-plane HTTP service."""

from tokenops.server.app import create_app

__all__ = ["create_app"]
