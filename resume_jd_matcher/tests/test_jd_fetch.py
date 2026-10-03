"""Tests for `POST /jd/fetch` - the only endpoint that opens a network connection.

Every test here drives an injected `fetch`/`resolve`, so nothing touches the
network and every refusal branch is reachable on demand. That matters because the
branches that are hardest to reach in production - a redirect aimed at
169.254.169.254, a paywall, a rate limit - are exactly the ones that must not
silently become "successfully read the posting".

Three groups of guarantees:

    SSRF        every hop's host is resolved and rejected if it is not public
    politeness  robots.txt is consulted first, and a disallow is reported
    honesty     a gated or unreadable page is reported as such, with a next step
"""

from __future__ import annotations

import socket
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from server.jd_fetch import (  # noqa: E402
    MAX_BYTES,
    MIN_USEFUL_CHARS,
    extract_readable_text,
    fetch_jd,
    is_public_url,
    robots_allows,
)

#: A hostname that resolves to a real public address, so the SSRF check passes and
#: the later branches are reachable.
PUBLIC_HOST = "careers.example.test"
PUBLIC_IP = "93.184.216.34"

POSTING_BODY = (
    "<html><head><title>Machine Learning Intern - Acme Corp</title>"
    "<script>var tracking = 'should not appear';</script>"
    "<style>.x{color:red}</style></head><body>"
    "<nav>Home About Careers Login</nav>"
    "<main><h1>Machine Learning Intern</h1>"
    "<p>Acme Corp is hiring a machine learning intern in Singapore. "
    "You will build training pipelines, evaluate models, and work with the "
    "research team on production systems. Requirements: Python, PyTorch, SQL, "
    "and a strong grounding in statistics. Nice to have: Docker and Kubernetes.</p>"
    "</main><footer>Copyright Acme Corp</footer></body></html>"
)

ROBOTS_ALLOW_ALL = b"User-agent: *\nAllow: /\n"
ROBOTS_DISALLOW = b"User-agent: *\nDisallow: /jobs/\n"


def resolver(mapping: dict[str, list[str]] | None = None):
    """A `resolve` that answers only for known hosts, like a real DNS failure otherwise."""
    table = {"example.test": [PUBLIC_IP], PUBLIC_HOST: [PUBLIC_IP], **(mapping or {})}

    def _resolve(host: str) -> list[str]:
        if host in table:
            return table[host]
        raise socket.gaierror(11001, f"getaddrinfo failed for {host}")

    return _resolve


class FakeFetcher:
    """Records every URL requested and replies from a routing table."""

    def __init__(self, routes: dict[str, object] | None = None, default: object | None = None) -> None:
        self.routes = routes or {}
        self.default = default if default is not None else (404, {"content-type": "text/html"}, b"")
        self.calls: list[str] = []

    def __call__(self, url: str, headers: dict[str, str], timeout: float):
        self.calls.append(url)
        route = self.routes.get(url, self.default)
        if isinstance(route, Exception):
            raise route
        status, extra_headers, body = route  # type: ignore[misc]
        return status, extra_headers, body, url


def ok_routes(**extra) -> dict[str, object]:
    routes: dict[str, object] = {
        f"https://{PUBLIC_HOST}/robots.txt": (200, {"content-type": "text/plain"}, ROBOTS_ALLOW_ALL),
        f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, POSTING_BODY.encode()),
    }
    routes.update(extra)
    return routes


def fetch(url: str, fetcher: FakeFetcher, **kwargs):
    # `setdefault`, so a test can override the resolver without colliding with it.
    kwargs.setdefault("resolve", resolver())
    return fetch_jd(url, fetch=fetcher, **kwargs)


