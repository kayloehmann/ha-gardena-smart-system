"""Shared pytest configuration for the aiogardenasmart test-suite.

This module carries a narrowly scoped compatibility shim for ``aioresponses``.

``aiohttp`` 3.14 turned ``stream_writer`` into a *required* keyword-only
argument of ``ClientResponse.__init__``. ``aioresponses`` (0.7.9, the latest
release at the time of writing) still builds its mocked responses without it,
so every mocked request raises::

    TypeError: ClientResponse.__init__() missing 1 required
               keyword-only argument: 'stream_writer'

``aioresponses`` declares ``aiohttp<4.0,>=3.8``, so pip happily resolves the
broken combination. Upstream has open pull requests for this (pnuckowski/
aioresponses#288 and #292) but no release yet.

Pinning ``aiohttp<3.14`` for tests would be the cheap way out, but it would
test this library against an aiohttp that Home Assistant does *not* ship
(HA 2026.2 runs aiohttp 3.14.1) — precisely the kind of gap that lets a real
bug through a green CI. So instead we apply upstream's fix ourselves, at the
smallest possible surface: a ``ClientResponse`` subclass that defaults the new
argument. ``stream_writer`` is only consulted for its ``output_size``
attribute, so a mock is sufficient.

The shim is guarded by a signature check and therefore becomes a no-op the
moment aioresponses ships a fixed release (or on any older aiohttp). Remove
this file once ``aioresponses > 0.7.9`` is available and pinned in the dev
dependencies.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import Mock

import aioresponses.core
from aiohttp.client_reqrep import ClientResponse


def _client_response_requires_stream_writer() -> bool:
    """Return True if ``ClientResponse`` demands a ``stream_writer`` argument."""
    parameter = inspect.signature(ClientResponse.__init__).parameters.get("stream_writer")
    return parameter is not None and parameter.default is inspect.Parameter.empty


class _ClientResponseWithStreamWriter(ClientResponse):
    """``ClientResponse`` that supplies the aiohttp 3.14 ``stream_writer`` argument."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("stream_writer", Mock(output_size=0))
        super().__init__(*args, **kwargs)


if _client_response_requires_stream_writer():
    # `aioresponses.core` imports `ClientResponse` into its own namespace and
    # resolves it at call time, so rebinding the module global is enough.
    aioresponses.core.ClientResponse = _ClientResponseWithStreamWriter  # type: ignore[misc]
