from openclaw.news_guard import cross_verify_news, compute_news_weight


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