#: Addresses that must never be requested, with the words that may appear in the
#: refusal. `ipaddress` classifies 169.254.0.0/16 as private *and* link-local, and
#: `_blocked_ip` reports the first match, so the exact wording is not pinned -
#: being refused is the guarantee, the label is not.
BLOCKED_ADDRESSES = [
    ("127.0.0.1", {"loopback"}),
    ("10.0.0.5", {"private"}),
    ("192.168.1.10", {"private"}),
    ("172.16.4.2", {"private"}),
    ("169.254.169.254", {"link-local", "private"}),
    ("0.0.0.0", {"unspecified", "private", "reserved"}),
    ("::1", {"loopback"}),
    ("fe80::1", {"link-local", "private"}),
    ("fc00::1", {"private"}),
    ("224.0.0.1", {"multicast", "reserved"}),
]


# --------------------------------------------------------------------------- #
# SSRF
# --------------------------------------------------------------------------- #


class TestSsrfProtection(unittest.TestCase):
    """A URL is attacker-controlled input; the process runs on the user's machine."""

    def test_loopback_private_and_link_local_hosts_are_refused(self) -> None:
        for address, accept in BLOCKED_ADDRESSES:
            url = f"http://[{address}]/apply" if ":" in address else f"http://{address}/apply"
            with self.subTest(address=address):
                allowed, reason = is_public_url(url, resolve=resolver({address: [address]}))
                self.assertFalse(allowed, f"{address} must not be fetched")
                self.assertTrue(
                    any(word in reason for word in accept),
                    f"expected one of {accept} in {reason!r}",
                )

    def test_a_lookalike_hostname_is_refused_because_its_address_is_private(self) -> None:
        # The check is on the resolved address, so a name that merely looks public
        # ("localhost.attacker.test") fails the same way `localhost` does.
        for name in ["localhost", "foo.internal", "localhost.attacker.test", "metadata.google.internal"]:
            with self.subTest(name=name):
                allowed, _ = is_public_url(f"http://{name}/x", resolve=resolver({name: ["127.0.0.1"]}))
                self.assertFalse(allowed)

    def test_the_cloud_metadata_address_is_refused(self) -> None:
        # The single most valuable SSRF target on a laptop or VM.
        result = fetch(
            "http://169.254.169.254/latest/meta-data/iam/security-credentials/",
            FakeFetcher(),
            resolve=resolver({"169.254.169.254": ["169.254.169.254"]}),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "private_host")

    def test_a_public_host_resolving_to_a_private_address_is_refused(self) -> None:
        # Rejecting by resolved address, not by hostname, is what makes a
        # DNS-rebinding-style name safe: the name looks public, the address is not.
        allowed, reason = is_public_url(
            f"https://{PUBLIC_HOST}/jobs/1",
            resolve=resolver({PUBLIC_HOST: ["127.0.0.1"]}),
        )
        self.assertFalse(allowed)
        self.assertIn("loopback", reason)

    def test_a_name_that_does_not_resolve_is_refused(self) -> None:
        allowed, reason = is_public_url("https://nope.invalid/jobs/1", resolve=resolver())
        self.assertFalse(allowed)
        self.assertIn("resolve", reason)

    def test_a_host_with_any_private_address_is_refused(self) -> None:
        # Multi-homed names must fail closed: one bad address is enough.
        allowed, _ = is_public_url(
            f"https://{PUBLIC_HOST}/jobs/1",
            resolve=resolver({PUBLIC_HOST: [PUBLIC_IP, "10.0.0.9"]}),
        )
        self.assertFalse(allowed)

    def test_a_redirect_to_a_private_host_is_refused_and_not_followed(self) -> None:
        # The standard bypass: a public URL that 302s to the metadata service.
        routes = ok_routes(
            **{
                f"https://{PUBLIC_HOST}/jobs/1": (
                    302,
                    {"location": "http://169.254.169.254/latest/meta-data/"},
                    b"",
                )
            }
        )
        fetcher = FakeFetcher(routes)
        result = fetch(
            f"https://{PUBLIC_HOST}/jobs/1",
            fetcher,
            resolve=resolver({"169.254.169.254": ["169.254.169.254"]}),
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "private_host")
        self.assertNotIn(
            "http://169.254.169.254/latest/meta-data/",
            fetcher.calls,
            "the private target must never be requested",
        )

    def test_a_redirect_to_a_public_host_is_followed(self) -> None:
        routes = ok_routes(
            **{
                f"https://{PUBLIC_HOST}/jobs/1": (301, {"location": "/jobs/2"}, b""),
                f"https://{PUBLIC_HOST}/jobs/2": (
                    200,
                    {"content-type": "text/html"},
                    POSTING_BODY.encode(),
                ),
            }
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertTrue(result.ok)
        self.assertTrue(result.final_url.endswith("/jobs/2"))

    def test_a_redirect_loop_is_reported_rather_than_followed_forever(self) -> None:
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (302, {"location": "/jobs/1"}, b"")}
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "http_error")
        self.assertIn("Too many redirects", result.message)

    def test_only_http_and_https_are_fetched(self) -> None:
        for url in [
            "file:///etc/passwd",
            "ftp://example.test/x",
            "gopher://example.test/x",
            "data:text/html,hello",
            "javascript:alert(1)",
        ]:
            with self.subTest(url=url):
                allowed, reason = is_public_url(url, resolve=resolver())
                self.assertFalse(allowed)
                self.assertIn("scheme", reason)

    def test_an_unsupported_scheme_is_reported_as_such_not_as_a_private_host(self) -> None:
        # Regression: every `is_public_url` failure was reported under
        # reason="private_host", so a `file://` URL told the user their host was
        # private when the real problem was the scheme.
        result = fetch("file:///etc/passwd", FakeFetcher())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unsupported_scheme")


