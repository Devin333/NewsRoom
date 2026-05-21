from __future__ import annotations

from framework.scoring import ScoreBundle, ScoringResult, features_from_dict, result_to_dict, target_from_dict


def test_dict_adapter_converts_target_features_and_result() -> None:
    target = target_from_dict({"id": "a", "type": "thing", "title": "A"})
    features = features_from_dict({"score": 0.9, "ignored": "x"})
    result = ScoringResult(target_id="a", target_type="thing", recipe_id="r", score=ScoreBundle.from_raw_score(0.9))

    assert target.target_id == "a"
    assert features.get("score") == 0.9
    assert result_to_dict(result)["score"]["final_score"] == 0.9
