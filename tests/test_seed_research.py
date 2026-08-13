import json

import seed_research


def test_load_seeds_deduplicates_cli_values(tmp_path):
    assert seed_research.load_seeds([" Activewear ", "activewear", "men's clothing"], tmp_path / "x") == [
        "Activewear", "men's clothing"
    ]


def test_load_seeds_from_yaml_config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("run:\n  seeds:\n    - streetwear\n    - ' Streetwear '\n    - apparel\n")
    assert seed_research.load_seeds([], path) == ["streetwear", "apparel"]


def test_extract_output_text():
    payload = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "{}"}]}]}
    assert seed_research.extract_output_text(payload) == "{}"


def test_prompt_preserves_seed_anchors():
    prompt = seed_research.build_prompt(["online clothing", "activewear"], "US", "retailer", 20)
    assert 'do not drop modifiers such as "online"' in prompt
    assert "directly traceable to at least one existing seed" in prompt
    assert "Do not simply repeat every input seed" not in prompt


def test_print_table_is_score_sorted_by_ranker(monkeypatch, capsys):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            data = {
                "candidates": [
                    {"seed_phrase": "apparel", "category": "core", "score": 80, "breadth": 90,
                     "retailer_relevance": 85, "trend_potential": 60, "confidence": "high", "reason": "Broad"},
                    {"seed_phrase": "clothing", "category": "core", "score": 95, "breadth": 98,
                     "retailer_relevance": 95, "trend_potential": 70, "confidence": "high", "reason": "Core"},
                ]
            }
            return {"output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(data)}]}]}

    monkeypatch.setattr(seed_research.requests, "post", lambda *args, **kwargs: FakeResponse())
    ranked = seed_research.rank_seeds("key", "model", ["fashion"], "US", "retailer", 2)
    seed_research.print_table(ranked)
    output = capsys.readouterr().out
    assert output.index("clothing") < output.index("apparel")
    assert "model-inferred" in output