# --------------------------------------------------------------------------- #
# robots.txt
# --------------------------------------------------------------------------- #


class TestRobots(unittest.TestCase):
    def test_robots_is_consulted_before_the_posting(self) -> None:
        fetcher = FakeFetcher(ok_routes())
        fetch(f"https://{PUBLIC_HOST}/jobs/1", fetcher)
        self.assertEqual(
            fetcher.calls[0],
            f"https://{PUBLIC_HOST}/robots.txt",
            "robots.txt must be the first request",
        )
        self.assertIn(f"https://{PUBLIC_HOST}/jobs/1", fetcher.calls)

    def test_a_disallow_is_reported_and_the_posting_is_not_fetched(self) -> None:
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/robots.txt": (200, {"content-type": "text/plain"}, ROBOTS_DISALLOW)}
        )
        fetcher = FakeFetcher(routes)
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", fetcher)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "robots_disallowed")
        self.assertFalse(result.robots_allowed)
        self.assertNotIn(f"https://{PUBLIC_HOST}/jobs/1", fetcher.calls)
        self.assertIn("paste", result.message.lower())

    def test_a_missing_robots_file_means_allowed(self) -> None:
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/robots.txt": (404, {"content-type": "text/plain"}, b"")}
        )
        self.assertTrue(fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes)).ok)

    def test_an_unreachable_robots_file_means_allowed(self) -> None:
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/robots.txt": ConnectionError("dns went away")}
        )
        self.assertTrue(fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes)).ok)

    def test_ignore_robots_skips_the_lookup(self) -> None:
        fetcher = FakeFetcher(ok_routes())
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", fetcher, ignore_robots=True)
        self.assertTrue(result.ok)
        self.assertNotIn(f"https://{PUBLIC_HOST}/robots.txt", fetcher.calls)

    def test_robots_allows_reports_the_disallow_path(self) -> None:
        fetcher = FakeFetcher(
            {f"https://{PUBLIC_HOST}/robots.txt": (200, {"content-type": "text/plain"}, ROBOTS_DISALLOW)}
        )
        allowed, note = robots_allows(f"https://{PUBLIC_HOST}/jobs/1", fetch=fetcher, resolve=resolver())
        self.assertFalse(allowed)
        self.assertIn("/jobs/", note)


# --------------------------------------------------------------------------- #
# Gates and error statuses
# --------------------------------------------------------------------------- #


