"""FastAPI entry point for the local web-application assistant.

    python -m server.app                    # bind 127.0.0.1:8765
    python -m server.app --port 9000
    uvicorn server.app:app --host 127.0.0.1 --port 8765

Design constraints, all enforced here rather than documented as intentions:

* **Loopback only.** `run()` calls `security.assert_loopback` before uvicorn is
  started, so binding to 0.0.0.0 fails loudly instead of quietly publishing an
  endpoint that accepts personal data.
* **Stateless.** No endpoint writes user data anywhere. The only file the server
  creates is the access token; the only optional log is fingerprinted and off by
  default (`RJD_SERVER_LOG=1`).
* **One policy implementation.** Routing, validation and error shaping live
  here; every judgement about whether a value may be shown to the user comes from
  `server.services`, which in turn calls `src/`.
* **No parallel abstention logic.** `/generate` does not contain a threshold.
  The threshold arrives from `ConfidenceConfig` inside `services.generate`.

The app is built by `create_app()` so the tests can inject a client, a knowledge
base and a known token without a running network or a real API key.
"""

from __future__ import annotations

import argparse
import os
import sys
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:  # allows `python server/app.py`
    sys.path.insert(0, str(REPO_ROOT))

from src import config  # noqa: E402
from src.llm.client import OpenRouterClient  # noqa: E402

from server import jd_fetch, security, services  # noqa: E402
from server.schemas import (  # noqa: E402
    ErrorResponse,
    ExtractResumeRequest,
    ExtractResumeResponse,
    GenerateRequest,
    GenerateResponse,
    HealthResponse,
    JdAnalyzeRequest,
    JdAnalyzeResponse,
    JdFetchRequest,
    JdFetchResponse,
    PrivacyEcho,
    ScanRequest,
    ScanResponse,
)

API_KEY_HEADER = "X-RJD-Api-Key"


@dataclass
class Runtime:
    """Per-app wiring. Held on `app.state.rjd` so tests can replace any part."""

    client: OpenRouterClient | None = None
    kb_provider: services.KnowledgeBaseProvider | None = None
    token: security.TokenInfo | None = None
    require_token: bool = True


def _runtime(request: Request) -> Runtime:
    return request.app.state.rjd


def _token_info(runtime: Runtime) -> security.TokenInfo:
    """Resolve the token lazily, so importing this module creates no files."""
    if not runtime.require_token:
        runtime.token = security.TokenInfo(token=None, required=False, source="disabled by flag")
        return runtime.token
    if runtime.token is None:
        runtime.token = security.resolve_token()
    return runtime.token


def enforce_token(
    request: Request,
    x_rjd_token: str | None = Header(default=None, alias=security.TOKEN_HEADER),
) -> None:
    """Gate every data endpoint behind the shared token, when one is configured.

    Named `enforce_token` rather than `require_token` on purpose: `create_app`
    takes a keyword of that name, and a module-level function of the same name
    would be shadowed inside the factory - which is exactly the bug this comment
    exists to stop someone reintroducing.
    """
    runtime = _runtime(request)
    info = _token_info(runtime)
    if not info.required:
        return
    if not security.constant_time_equal(x_rjd_token, info.token):
        raise HTTPException(
            status_code=401,
            detail=(
                f"missing or wrong {security.TOKEN_HEADER}. The token is printed at startup and "
                f"stored at {security.token_path()}; paste it into the extension's settings."
            ),
        )


def _client_for(runtime: Runtime, api_key: str | None) -> OpenRouterClient:
    """An LLM client for this request.

    A key supplied per request takes precedence over the environment, is used for
    that request only, and is never written anywhere. With neither, the client
    runs offline and says so in the response `mode` - the extension must never be
    able to present stub output as model output.
    """
    if runtime.client is not None:
        return runtime.client
    if api_key and api_key.strip():
        return OpenRouterClient(api_key=api_key.strip())
    return services.new_client()


