"""Fetch a public job posting's text, for the `POST /jd/fetch` endpoint.

Three constraints shape this module, and each one is a refusal rather than a
feature:

1. **No access-control bypass.** This fetches public pages. A login wall, a
   captcha, a paywall or a rate limit is reported back as exactly that, with a
   message telling the user to paste the posting text instead. The assistant
   never presents gated content as if it had been read.
2. **No SSRF.** A URL is attacker-controlled input, and this process runs on the
   user's own machine, where `http://127.0.0.1:...` and `http://169.254.169.254/`
   reach things that are not the public web. Every host is resolved and rejected
   if any address is loopback, private, link-local, reserved or multicast - and
   the check is repeated on every redirect hop, because following a redirect
   blindly is the standard way this guard gets bypassed.
3. **No robots.txt violation.** The posting's own robots policy is consulted
   first, and a disallow is reported rather than ignored.

The HTTP call and the DNS lookup are both injectable, so the tests exercise
every one of those refusals without touching the network.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from server.schemas import JdFetchResponse

#: Identifies the tool honestly and gives a site owner something to block.
USER_AGENT = "RJD-Prefill-Assistant/0.3 (local-only; job-posting reader)"

MAX_BYTES = 2_000_000
TIMEOUT_S = 15.0
MAX_REDIRECTS = 5
MIN_USEFUL_CHARS = 200

#: Markers that mean "this page is gated". Checked only when the extracted text
#: is too short to be a real posting, so a posting that merely mentions the word
#: "subscribe" is not misclassified.
_GATE_MARKERS: tuple[tuple[str, str], ...] = (
    ("login_required", r"sign\s+in\s+to\s+(continue|view|apply)|log\s*in\s+to\s+(continue|view|apply)|already have an account|enter your password"),
    ("paywall", r"subscri(be|ption)\s+to\s+(read|continue|view)|article limit|premium content|members only"),
    ("captcha", r"verify you are human|are you a robot|recaptcha|hcaptcha|cf-browser-verification|checking your browser|just a moment"),
    ("blocked", r"access denied|request blocked|forbidden|unusual traffic|too many requests"),
)

_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES = re.compile(r"\n{3,}")
_SCRIPT_STYLE = re.compile(r"(?is)<(script|style|noscript|template|svg)[^>]*>.*?</\1>")
_TAG = re.compile(r"(?s)<[^>]+>")
_TITLE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_LD_JSON = re.compile(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>')

FetchFn = Callable[[str, dict[str, str], float], tuple[int, dict[str, str], bytes, str]]
ResolveFn = Callable[[str], list[str]]


@dataclass
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes
    final_url: str


def _default_resolve(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, None)
    return sorted({info[4][0] for info in infos})


def _default_fetch(url: str, headers: dict[str, str], timeout: float) -> tuple[int, dict[str, str], bytes, str]:
    import httpx

    with httpx.Client(follow_redirects=False, timeout=timeout) as client:
        response = client.get(url, headers=headers)
        return response.status_code, dict(response.headers), response.content, str(response.url)


def _blocked_ip(address: str) -> str | None:
    """Why this IP must not be fetched, or None when it is a public address."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return f"{address!r} is not an IP address"
    if ip.is_loopback:
        return "loopback address"
    if ip.is_private:
        return "private address"
    if ip.is_link_local:
        return "link-local address"
    if ip.is_reserved:
        return "reserved address"
    if ip.is_multicast:
        return "multicast address"
    if ip.is_unspecified:
        return "unspecified address"
    return None


def is_public_url(url: str, *, resolve: ResolveFn = _default_resolve) -> tuple[bool, str]:
    """Is this a URL we are willing to request?

    Rejecting by *resolved address* rather than by hostname is what makes this
    hold: `localhost`, `foo.internal` and a DNS name that resolves to
    169.254.169.254 all fail the same way.
    """
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False, f"unsupported scheme {parsed.scheme or '(none)'!r}; only http and https are fetched"
    if not parsed.netloc:
        return False, "the URL has no host"
    host = parsed.hostname or ""
    if not host:
        return False, "the URL has no host"
    try:
        addresses = resolve(host)
    except Exception as exc:  # noqa: BLE001 - a name that will not resolve is not fetched
        return False, f"could not resolve {host!r}: {type(exc).__name__}"
    if not addresses:
        return False, f"{host!r} did not resolve to any address"
    for address in addresses:
        reason = _blocked_ip(address)
        if reason is not None:
            return False, f"{host!r} resolves to a {reason} ({address}); refusing to fetch it"
    return True, ""


