"""Transport-level guards for the local server: binding, tokens and CORS.

Three things this file is responsible for, each of which is a refusal:

* **The server only ever listens on a loopback address.** `run()` asserts this
  rather than trusting the caller, because binding to 0.0.0.0 would put an
  endpoint that accepts a candidate's personal data on the local network - and
  the failure would be invisible from the machine it is running on.
* **A shared token is required when one is configured.** A page in any other tab
  can reach `127.0.0.1`, so "it is only localhost" is not by itself an access
  control. The token is generated on first run and stored next to the artifacts,
  never in the repository.
* **CORS admits extension origins only.** A permissive `*` would let any website
  the user visits read their profile out of this server. The regex is pinned to
  `chrome-extension://` and `moz-extension://`.
"""

from __future__ import annotations

import hmac
import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from src import config

TOKEN_HEADER = "X-RJD-Token"
TOKEN_ENV = "RJD_SERVER_TOKEN"

#: The only origins allowed to call this server from a browser page context.
ALLOWED_ORIGIN_REGEX = r"^(chrome|moz)-extension://[A-Za-z0-9_\-]+$"

#: Addresses that mean "this machine only".
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class InsecureBindError(RuntimeError):
    """Raised when asked to bind somewhere other than loopback."""


@dataclass
class TokenInfo:
    token: str | None
    required: bool
    source: str

    def describes(self) -> str:
        if not self.required:
            return "disabled (no token configured)"
        return f"required (from {self.source})"


def token_path() -> Path:
    return config.ROOT / "artifacts" / "server_token.txt"


def resolve_token(*, allow_generate: bool = True) -> TokenInfo:
    """Find the shared token, generating one on first run.

    Generation is on by default because the alternative - running open unless the
    user remembers to set an environment variable - is how a localhost service
    ends up unauthenticated in practice. The file is written with owner-only
    permissions where the platform supports it.
    """
    from_env = os.getenv(TOKEN_ENV)
    if from_env and from_env.strip():
        return TokenInfo(token=from_env.strip(), required=True, source=TOKEN_ENV)

    path = token_path()
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return TokenInfo(token=existing, required=True, source=str(path))
    except Exception:  # noqa: BLE001 - fall through to generating a new one
        pass

    if not allow_generate:
        return TokenInfo(token=None, required=False, source="none")

    token = secrets.token_urlsafe(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except Exception:  # noqa: BLE001 - not supported everywhere, not fatal
            pass
        return TokenInfo(token=token, required=True, source=str(path))
    except Exception:  # noqa: BLE001 - if it cannot be persisted, stay open and say so
        return TokenInfo(token=None, required=False, source="unwritable path")


def assert_loopback(host: str) -> None:
    """Refuse to bind anywhere a network can reach."""
    if host not in LOOPBACK_HOSTS:
        raise InsecureBindError(
            f"refusing to bind {host!r}. This server holds personal data and accepts requests "
            "from a browser extension, so it only ever listens on loopback "
            f"({', '.join(sorted(LOOPBACK_HOSTS))}). Use an SSH tunnel to reach it remotely."
        )


def constant_time_equal(candidate: str | None, expected: str | None) -> bool:
    """Compare tokens without leaking length or prefix through timing."""
    if not expected:
        return True
    if not candidate:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


__all__ = [
    "ALLOWED_ORIGIN_REGEX",
    "InsecureBindError",
    "LOOPBACK_HOSTS",
    "TOKEN_ENV",
    "TOKEN_HEADER",
    "TokenInfo",
    "assert_loopback",
    "constant_time_equal",
    "resolve_token",
    "token_path",
]
