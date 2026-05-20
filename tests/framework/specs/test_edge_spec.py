from framework.specs import EdgeCondition, EdgeConditionSpec, EdgeSpec


def test_edge_condition_spec_round_trip() -> None:
    condition = EdgeConditionSpec(expression="outputs.score > 0.7", when_status="succeeded")

    assert condition.is_unconditional() is False
    assert EdgeConditionSpec.from_dict(condition.to_dict()) == condition


def test_edge_spec_accepts_prd_field_names() -> None:
    edge = EdgeSpec(from_step="collect", to_step="normalize")

    assert edge.edge_id == "collect->normalize"
    assert edge.source_step_id == "collect"
    assert edge.target_step_id == "normalize"
    assert edge.is_unconditional() is True


def test_edge_spec_maps_prd_condition_model_to_runtime_condition() -> None:
    edge = EdgeSpec(
        from_step="score",
        to_step="publish",
        condition=EdgeConditionSpec(expression="score >= 0.8"),
    )

    assert edge.condition is EdgeCondition.CONDITIONAL
    assert edge.condition_expr == "score >= 0.8"
