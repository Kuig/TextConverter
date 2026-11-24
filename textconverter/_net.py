"""Networking helpers.

Single place where outbound TLS verification is configured. Every HTTP(S)
download in the package goes through :func:`open_url` so certificate
verification is done against an up-to-date trust store instead of the
possibly-stale OpenSSL/system store that ``urllib`` uses by default.
"""

from __future__ import annotations

import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from .logger import log_warning

# Some servers refuse urllib's default User-Agent.
_USER_AGENT = "Mozilla/5.0"


class DownloadError(RuntimeError):
    """A remote resource could not be downloaded."""


@dataclass
class Download:
    """A downloaded resource.

    Attributes:
        data: The response body.
        content_type: Media type from ``Content-Type``, lowercase without
            parameters; "" when the server sent none.
        charset: The ``charset`` parameter of ``Content-Type``, if any.
    """
    data: bytes
    content_type: str = ""
    charset: str | None = None


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
    except ImportError:
        pass
    except (OSError, ssl.SSLError) as exc:
        log_warning(f"OS trust store unavailable, using the certifi bundle: {exc}")

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    except (OSError, ssl.SSLError) as exc:
        log_warning(f"certifi bundle unavailable, using the default trust store: {exc}")
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


def fetch(url: str, *, timeout: float) -> Download:
    """Download ``url`` with :func:`open_url` and a browser-like User-Agent.

    Args:
        url: An ``http://`` or ``https://`` URL.
        timeout: Socket timeout in seconds.

    Returns:
        The body and the ``Content-Type`` details.

    Raises:
        DownloadError: If the request fails (HTTP error, network error,
            malformed URL).
    """
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with open_url(req, timeout=timeout) as response:
            data = response.read()
            headers = response.headers
            status = response.status
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise _blocked(url, "HTTP Error 403 Forbidden/Blocked") from exc
        raise DownloadError(f"Failed to download {url}: {exc}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DownloadError(f"Failed to download {url}: {exc}") from exc
    if _is_challenge(headers):
        raise _blocked(url, f"HTTP {status} with a bot challenge instead of the content")
    if not data and status != 200:
        raise DownloadError(f"Failed to download {url}: HTTP {status} with an empty body")
    content_type = headers.get_content_type() if headers.get("Content-Type") else ""
    return Download(data=data, content_type=content_type, charset=headers.get_content_charset())


def _is_challenge(headers) -> bool:
    """Tell whether a successful response is an anti-bot challenge page.

    AWS WAF answers ``202`` with an empty body and ``x-amzn-waf-action``;
    Cloudflare marks its challenge with ``cf-mitigated: challenge``. Both
    need a browser that runs the challenge's JavaScript.

    Args:
        headers: The response headers.

    Returns:
        True when the body is a challenge, not the requested resource.
    """
    return bool(headers.get("x-amzn-waf-action")) or headers.get("cf-mitigated", "").lower() == "challenge"


def _blocked(url: str, reason: str) -> DownloadError:
    """Build the error for a server that refuses automated clients.

    Args:
        url: The requested URL.
        reason: What the server answered.

    Returns:
        A ``DownloadError`` that suggests converting a local copy.
    """
    return DownloadError(
        f"Failed to download {url}: {reason}. "
        "This server blocks automated scrapers. "
        "Please download the file manually and convert the local file."
    )
