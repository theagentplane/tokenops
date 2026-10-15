"""Chronicle setup for an example agent server: one trace across the A2A hops.

A run is a Chronicle trace. Hops share it through the W3C ``traceparent`` header, which
Chronicle sends on outbound ``httpx`` calls to hosts in ``inject_hosts`` and which
``tokenops_run`` reads from the inbound request. Without a control plane configured
(``CONTROL_PLANE_URL``) nothing is recorded or delivered, but propagation still works.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from urllib.parse import urlparse

import chronicle


def configure_tracing(service: str, peers: Iterable[str] = ()) -> None:
    """Point Chronicle at the control plane and allow ``traceparent`` to the peer services."""
    hosts = sorted({urlparse(url).hostname for url in peers if urlparse(url).hostname})
    settings: dict[str, object] = {"service_name": service, "inject_hosts": hosts}
    url = (os.environ.get("CONTROL_PLANE_URL") or "").strip()
    if url:
        settings["control_plane_url"] = url
        key = (os.environ.get("CONTROL_PLANE_API_KEY") or "").strip()
        if key:
            settings["api_key"] = key
    chronicle.configure(**settings)
    chronicle.instrument_httpx()
