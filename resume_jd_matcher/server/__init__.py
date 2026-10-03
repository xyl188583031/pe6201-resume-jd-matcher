"""Local FastAPI backend for the Chrome "web application auto-fill assistant".

This package wraps the *existing* `src/` pipeline. It does not re-implement any
of it: the abstention rule, the anti-fabrication guards, the similarity
calibration, the prompt-hijack sanitiser and the retrieval store are all called
from `src/`, so the browser path and the evaluation path cannot drift apart.

Import graph, deliberately one-directional:

    server.app      HTTP: routing, auth, CORS, validation errors
      server.services  orchestration: compose src/ calls, own no policy
        src.*            the pipeline itself

Nothing under `src/` imports from `server/`.
"""

from __future__ import annotations

__all__ = ["app", "schemas", "services", "field_map", "jd_fetch", "security"]
