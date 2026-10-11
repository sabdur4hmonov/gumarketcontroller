"""Fill deploy/gulbot.env.example the way DEPLOY step 4 says, for the rehearsal.

    python make_env.py <example> <dev .env holding BOT_TOKEN> <out file>

Production-SHAPED: ENVIRONMENT=production, a fresh random database password,
a fresh Fernet key, an https PUBLIC_BASE_URL, a (dummy) admin id. The one real
value is the DEV bot's token, read from the dev .env. Nothing is printed but
the names it set; the out file is gitignored and deleted by the teardown.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

from cryptography.fernet import Fernet

example, dev_env, out = (Path(a) for a in sys.argv[1:4])

dev = dict(
    line.split("=", 1)
    for line in dev_env.read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
token = dev.get("BOT_TOKEN", "").strip().strip('"')
if not token:
    raise SystemExit("the dev .env has no BOT_TOKEN")

values = {
    "ENVIRONMENT": "production",
    "BOT_TOKEN": token,
    # No platform bot on this machine (an owner's BotFather step); the guard
    # does not require one.
    "PLATFORM_BOT_TOKEN": "",
    "PLATFORM_ADMIN_TELEGRAM_IDS": "111111111",
    "SHOP_TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
    "PUBLIC_BASE_URL": "https://localhost:8443",
}

filled = sorted(values)
lines = []
for line in example.read_text(encoding="utf-8").splitlines():
    key = line.split("=", 1)[0] if "=" in line and not line.startswith("#") else None
    lines.append(f"{key}={values.pop(key)}" if key in values else line)
for key, value in values.items():  # anything the example lacks
    lines.append(f"{key}={value}")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print(f"{out.name}: filled {', '.join(filled)} (values not shown)")
