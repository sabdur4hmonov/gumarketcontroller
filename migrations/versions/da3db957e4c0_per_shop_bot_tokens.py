"""per-shop bot tokens

Each shop speaks through its own Telegram bot, so each shop needs its own
token -- stored ENCRYPTED, because a bot token is the whole of a shop's
Telegram identity:

  * `bot_token_encrypted` -- Fernet ciphertext, never the token. Written and
    read only through `gulbot.services.shop_tokens`, with the key from
    SHOP_TOKEN_ENCRYPTION_KEY. Nullable: a shop exists before its owner hands
    a token over. A CHECK refuses anything that is not Fernet-shaped, so a
    token pasted in through psql is rejected by the database itself.
  * `uses_process_bot_token` -- the one shop allowed to keep using the process
    BOT_TOKEN, so the deployment already running does not stop. Set HERE, on
    the single pre-existing shop, and nowhere else; the registry logs every
    use, because the fallback is meant to be retired.

"The single pre-existing shop" is literal. With several shops already present
there is no single one -- and `resolve_single_shop` refuses to start such a
deployment anyway -- so none is flagged.

Downgrading DROPS every stored token.

AUTOGENERATE DOES NOT SEE THE CHECK; see CONTRIBUTING.md.

Revision ID: da3db957e4c0
Revises: 93b90673b997
Create Date: 2026-09-27 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "da3db957e4c0"
down_revision: str | None = "93b90673b997"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("bot_token_encrypted", sa.Text(), nullable=True))
    op.add_column(
        "shops",
        sa.Column(
            "uses_process_bot_token",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "bot_token_is_ciphertext",
        "shops",
        sa.text("bot_token_encrypted IS NULL OR bot_token_encrypted LIKE 'gAAAAA%'"),
    )
    op.execute(
        "UPDATE shops SET uses_process_bot_token = true WHERE (SELECT count(*) FROM shops) = 1"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_shops_bot_token_is_ciphertext"), "shops", type_="check")
    op.drop_column("shops", "uses_process_bot_token")
    op.drop_column("shops", "bot_token_encrypted")
