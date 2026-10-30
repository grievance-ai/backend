"""Official-website search: the domain allowlist and the sentence filter."""

import pytest
from app.integrations.websearch import GroundedAnswer, Support, WebPage
from app.integrations.websearch.gemini import parse
from app.services import official_search
from app.services.official_search import filter_official, is_official


@pytest.mark.parametrize(
    "value",
    [
        "https://pmkisan.gov.in/",
        "https://sswcd.punjab.gov.in/en/node/5520",
        "nsap.nic.in",
        "https://www.myscheme.gov.in/schemes/x",
        "PMKISAN.GOV.IN",
    ],
)
def test_government_domains_are_official(value: str) -> None:
    assert is_official(value)


@pytest.mark.parametrize(
    "value",
    [
        "https://gov.in.example.com/scheme",  # the allowed suffix as a subdomain trick
        "https://fakegov.in/",  # not a whole label
        "https://pmkisan-gov.in.co/",
        "https://www.bajajfinserv.in/punjab-pension",
        "https://example.com/?u=pmkisan.gov.in",
        "https://user@evil.com/pmkisan.gov.in",
        "",
    ],
)
def test_other_domains_are_not(value: str) -> None:
    assert not is_official(value)


def _answer() -> GroundedAnswer:
    return GroundedAnswer(
        text="ignored",
        pages=[
            WebPage(url="https://sswcd.punjab.gov.in/en/node/5520", title="sswcd.punjab.gov.in"),
            WebPage(url="https://www.some-news-site.com/story", title="some-news-site.com"),
            WebPage(url="https://pmkisan.gov.in/", title="pmkisan.gov.in"),
        ],
        supports=[
            Support(text="The pension is Rs 1,500 a month.", pages=(0,)),
            Support(text="It will double next year, sources say.", pages=(1,)),
            Support(text="Apply at a Sewa Kendra.", pages=(1, 0)),
            Support(text="Unbacked claim.", pages=()),
        ],
    )


async def test_only_sentences_backed_by_official_pages_are_kept() -> None:
    result = await filter_official(_answer())
    assert result.found
    assert result.text == "The pension is Rs 1,500 a month. Apply at a Sewa Kendra."
    # Only the official page that backs a kept sentence is linked.
    assert result.sources == [
        {"url": "https://sswcd.punjab.gov.in/en/node/5520", "title": "sswcd.punjab.gov.in"}
    ]


async def test_nothing_official_means_not_found() -> None:
    answer = _answer()
    answer.supports = [s for s in answer.supports if s.pages == (1,)]
    result = await filter_official(answer)
    assert not result.found
    assert result.text == ""
    assert result.sources == []


async def test_redirect_links_must_resolve_to_an_official_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"
    targets = {
        f"{redirect}1": "https://pmkisan.gov.in/Rpt.aspx",
        f"{redirect}2": "https://scam-pmkisan.com/apply",  # title claims gov.in, page is not
        f"{redirect}3": None,  # could not be followed
    }

    async def fake_resolve(client: object, url: str) -> str | None:
        return targets[url]

    monkeypatch.setattr(official_search, "_resolve", fake_resolve)
    answer = GroundedAnswer(
        text="ignored",
        pages=[
            WebPage(url=f"{redirect}1", title="pmkisan.gov.in"),
            WebPage(url=f"{redirect}2", title="pmkisan.gov.in"),
            WebPage(url=f"{redirect}3", title="nsap.nic.in"),
        ],
        supports=[
            Support(text="A.", pages=(0,)),
            Support(text="B.", pages=(1,)),
            Support(text="C.", pages=(2,)),
        ],
    )
    result = await filter_official(answer)
    assert result.text == "A. C."
    assert result.sources == [
        {"url": "https://pmkisan.gov.in/Rpt.aspx", "title": "pmkisan.gov.in"},
        {"url": "https://nsap.nic.in/", "title": "nsap.nic.in"},  # site home, not unchecked link
    ]


def test_gemini_grounding_is_parsed() -> None:
    payload = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Rs 1,500 a month."}]},
                "groundingMetadata": {
                    "webSearchQueries": ["punjab old age pension"],
                    "groundingChunks": [
                        {"web": {"uri": "https://x.gov.in/a", "title": "x.gov.in"}}
                    ],
                    "groundingSupports": [
                        {
                            "segment": {"text": "Rs 1,500 a month."},
                            "groundingChunkIndices": [0],
                        }
                    ],
                },
            }
        ]
    }
    answer = parse(payload)
    assert answer.pages == [WebPage(url="https://x.gov.in/a", title="x.gov.in")]
    assert answer.supports == [Support(text="Rs 1,500 a month.", pages=(0,))]
    assert answer.queries == ["punjab old age pension"]

    payload["candidates"][0]["content"] = {"parts": [{"text": "NOT_FOUND"}]}
    assert parse(payload).supports == []
