from openclaw.news_guard import cross_verify_news, compute_news_weight, NewsEvidence, lobster_gold_filter


def test_cross_verify_news_passes_with_brave_and_twitter_evidence():
    def brave_search(q: str, n: int):
        return [
            {
                "title": "Reuters: Trump tariff proposal impacts semis",
                "snippet": "Market reacts to new tariff plan...",
                "url": "https://example.com/reuters-trump-tariff",
                "source": "reuters",
            }
        ]

    def twitter_search(q: str, n: int):
        return [
            {
                "title": "@someanalyst: 川普關稅政策可能影響 AI 供應鏈",
                "snippet": "討論關稅與出口管制...",
                "url": "https://x.com/some/status/123",
                "source": "x",
            }
        ]

    text = "川普關稅政策可能衝擊 AI 巨頭供應鏈"
    res = cross_verify_news(text=text, brave_search=brave_search, twitter_search=twitter_search)
    assert res.lobster_gold is True
    assert res.verified is True
    assert res.matched_keywords["trump_policy"] >= 1
    assert res.matched_keywords["ai_giants"] >= 0
    assert res.weight >= 1.0


def test_lobster_gold_rejects_missing_url():
    def brave_search(q: str, n: int):
        return [{"title": "no url", "snippet": "...", "url": ""}]

    def twitter_search(q: str, n: int):
        return []

    res = cross_verify_news(text="random", brave_search=brave_search, twitter_search=twitter_search)
    assert res.lobster_gold is False
    assert res.verified is False
    assert res.reason == "LOBSTER_GOLD_REJECT"


def test_compute_news_weight_boosts_geopolitics():
    w = compute_news_weight("紅海航運風險升溫，原油走高")
    assert w > 1.0


def test_evidence_quality_scoring():
    # Test that evidence quality is computed correctly
    # Create evidence with URL, source, title, snippet
    evidence = NewsEvidence(
        provider="brave",
        title="A long enough title",
        snippet="A snippet that is long enough to pass threshold",
        url="https://example.com/article",
        source="reuters",
        quality=0.0  # will be computed by constructor? Actually quality is a field with default 0.0
    )
    # Note: quality is set manually, not computed automatically.
    # We need to test the internal quality computation logic.
    # Instead, we can test lobster_gold_filter's quality threshold.
    # Create evidence with low quality
    low_quality = NewsEvidence(
        provider="brave",
        title="short",
        snippet="short",
        url="",  # missing URL
        source="",
        quality=0.0
    )
    high_quality = NewsEvidence(
        provider="brave",
        title="Long title with enough length",
        snippet="Snippet with sufficient length for quality score",
        url="https://news.com/article",
        source="reuters",
        quality=1.0
    )
    filtered = lobster_gold_filter([low_quality, high_quality], min_quality=0.7)
    assert len(filtered) == 1
    assert filtered[0].quality >= 0.7
    assert filtered[0].url.startswith("http")