class TestGatedAndErrorPages(unittest.TestCase):
    def test_http_status_codes_map_to_the_documented_reasons(self) -> None:
        cases = {
            401: "login_required",
            402: "paywall",
            403: "blocked",
            429: "blocked",
            500: "http_error",
            503: "http_error",
        }
        for status, expected in cases.items():
            with self.subTest(status=status):
                routes = ok_routes(
                    **{f"https://{PUBLIC_HOST}/jobs/1": (status, {"content-type": "text/html"}, b"nope")}
                )
                result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, expected)
                self.assertTrue(result.message, "a refusal must tell the user what to do next")
                self.assertIn("paste", result.message.lower())

    def test_a_login_wall_page_is_reported_as_a_login_wall(self) -> None:
        body = b"<html><body><h1>Sign in to continue</h1><p>You must log in to view this job.</p></body></html>"
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, body)}
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "login_required")

    def test_a_paywall_page_is_reported_as_a_paywall(self) -> None:
        body = b"<html><body><h1>Subscribe to read</h1><p>This is premium content.</p></body></html>"
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, body)}
        )
        self.assertEqual(fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes)).reason, "paywall")

    def test_a_bot_check_is_reported_as_a_captcha(self) -> None:
        body = b"<html><body><h1>Just a moment...</h1><p>Verify you are human.</p></body></html>"
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, body)}
        )
        self.assertEqual(fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes)).reason, "captcha")

    def test_a_long_posting_that_merely_mentions_subscribing_is_not_a_paywall(self) -> None:
        # The gate markers are only consulted for pages too short to be a real
        # posting. Otherwise an ordinary posting with a newsletter footer would be
        # refused, and the user would be told to paste text they can already see.
        filler = "You will build training pipelines and evaluate models with the team. " * 6
        body = f"<html><body><main><p>{filler}</p><p>Subscribe to our newsletter.</p></main></body></html>"
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, body.encode())}
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertTrue(result.ok, f"expected a successful read, got {result.reason}")
        self.assertGreater(len(result.text), MIN_USEFUL_CHARS)

    def test_a_non_html_response_is_refused(self) -> None:
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "application/pdf"}, b"%PDF-1.4 ...")}
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_html")

    def test_an_oversized_body_is_refused(self) -> None:
        routes = ok_routes(
            **{
                f"https://{PUBLIC_HOST}/jobs/1": (
                    200,
                    {"content-type": "text/html"},
                    b"x" * (MAX_BYTES + 1),
                )
            }
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "too_large")

    def test_a_page_with_no_readable_text_is_refused(self) -> None:
        routes = ok_routes(
            **{
                f"https://{PUBLIC_HOST}/jobs/1": (
                    200,
                    {"content-type": "text/html"},
                    b"<html><body><script>var x=1;</script></body></html>",
                )
            }
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "not_html")

    def test_network_failures_are_reported_by_kind(self) -> None:
        cases = {
            TimeoutError("too slow"): "timeout",
            ConnectionError("refused"): "network_error",
        }
        for error, expected in cases.items():
            with self.subTest(error=type(error).__name__):
                routes = ok_routes(**{f"https://{PUBLIC_HOST}/jobs/1": error})
                result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
                self.assertFalse(result.ok)
                self.assertEqual(result.reason, expected)

    def test_an_empty_url_is_refused(self) -> None:
        result = fetch_jd("   ", fetch=FakeFetcher(), resolve=resolver())
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "unsupported_scheme")

    def test_every_refusal_carries_a_reason_from_the_documented_set(self) -> None:
        documented = {
            "ok",
            "unsupported_scheme",
            "private_host",
            "robots_disallowed",
            "login_required",
            "paywall",
            "captcha",
            "blocked",
            "too_large",
            "not_html",
            "timeout",
            "network_error",
            "http_error",
        }
        samples = [
            fetch_jd("", fetch=FakeFetcher(), resolve=resolver()),
            fetch("file:///x", FakeFetcher()),
            fetch("http://127.0.0.1/x", FakeFetcher(), resolve=resolver({"127.0.0.1": ["127.0.0.1"]})),
            fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(ok_routes())),
        ]
        for result in samples:
            with self.subTest(reason=result.reason):
                self.assertIn(result.reason, documented)


