#!/usr/bin/env bash
# One-shot driver for `browser_check.mjs`.
#
# Everything the check needs has to be started and torn down inside a single
# shell invocation: this machine reclaims background jobs as soon as the call
# that started them returns, so a two-step "start the servers, then run the
# check" split leaves nothing listening by the time the second step runs.
#
# What it starts
#   1. the backend            python -m server.app --port 8765
#   2. the static demo pages  python -m http.server 8770 --directory demo
#   3. Edge, with the built extension loaded unpacked, on a throwaway profile
#
# The throwaway profile must live *outside* the repository (a repo-relative one
# would be swept up by the checker and by git) and must be empty (pointing
# --user-data-dir at a profile that already exists makes Edge hand the request
# to the running instance and silently drop --load-extension).
#
# Usage: bash extension/scripts/_run_browser_check.sh [extra browser_check flags]
set -u

# Binaries and paths, resolved rather than hard-coded, so this runs on a machine
# that is not the author's.  Override with RJD_PYTHON, RJD_NODE, RJD_EDGE,
# RJD_LOG_DIR.
PY="${RJD_PYTHON:-python}"
NODE="${RJD_NODE:-node}"

# The repository root, from this script's own location (extension/scripts/).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Git Bash reports POSIX paths; Edge and Python are Windows binaries and want a
# drive letter.  cygpath is absent on macOS and Linux, where this is a no-op.
if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -m "$ROOT")"
fi

# The browser. A branded Chrome silently loads nothing from --load-extension, so
# this check wants Edge.
EDGE="${RJD_EDGE:-}"
if [ -z "$EDGE" ]; then
  for candidate in \
    "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
    "/c/Program Files/Microsoft/Edge/Application/msedge.exe" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "$(command -v microsoft-edge 2>/dev/null || true)" \
    "$(command -v msedge 2>/dev/null || true)"
  do
    if [ -n "$candidate" ] && [ -e "$candidate" ]; then EDGE="$candidate"; break; fi
  done
fi
if [ -z "$EDGE" ]; then
  echo "no Edge found - set RJD_EDGE to the browser binary and run again"
  exit 2
fi

PROFILE="${TMPDIR:-/tmp}/rjd_edge_profile_run$$"
LOG_DIR="${RJD_LOG_DIR:-${TMPDIR:-/tmp}}"
EXT="$ROOT/extension/dist"
DEMO_URL="http://127.0.0.1:8770/application_form.html"

BACKEND_PID=""
DEMO_PID=""
EDGE_STARTED=0

cleanup() {
  # Close the browser this script started, and only that one. `Browser.close`
  # over CDP reaches the instance bound to our throwaway profile; killing
  # msedge.exe by image name would take the user's own windows with it.
  if [ "$EDGE_STARTED" = "1" ]; then
    "$NODE" -e '
      (async () => {
        try {
          const v = await (await fetch("http://127.0.0.1:9222/json/version")).json();
          const ws = new WebSocket(v.webSocketDebuggerUrl);
          await new Promise((r) => { ws.addEventListener("open", r, { once: true });
                                     ws.addEventListener("error", r, { once: true }); });
          ws.send(JSON.stringify({ id: 1, method: "Browser.close", params: {} }));
          await new Promise((r) => setTimeout(r, 1500));
        } catch { /* already gone */ }
      })();
    ' >/dev/null 2>&1 || true
  fi
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" >/dev/null 2>&1
  [ -n "$DEMO_PID" ] && kill "$DEMO_PID" >/dev/null 2>&1
  sleep 1
  # Guard the delete: only ever remove a directory this script created.
  case "$PROFILE" in
    */rjd_edge_profile_run*) rm -rf "$PROFILE" >/dev/null 2>&1 ;;
  esac
}
trap cleanup EXIT

cd "$ROOT" || exit 2

# Refuse to run while anything else holds the ports.
#
# Starting a second backend when an older one already owns 8765 does not fail:
# the new process dies on the bind, the *old* one keeps answering `/health`, and
# every check then runs against a stale build. That is how a missing route once
# presented itself as a frontend bug - the run reported `Not Found` from
# `/extract_resume` while the source plainly registered it. Fail loudly instead.
for port in 8765 8770 9222; do
  busy=$(netstat -ano | grep LISTENING | grep -E "[:.]$port[[:space:]]" || true)
  if [ -n "$busy" ]; then
    echo "port $port is already in use; stop whatever is listening there and run again:"
    echo "$busy"
    exit 2
  fi
done

echo "== starting the backend on 127.0.0.1:8765 =="
"$PY" -m server.app --port 8765 >"$LOG_DIR/rjd_backend.log" 2>&1 &
BACKEND_PID=$!
for _ in $(seq 1 80); do
  curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1 && break
  sleep 0.5
done
if ! curl -sf http://127.0.0.1:8765/health >/dev/null 2>&1; then
  echo "backend never came up; see $LOG_DIR/rjd_backend.log"
  tail -20 "$LOG_DIR/rjd_backend.log"
  exit 2
fi
echo "backend up (pid $BACKEND_PID)"

echo "== starting the demo pages on 127.0.0.1:8770 =="
"$PY" -m http.server 8770 --bind 127.0.0.1 --directory demo >"$LOG_DIR/rjd_demo.log" 2>&1 &
DEMO_PID=$!
for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:8770/application_form.html" >/dev/null 2>&1 && break
  sleep 0.5
done
echo "demo pages up (pid $DEMO_PID)"

echo "== starting Edge on a throwaway profile =="
rm -rf "$PROFILE"
"$EDGE" \
  --user-data-dir="$PROFILE" \
  --load-extension="$EXT" \
  --disable-extensions-except="$EXT" \
  --remote-debugging-port=9222 \
  --no-first-run --no-default-browser-check --disable-sync \
  --new-window "$DEMO_URL" >/dev/null 2>&1 &
EDGE_STARTED=1

for _ in $(seq 1 80); do
  curl -sf http://127.0.0.1:9222/json/version >/dev/null 2>&1 && break
  sleep 0.5
done
if ! curl -sf http://127.0.0.1:9222/json/version >/dev/null 2>&1; then
  echo "Edge never opened a debug port; is $EDGE present?"
  exit 2
fi
echo "edge up (debug port 9222)"

# Confirm the unpacked extension really was loaded, from the profile, not from
# the command line: a branded Chrome accepts the flag and loads nothing.
"$PY" - "$PROFILE" "$EXT" <<'PYEOF'
import json, pathlib, sys
profile, ext = pathlib.Path(sys.argv[1]), sys.argv[2]
prefs = profile / "Default" / "Secure Preferences"
if not prefs.exists():
    print("  (no Secure Preferences yet - the load cannot be confirmed here)")
    raise SystemExit(0)
data = json.loads(prefs.read_text(encoding="utf-8"))
found = [
    (eid, info.get("location"), info.get("disable_reasons"))
    for eid, info in (data.get("extensions") or {}).get("settings", {}).items()
    if (info.get("path") or "").lower() == ext.lower()
]
if not found:
    print("  WARNING: no unpacked extension in the profile points at", ext)
for eid, location, reasons in found:
    print(f"  loaded {eid} location={location} disable_reasons={reasons}")
PYEOF

echo "== running browser_check.mjs =="
"$NODE" extension/scripts/browser_check.mjs "$@"
STATUS=$?
echo "BROWSER_CHECK_EXIT=$STATUS"
exit $STATUS