def create_app(
    *,
    client: OpenRouterClient | None = None,
    kb_provider: services.KnowledgeBaseProvider | None = None,
    require_token: bool = True,
    token: str | None = None,
    lifespan: Any = None,
) -> FastAPI:
    """Build the app. Injected pieces are used as-is; nothing is built eagerly."""
    runtime = Runtime(
        client=client,
        kb_provider=kb_provider,
        require_token=require_token,
        token=(
            security.TokenInfo(token=token, required=bool(token), source="injected")
            if token is not None
            else None
        ),
    )

    @asynccontextmanager
    async def default_lifespan(app: FastAPI):
        info = _token_info(runtime)
        banner = config.banner()
        print(f"[server] {config.get('app', 'name', default='rjd')}")
        print(f"[server] prototype notice: {banner}")
        print(f"[server] mode: {'live_api' if not _default_offline() else 'offline_stub (no API key found)'}")
        print(f"[server] auth  : {info.describes()}")
        if info.required and info.source != "injected":
            print(f"[server] token : {info.token}")
        print(f"[server] bind  : 127.0.0.1 only (loopback enforced)")
        try:
            yield
        finally:
            provider = runtime.kb_provider
            if provider is not None:
                provider.close()

    app = FastAPI(
        title="Graduate Resume-JD Matcher - web-form assistant backend",
        version=str(config.get("app", "version", default="0.3.0")),
        description=(
            "Local-only backend for the Chrome extension. Holds no user data: every "
            "request is processed in memory and nothing is written to disk."
        ),
        lifespan=lifespan or default_lifespan,
    )
    app.state.rjd = runtime

    app.add_middleware(
        CORSMiddleware,
        # Pinned to extension origins. `*` would let any site the user visits read
        # their profile out of this server.
        allow_origin_regex=str(
            config.get("server", "cors_origin_regex", default=security.ALLOWED_ORIGIN_REGEX)
        ),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", security.TOKEN_HEADER, API_KEY_HEADER],
    )

    # ------------------------------------------------------------------ health

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health(request: Request) -> HealthResponse:
        """Liveness plus what the extension needs to configure itself.

        Deliberately unauthenticated and deliberately free of user data: the
        extension needs to know whether the backend is up, what mode it is in and
        whether a token will be required, before it can send anything.
        """
        rt = _runtime(request)
        info = _token_info(rt)
        provider = rt.kb_provider or services.DEFAULT_KB_PROVIDER
        client_obj = rt.client
        offline = _default_offline() if client_obj is None else client_obj.offline
        return HealthResponse(
            status="ok",
            app=str(config.get("app", "name", default="")),
            version=str(config.get("app", "version", default="")),
            mode="offline_stub" if offline else "live_api",
            model=(
                "offline-deterministic-stub"
                if offline
                else (client_obj.cfg.model if client_obj is not None else config.LLMConfig.load().model)
            ),
            bind_host=str(config.get("server", "host", default="127.0.0.1")),
            bind_port=int(config.get("server", "port", default=8765)),
            auth_required=bool(info.required),
            knowledge_base=provider.describe(),
            sensitive_policy={
                "never_generated": [
                    "national identity / ID card number",
                    "passport number",
                    "social security number",
                    "residence permit number",
                    "tax identification number",
                    "driving licence number",
                ],
                "behaviour": "reported as sensitive_skipped with no value, and never sent to the model",
            },
            privacy={
                "in_memory_only": True,
                "persisted": False,
                "logs_raw_user_text": False,
                "action_log_enabled": _action_log_enabled(),
                "action_log_records": "counts and sha256 prefixes only",
            },
            prototype_banner=config.banner(),
            non_use_notice=config.non_use_notice(),
        )

    # -------------------------------------------------------------------- scan

    @app.post("/scan", response_model=ScanResponse, tags=["form"], dependencies=[Depends(enforce_token)])
    def scan(payload: ScanRequest) -> ScanResponse:
        """Normalise the controls the content script found on the page."""
        try:
            return services.scan(payload)
        except Exception as exc:  # noqa: BLE001 - a crash must be a clean 500, not a stack trace
            raise HTTPException(status_code=500, detail=f"scan failed: {type(exc).__name__}: {exc}") from exc

    # ---------------------------------------------------------------- generate

    @app.post("/generate", response_model=GenerateResponse, tags=["form"], dependencies=[Depends(enforce_token)])
    def generate(
        payload: GenerateRequest,
        request: Request,
        x_rjd_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> GenerateResponse:
        """Draft a suggestion for every field, using only the authorised modules."""
        rt = _runtime(request)
        client_obj = _client_for(rt, x_rjd_api_key)
        try:
            return services.generate(
                payload,
                client=client_obj,
                kb_provider=rt.kb_provider,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"generate failed: {type(exc).__name__}: {exc}"
            ) from exc

    # --------------------------------------------------------- extract_resume

    @app.post(
        "/extract_resume",
        response_model=ExtractResumeResponse,
        tags=["form"],
        dependencies=[Depends(enforce_token)],
    )
    def extract_resume(payload: ExtractResumeRequest) -> ExtractResumeResponse:
        """Turn resume text into a profile the user confirms before it replaces anything.

        The extension parses the PDF in the browser and posts only the text, so
        there is no upload here and no file to store. Nothing is persisted: the
        text is read from the request, the profile is returned, and no code path
        in this module writes either to disk (H3).
        """
        try:
            return services.extract_profile_from_text(payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"extract_resume failed: {type(exc).__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ jd/...

    @app.post("/jd/fetch", response_model=JdFetchResponse, tags=["jd"], dependencies=[Depends(enforce_token)])
    def jd_fetch_endpoint(payload: JdFetchRequest) -> JdFetchResponse:
        """Read a public posting. Gated or non-public pages are refused, not worked around."""
        return jd_fetch.fetch_jd(
            payload.url,
            ignore_robots=payload.ignore_robots,
            max_chars=int(config.get("server", "max_fetch_chars", default=20000)),
        )

    @app.post("/jd/analyze", response_model=JdAnalyzeResponse, tags=["jd"], dependencies=[Depends(enforce_token)])
    def jd_analyze_endpoint(
        payload: JdAnalyzeRequest,
        request: Request,
        x_rjd_api_key: str | None = Header(default=None, alias=API_KEY_HEADER),
    ) -> JdAnalyzeResponse:
        """Analyse posting text. Same code path `/generate` uses, so the two agree."""
        rt = _runtime(request)
        client_obj = _client_for(rt, x_rjd_api_key)
        prepared = services.prepare_inputs(
            payload.profile, payload.authorised_modules, payload.jd_text
        )
        try:
            analysis, notes = services.analyse_jd(
                prepared.jd_clean,
                profile_clean=prepared.profile_clean,
                client=client_obj,
                condition=payload.condition,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=500, detail=f"jd analysis failed: {type(exc).__name__}: {exc}"
            ) from exc
        return JdAnalyzeResponse(
            run_id=services.now_run_id(),
            mode="offline_stub" if client_obj.offline else "live_api",
            model="offline-deterministic-stub" if client_obj.offline else client_obj.cfg.model,
            condition=payload.condition.upper(),
            jd_analysis=analysis,
            privacy=PrivacyEcho(
                authorised_modules=list(payload.authorised_modules),
                used_modules=list(prepared.rendered.used_modules),
                dropped_modules=list(prepared.rendered.dropped_modules),
            ),
            notes=list(notes) + list(prepared.notes),
        )

    @app.exception_handler(security.InsecureBindError)
    async def _insecure_bind(_request: Request, exc: security.InsecureBindError):
        return _json_error(500, str(exc), reason="insecure_bind")

    return app


def _json_error(status_code: int, detail: str, *, reason: str = "") -> Any:
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=status_code,
        content=ErrorResponse(detail=detail, reason=reason).model_dump(),
    )


#: Module-level app for `uvicorn server.app:app`. The token is resolved on
#: startup, not at import, so importing this module has no side effects.
app = create_app()


def _default_offline() -> bool:
    return OpenRouterClient().offline


def _action_log_enabled() -> bool:
    return os.getenv("RJD_SERVER_LOG", "0").strip() in {"1", "true", "yes", "on"}


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local web-form assistant backend")
    parser.add_argument("--host", default=str(config.get("server", "host", default="127.0.0.1")))
    parser.add_argument("--port", type=int, default=int(config.get("server", "port", default=8765)))
    parser.add_argument(
        "--no-token",
        action="store_true",
        help="disable the shared-token check (loopback only; useful for a first local test)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help=(
            "uvicorn autoreload (development). Reload needs an import string, so this mode "
            "always uses the default app, and --no-token is ignored."
        ),
    )
    args = parser.parse_args(argv)

    # Before uvicorn starts: an accidental 0.0.0.0 must fail here.
    security.assert_loopback(args.host)

    import uvicorn

    if args.reload:
        uvicorn.run("server.app:app", host=args.host, port=args.port, reload=True, log_level="info")
        return 0

    application = create_app(require_token=not args.no_token)
    uvicorn.run(application, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the e2e script
    raise SystemExit(run())
