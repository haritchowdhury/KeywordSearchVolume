from __future__ import annotations

import copy
import json

from pipeline.pipeline import KeywordPipeline
from tests.fixtures import make_item


class MarketClient:
    def __init__(self):
        self.volumes = {
            "US": {"alpha running shoes": 1000, "beta clothing store": 150},
            "GB": {"alpha running shoes": 400, "beta clothing store": 10},
        }

    def expand(self, seed, market=None):
        return list(self.volumes[(market or {"code": "US"})["code"]])

    def keyword_overview(self, keywords, market=None):
        code = (market or {"code": "US"})["code"]
        return [
            make_item(keyword, self.volumes[code][keyword], 1.25, 0.35, 30,
                      "commercial", trend=5)
            for keyword in keywords
        ]


def two_market_config(cfg, tmp_path):
    config = copy.deepcopy(cfg)
    config.root = tmp_path
    config.paths.raw_dir = "data/raw"
    config.paths.normalized_dir = "data/normalized"
    config.paths.output_dir = "data/output"
    config.filters.min_volume_keep = 100
    config.search.markets = [
        {"code": "US", "name": "United States", "location_code": 2840,
         "language_name": "English"},
        {"code": "GB", "name": "United Kingdom", "location_code": 2826,
         "language_name": "English"},
    ]
    return config


def test_pipeline_emits_cumulative_and_country_metrics(cfg, tmp_path):
    config = two_market_config(cfg, tmp_path)
    result = KeywordPipeline(config, MarketClient()).run(["clothing"])

    output = tmp_path / "data/output"
    keywords = json.loads((output / "keywords.json").read_text())
    alpha = next(row for row in keywords if row["keyword"] == "alpha running shoes")
    assert alpha["search_volume"] == 1400
    assert alpha["available_markets"] == ["GB", "US"]

    manifest = json.loads((output / "markets.json").read_text())
    assert manifest["schema_version"] == 3
    assert [market["code"] for market in manifest["markets"]] == ["US", "GB"]

    us = json.loads((output / "markets/US.json").read_text())
    gb = json.loads((output / "markets/GB.json").read_text())
    assert us["keywords"]["alpha running shoes"]["search_volume"] == 1000
    assert gb["keywords"]["alpha running shoes"]["search_volume"] == 400

    us_beta = us["keywords"]["beta clothing store"]
    gb_beta = gb["keywords"]["beta clothing store"]
    assert "too_little_traffic" not in us_beta["flags"]
    assert "too_little_traffic" in gb_beta["flags"]
    assert gb_beta["recommended"] is False

    assert result["markets"] == config.search.markets
    assert result["outputs"]["market_us_json"].endswith("markets/US.json")


def test_market_request_payload_prefers_location_code(cfg, tmp_path):
    config = two_market_config(cfg, tmp_path)

    # Exercise the payload helper without constructing a network client.
    from pipeline.client import DataForSEOClient

    client = object.__new__(DataForSEOClient)
    client.config = config
    payload = client._market_payload(config.search.markets[1])
    assert payload == {"location_code": 2826, "language_code": "en"}


def test_extract_keywords_supports_related_keyword_shape():
    from pipeline.client import DataForSEOClient

    payload = {"tasks": [{"result": [{"items": [
        {"keyword": "direct suggestion"},
        {"keyword_data": {"keyword": "nested related phrase"}},
    ]}]}]}
    assert DataForSEOClient._extract_keywords(payload) == [
        "direct suggestion", "nested related phrase"
    ]