# --------------------------------------------------------------------------- #
# The successful path
# --------------------------------------------------------------------------- #


class TestSuccessfulRead(unittest.TestCase):
    def test_a_public_posting_is_read(self) -> None:
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(ok_routes()))
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "ok")
        self.assertIn("Machine Learning Intern", result.title)
        self.assertIn("Python, PyTorch, SQL", result.text)
        self.assertGreater(result.chars, MIN_USEFUL_CHARS)
        self.assertEqual(result.chars, len(result.text))

    def test_scripts_navigation_and_footers_are_stripped(self) -> None:
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(ok_routes()))
        self.assertNotIn("tracking", result.text, "script content must not be read")
        self.assertNotIn("color:red", result.text, "style content must not be read")
        self.assertNotIn("Copyright", result.text, "the footer is boilerplate")

    def test_the_text_is_truncated_to_the_configured_limit(self) -> None:
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(ok_routes()), max_chars=80)
        self.assertTrue(result.ok)
        self.assertEqual(len(result.text), 80)
        self.assertIn("truncated", result.message)

    def test_the_user_agent_identifies_the_tool(self) -> None:
        from server.jd_fetch import USER_AGENT

        self.assertIn("RJD", USER_AGENT)
        self.assertNotIn("Mozilla", USER_AGENT, "the tool must not impersonate a browser")

    def test_html_entities_and_whitespace_are_normalised(self) -> None:
        body = (
            b"<html><head><title>T</title></head><body><main><p>"
            + b"A&amp;B   role&nbsp;&nbsp;with      spaces " * 8
            + b"</p></main></body></html>"
        )
        routes = ok_routes(
            **{f"https://{PUBLIC_HOST}/jobs/1": (200, {"content-type": "text/html"}, body)}
        )
        result = fetch(f"https://{PUBLIC_HOST}/jobs/1", FakeFetcher(routes))
        self.assertTrue(result.ok)
        self.assertNotIn("   ", result.text)
        self.assertNotIn("\u00a0", result.text)


class TestReadableText(unittest.TestCase):
    """The extractor, called directly - the fallback path is otherwise untested."""

    def test_it_prefers_the_main_element(self) -> None:
        html = (
            "<html><head><title>Posting</title></head><body>"
            "<div>NAVIGATION CHROME LOGIN SIGNUP</div>"
            "<main><h1>The actual posting</h1><p>Requirements: Python and SQL.</p></main>"
            "</body></html>"
        )
        title, text = extract_readable_text(html, "https://example.test/j")
        self.assertEqual(title, "Posting")
        self.assertIn("The actual posting", text)

    def test_it_falls_back_to_the_largest_text_block(self) -> None:
        html = (
            "<html><body><div>short</div>"
            "<div><p>" + "Long posting text about pipelines and models. " * 5 + "</p></div>"
            "</body></html>"
        )
        _title, text = extract_readable_text(html, "https://example.test/j")
        self.assertIn("pipelines", text)

    def test_it_reads_the_title_from_ld_json_when_there_is_no_title_tag(self) -> None:
        html = (
            '<html><head><script type="application/ld+json">'
            '{"@type":"JobPosting","title":"Data Analyst Intern","hiringOrganization":{"name":"Acme"}}'
            "</script></head><body><main><p>" + "Text. " * 30 + "</p></main></body></html>"
        )
        title, _text = extract_readable_text(html, "https://example.test/j")
        self.assertEqual(title, "Data Analyst Intern")

    def test_it_handles_an_empty_document(self) -> None:
        title, text = extract_readable_text("", "")
        self.assertEqual(title, "")
        self.assertEqual(text.strip(), "")

    def test_it_never_raises_on_malformed_html(self) -> None:
        for html in ["<html><body><p>unclosed", "<<<>>>", "\x00\x01", "<main>"]:
            with self.subTest(html=html[:12]):
                extract_readable_text(html, "https://example.test/j")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
