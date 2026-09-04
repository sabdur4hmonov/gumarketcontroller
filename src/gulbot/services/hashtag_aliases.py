"""Seeding the hashtag alias table from the versioned fixture.

Idempotent: run it as often as you like. Rows a human added by hand are left
alone, because they have no fixture_version and the seed only ever touches its
own rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from gulbot.catalog.alias_fixture import ALIASES, FIXTURE_VERSION
from gulbot.catalog.hashtags import normalize_hashtag
from gulbot.models.product import HashtagAlias


@dataclass(frozen=True)
class SeedResult:
    inserted: int
    updated: int
    unchanged: int
    skipped: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def normalized_pairs() -> list[tuple[str, str]]:
    """The fixture, with both sides normalised and no-op pairs dropped.

    A pair whose two sides normalise to the same key would violate the
    alias_differs_from_canonical CHECK, so it is dropped here with the rest of
    the unusable rows rather than blowing up mid-seed.
    """
    pairs = []
    for alias, canonical in ALIASES.items():
        alias_key = normalize_hashtag(alias)
        canonical_key = normalize_hashtag(canonical)
        if not alias_key or not canonical_key or alias_key == canonical_key:
            continue
        pairs.append((alias_key, canonical_key))
    return pairs


async def seed_hashtag_aliases(session: AsyncSession, *, shop_id: int) -> SeedResult:
    """Bring one shop's alias table up to the fixture. Safe to repeat."""
    pairs = normalized_pairs()
    skipped = len(ALIASES) - len(pairs)

    existing = {
        row.alias_normalized: row
        for row in await session.scalars(
            select(HashtagAlias).where(HashtagAlias.shop_id == shop_id)
        )
    }

    inserted = updated = unchanged = 0
    for alias_key, canonical_key in pairs:
        current = existing.get(alias_key)
        if current is None:
            await session.execute(
                insert(HashtagAlias)
                .values(
                    shop_id=shop_id,
                    alias_normalized=alias_key,
                    canonical_hashtag=canonical_key,
                    fixture_version=FIXTURE_VERSION,
                )
                # Concurrent seeds are harmless: the loser does nothing.
                .on_conflict_do_nothing(index_elements=["shop_id", "alias_normalized"])
            )
            inserted += 1
        elif current.fixture_version is None:
            # Somebody edited this by hand. The fixture does not get to
            # overrule them.
            unchanged += 1
        elif current.canonical_hashtag != canonical_key:
            current.canonical_hashtag = canonical_key
            current.fixture_version = FIXTURE_VERSION
            updated += 1
        else:
            unchanged += 1

    await session.flush()
    return SeedResult(inserted=inserted, updated=updated, unchanged=unchanged, skipped=skipped)


async def resolve_alias(session: AsyncSession, *, shop_id: int, tag: str) -> str:
    """Map a tag through the alias table. Returns the tag itself if unaliased."""
    key = normalize_hashtag(tag)
    if not key:
        return ""
    canonical = await session.scalar(
        select(HashtagAlias.canonical_hashtag).where(
            HashtagAlias.shop_id == shop_id, HashtagAlias.alias_normalized == key
        )
    )
    return canonical or key
