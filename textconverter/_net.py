"""Networking helpers.

Single place where outbound TLS verification is configured. Every HTTP(S)
download in the package goes through :func:`open_url` so certificate
verification is done against an up-to-date trust store instead of the
possibly-stale OpenSSL/system store that ``urllib`` uses by default.
"""

from __future__ import annotations

import ssl
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def ssl_context() -> ssl.SSLContext:
    """Return a verifying ``SSLContext`` backed by an up-to-date trust store.

    Prefers the OS-native verifier via ``truststore`` (on Windows/macOS the
    root certificates are kept current by the system), falls back to the
    ``certifi`` bundle, then to the stdlib default.

    Returns:
        A certificate-verifying SSL context.
    """
    try:
        import truststore

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:
        pass

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def open_url(req: urllib.request.Request | str, *, timeout: float):
    """Open ``req`` like ``urllib.request.urlopen`` but with :func:`ssl_context`.

    Args:
        req: A ``Request`` object or URL string.
        timeout: Socket timeout in seconds.

    Returns:
        The ``http.client.HTTPResponse`` context manager from ``urlopen``.
    """
    return urllib.request.urlopen(req, timeout=timeout, context=ssl_context())
