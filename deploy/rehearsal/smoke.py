"""The rehearsal's outside checks, over real HTTPS (DEPLOY step 10).

    python smoke.py <base url> <caddy root CA file> <share page path>

The certificate is VERIFIED against Caddy's internal CA, not skipped: what is
being proven is that HTTPS works end to end. Standard library only. Prints one
line per check; exits non-zero if any fails.
"""

from __future__ import annotations

import ssl
import sys
import time
import urllib.error
import urllib.request

base, ca_file, page_path = sys.argv[1:4]
context = ssl.create_default_context(cafile=ca_file)
failures = 0


def get(path: str) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(base + path, headers={"User-Agent": "rehearsal-smoke"})
    try:
        with urllib.request.urlopen(request, context=context, timeout=20) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode("utf-8", "replace")


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  -- ' + detail if detail else ''}")


status, headers, body = get("/healthz")
check("GET /healthz -> 200", status == 200, str(status))
check("  Content-Security-Policy present", "Content-Security-Policy" in headers)
check("  X-Robots-Tag noindex", "noindex" in headers.get("X-Robots-Tag", ""))
check(
    "  Strict-Transport-Security present",
    "Strict-Transport-Security" in headers,
    headers.get("Strict-Transport-Security", "missing"),
)

for path in ("/admin", "/shop"):
    status, _headers, body = get(path)
    check(f"GET {path} without a session -> 401", status == 401, str(status))

status, _headers, body = get("/demo/yesno")
check("GET /demo/yesno -> 200", status == 200, str(status))

status, _headers, body = get(page_path)
check("a real share page renders over HTTPS", status == 200 and "Rehearsal" in body, str(status))

# The slowest liveness job (check_health) first runs five minutes after
# beat starts; give it that and two more.
deadline = time.monotonic() + 420
while True:
    status, _headers, body = get("/healthz/jobs")
    if status == 200 or time.monotonic() > deadline:
        break
    time.sleep(10)
check("GET /healthz/jobs -> 200 once the worker has run", status == 200, body.strip()[:120])

print(f"{failures} failed")
sys.exit(1 if failures else 0)