def robots_allows(
    url: str,
    *,
    fetch: FetchFn = _default_fetch,
    resolve: ResolveFn = _default_resolve,
) -> tuple[bool, str]:
    """Consult the site's robots.txt. Unavailable robots.txt means "allowed".

    `RobotFileParser` is used rather than a hand-rolled matcher so wildcard and
    Allow/Disallow precedence follow the standard.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    ok, reason = is_public_url(robots_url, resolve=resolve)
    if not ok:
        return True, f"robots.txt not consulted ({reason})"
    try:
        status, _headers, body, _final = fetch(
            robots_url, {"User-Agent": USER_AGENT, "Accept": "text/plain"}, TIMEOUT_S
        )
    except Exception as exc:  # noqa: BLE001
        return True, f"robots.txt unreachable ({type(exc).__name__}); treated as allowed"
    if status >= 400:
        return True, f"robots.txt returned HTTP {status}; treated as allowed"

    parser = RobotFileParser()
    parser.parse(body.decode("utf-8", errors="replace").splitlines())
    allowed = parser.can_fetch(USER_AGENT, url)
    if allowed:
        return True, "robots.txt allows this path"
    return False, f"robots.txt disallows {parsed.path or '/'} for this user agent"


def extract_readable_text(html: str, url: str = "") -> tuple[str, str]:
    """Pull the readable text out of a posting page.

    Preferred path is BeautifulSoup with the boilerplate elements removed; the
    regex fallback exists so a missing optional dependency degrades the result
    instead of failing the request. `application/ld+json` is consulted for the
    title because job boards routinely put the real title only there.
    """
    title = ""
    match = _TITLE.search(html or "")
    if match:
        title = _TAG.sub(" ", match.group(1)).strip()
    if not title:
        for match in _LD_JSON.finditer(html or ""):
            block = match.group(1)
            found = re.search(r'"title"\s*:\s*"([^"]{3,200})"', block)
            if found:
                title = found.group(1).strip()
                break

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html or "", "html.parser")
        for tag in soup(["script", "style", "noscript", "template", "svg", "nav", "header", "footer", "aside", "form", "iframe"]):
            tag.decompose()
        container = soup.find("main") or soup.find("article") or soup.find(attrs={"role": "main"})
        if container is None:
            body = soup.find("body")
            if body is not None:
                # Largest text block: the candidate that usually holds the posting
                # rather than the site chrome.
                blocks = body.find_all(["div", "section"], recursive=True)
                container = max(
                    (blocks or [body]),
                    key=lambda node: len(node.get_text(" ", strip=True)),
                    default=body,
                )
            else:
                container = soup
        text = container.get_text("\n", strip=True)
        if not title and soup.title and soup.title.string:
            title = soup.title.string.strip()
        return title, text
    except Exception:  # noqa: BLE001 - the fallback is the whole point here
        cleaned = _SCRIPT_STYLE.sub(" ", html or "")
        cleaned = re.sub(r"(?i)</(p|div|li|br|h[1-6]|tr)>", "\n", cleaned)
        text = _TAG.sub(" ", cleaned)
        return title, text


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _gated(text: str) -> str | None:
    """A gate marker, when the page is too short to be a real posting."""
    if len(text) >= MIN_USEFUL_CHARS:
        return None
    lowered = text.lower()
    for reason, pattern in _GATE_MARKERS:
        if re.search(pattern, lowered):
            return reason
    return None


_GATE_MESSAGES = {
    "login_required": "This page needs a sign-in. Log in in your browser and copy the posting text, then paste it into the extension.",
    "paywall": "This posting sits behind a paywall, which this tool will not circumvent. Paste the text you can see instead.",
    "captcha": "This page is showing a bot check. Open it in your browser and paste the posting text instead.",
    "blocked": "The site refused the request (rate limit or block). Paste the posting text instead.",
}


def fetch_jd(
    url: str,
    *,
    ignore_robots: bool = False,
    fetch: FetchFn = _default_fetch,
    resolve: ResolveFn = _default_resolve,
    max_chars: int = 20000,
) -> JdFetchResponse:
    """Fetch one public posting and return its readable text.

    `fetch` and `resolve` are injected so the tests can drive every branch -
    private host, robots disallow, redirect to a private host, login wall, paywall,
    oversized body - with no network access at all.
    """
    url = (url or "").strip()
    if not url:
        return JdFetchResponse(
            ok=False, url=url, reason="unsupported_scheme",
            message="No URL was given.",
        )

    # The scheme and host are checked separately from the address check, because
    # they are different faults with different fixes. Folding them together made
    # `file:///etc/passwd` come back as reason="private_host", which told the user
    # their host was private when the real problem was the scheme - and the
    # documented `unsupported_scheme` reason was then unreachable.
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return JdFetchResponse(
            ok=False, url=url, reason="unsupported_scheme",
            message=(
                f"unsupported scheme {parsed.scheme or '(none)'!r}; only http and https are "
                "fetched. Paste the posting text instead."
            ),
        )
    if not parsed.netloc or not parsed.hostname:
        return JdFetchResponse(
            ok=False, url=url, reason="unsupported_scheme",
            message="The URL has no host. Paste the posting text instead.",
        )

    ok, reason = is_public_url(url, resolve=resolve)
    if not ok:
        return JdFetchResponse(ok=False, url=url, reason="private_host", message=reason)

    if not ignore_robots:
        allowed, note = robots_allows(url, fetch=fetch, resolve=resolve)
        if not allowed:
            return JdFetchResponse(
                ok=False, url=url, robots_allowed=False, reason="robots_disallowed",
                message=(
                    f"{note}. This tool respects the site's crawling policy; "
                    "paste the posting text into the extension instead."
                ),
            )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en",
    }

    current = url
    response: _Response | None = None
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            status, resp_headers, body, final_url = fetch(current, headers, TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - every failure becomes a user-facing reason
            name = type(exc).__name__
            if "Timeout" in name:
                return JdFetchResponse(ok=False, url=url, reason="timeout", message="The site did not respond in time. Paste the posting text instead.")
            return JdFetchResponse(ok=False, url=url, reason="network_error", message=f"Could not reach the site ({name}). Paste the posting text instead.")

        if len(body) > MAX_BYTES:
            return JdFetchResponse(
                ok=False, url=url, status=status, reason="too_large",
                message=f"The page is larger than {MAX_BYTES // 1_000_000} MB. Paste the relevant text instead.",
            )

        lowered = {k.lower(): v for k, v in resp_headers.items()}
        if status in {301, 302, 303, 307, 308} and lowered.get("location"):
            target = urljoin(current, lowered["location"])
            # The redirect target is re-validated: this is the hop that turns a
            # public URL into an SSRF if it is not.
            target_ok, target_reason = is_public_url(target, resolve=resolve)
            if not target_ok:
                return JdFetchResponse(
                    ok=False, url=url, status=status, reason="private_host",
                    message=f"The page redirected to a target that is not fetched ({target_reason}).",
                )
            current = target
            continue
        response = _Response(status=status, headers=lowered, body=body, final_url=final_url or current)
        break

    if response is None:
        return JdFetchResponse(ok=False, url=url, reason="http_error", message="Too many redirects. Paste the posting text instead.")

    content_type = response.headers.get("content-type", "")
    if response.status == 401:
        return JdFetchResponse(ok=False, url=url, final_url=response.final_url, status=401, content_type=content_type, reason="login_required", message=_GATE_MESSAGES["login_required"])
    if response.status == 402:
        return JdFetchResponse(ok=False, url=url, final_url=response.final_url, status=402, content_type=content_type, reason="paywall", message=_GATE_MESSAGES["paywall"])
    if response.status in {403, 429}:
        return JdFetchResponse(ok=False, url=url, final_url=response.final_url, status=response.status, content_type=content_type, reason="blocked", message=_GATE_MESSAGES["blocked"])
    if response.status >= 400:
        return JdFetchResponse(
            ok=False, url=url, final_url=response.final_url, status=response.status, content_type=content_type,
            reason="http_error",
            message=f"The site returned HTTP {response.status}. Paste the posting text instead.",
        )
    if "html" not in content_type.lower() and "text" not in content_type.lower():
        return JdFetchResponse(
            ok=False, url=url, final_url=response.final_url, status=response.status, content_type=content_type,
            reason="not_html",
            message=f"The response is {content_type or 'an unknown type'}, not a web page. Paste the posting text instead.",
        )

    html = response.body.decode("utf-8", errors="replace")
    title, text = extract_readable_text(html, url=response.final_url)
    text = _tidy(text)

    gate = _gated(text)
    if gate:
        return JdFetchResponse(
            ok=False, url=url, final_url=response.final_url, status=response.status,
            content_type=content_type, title=title, chars=len(text), reason=gate,
            robots_allowed=True, message=_GATE_MESSAGES.get(gate, "The page could not be read."),
        )

    if len(text) < 40:
        return JdFetchResponse(
            ok=False, url=url, final_url=response.final_url, status=response.status,
            content_type=content_type, title=title, chars=len(text), reason="not_html",
            message="No readable text was found on that page. Paste the posting text instead.",
        )

    truncated = len(text) > max_chars
    return JdFetchResponse(
        ok=True,
        url=url,
        final_url=response.final_url,
        status=response.status,
        content_type=content_type,
        title=title,
        text=text[:max_chars],
        chars=len(text[:max_chars]),
        robots_allowed=True,
        reason="ok",
        message=(
            f"Read {len(text[:max_chars])} characters"
            + (" (truncated to the configured input limit)." if truncated else ".")
        ),
    )


__all__ = [
    "MAX_BYTES",
    "MIN_USEFUL_CHARS",
    "USER_AGENT",
    "extract_readable_text",
    "fetch_jd",
    "is_public_url",
    "robots_allows",
]
