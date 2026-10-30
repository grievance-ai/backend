"""Scheme shortlist: all schemes while the list is small, by meaning once it grows."""

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from app.core.config import settings
from app.integrations.embeddings import EmbeddingError
from app.integrations.embeddings.mock import MockEmbeddingProvider
from app.models.scheme import Scheme, SchemeEmbedding
from app.services import scheme_search
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

TOPICS = {
    "pension": "Monthly pension for elderly widows and old age citizens.",
    "tractor": "Subsidy for farmers buying a tractor or farm machinery.",
    "scholarship": "Scholarship for college students from poor families.",
    "cylinder": "Free gas cylinder connection for rural kitchens.",
}


@pytest_asyncio.fixture
async def schemes(db: AsyncSession) -> AsyncIterator[dict[str, Scheme]]:
    """Throwaway schemes (the test database is shared and never reset)."""
    tag = uuid.uuid4().hex[:8]
    rows = {
        topic: Scheme(
            slug=f"test-{topic}-{tag}",
            name=f"Test {topic.title()} Scheme {tag}",
            # A unique code word, so a query can single out these schemes from the
            # real ones that share the database.
            description=f"{text} Code {tag}.",
            benefits="Help.",
            keywords=[topic],
        )
        for topic, text in TOPICS.items()
    }
    db.add_all(rows.values())
    await db.commit()
    yield rows
    ids = [s.id for s in rows.values()]
    await db.execute(delete(SchemeEmbedding).where(SchemeEmbedding.scheme_id.in_(ids)))
    await db.execute(delete(Scheme).where(Scheme.id.in_(ids)))
    await db.commit()
    scheme_search._matrix_cache.clear()


def _order(result: list[Scheme], schemes: dict[str, Scheme]) -> list[str]:
    """The test schemes' topics in the order the shortlist ranked them."""
    topic = {s.id: t for t, s in schemes.items()}
    return [topic[s.id] for s in result if s.id in topic]


@pytest.fixture
def search_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend the knowledge base is big enough to need a shortlist."""
    monkeypatch.setattr(settings, "scheme_full_injection_limit", 1)
    monkeypatch.setattr(settings, "scheme_shortlist_size", 3)


async def test_small_knowledge_base_sends_everything(
    db: AsyncSession, schemes: dict[str, Scheme], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "scheme_full_injection_limit", 100_000)
    before = MockEmbeddingProvider.calls
    result = await scheme_search.shortlist(db, query="anything")
    assert {s.id for s in schemes.values()} <= {s.id for s in result}
    assert MockEmbeddingProvider.calls == before  # no embedding call needed


async def test_shortlist_ranks_by_meaning(
    db: AsyncSession, schemes: dict[str, Scheme], search_on: None
) -> None:
    await scheme_search.refresh_embeddings(db)
    # The offline mock ranks by shared words (the live model ranks by meaning).
    tag = schemes["tractor"].slug.rsplit("-", 1)[-1]
    result = await scheme_search.shortlist(db, query=f"subsidy to buy a tractor machinery {tag}")
    assert len(result) == 3
    # The real schemes share this database, so compare only the test schemes.
    assert _order(result, schemes)[0] == "tractor"
    assert all(s.conditions is not None for s in result)  # details loaded for the prompt


async def test_discussed_schemes_stay_in_the_shortlist(
    db: AsyncSession, schemes: dict[str, Scheme], search_on: None
) -> None:
    await scheme_search.refresh_embeddings(db)
    tag = schemes["tractor"].slug.rsplit("-", 1)[-1]
    result = await scheme_search.shortlist(
        db, query=f"tractor for my farm {tag}", discussed=[schemes["pension"].id]
    )
    assert result[0].id == schemes["pension"].id
    assert schemes["tractor"].id in [s.id for s in result]


async def test_refresh_only_embeds_new_or_changed_schemes(
    db: AsyncSession, schemes: dict[str, Scheme]
) -> None:
    await scheme_search.refresh_embeddings(db)
    assert await scheme_search.refresh_embeddings(db) == 0

    schemes["cylinder"].description = "Free LPG connection for women."
    await db.commit()
    assert await scheme_search.refresh_embeddings(db) == 1
    row = await db.scalar(
        select(SchemeEmbedding).where(SchemeEmbedding.scheme_id == schemes["cylinder"].id)
    )
    assert row is not None and row.model == "mock:64"


async def test_falls_back_to_keywords_when_embeddings_fail(
    db: AsyncSession,
    schemes: dict[str, Scheme],
    search_on: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await scheme_search.refresh_embeddings(db)

    async def broken(self: MockEmbeddingProvider, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("provider down")

    monkeypatch.setattr(MockEmbeddingProvider, "embed", broken)
    result = await scheme_search.shortlist(db, query="scholarship for college students")
    assert _order(result, schemes)[0] == "scholarship"


async def test_inactive_and_other_state_schemes_are_left_out(
    db: AsyncSession, schemes: dict[str, Scheme], search_on: None
) -> None:
    schemes["tractor"].is_active = False
    schemes["pension"].state_code = "HR"
    await db.commit()
    await scheme_search.refresh_embeddings(db)
    ids = [s.id for s in await scheme_search.shortlist(db, query="tractor pension")]
    assert schemes["tractor"].id not in ids
    assert schemes["pension"].id not in ids
