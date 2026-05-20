from framework.specs import WorkflowTriggerSpec, WorkflowTriggerType


def test_trigger_spec_prd_shape_round_trip() -> None:
    trigger = WorkflowTriggerSpec(
        trigger_id="nightly",
        trigger_type=WorkflowTriggerType.SCHEDULE,
        config={"cron": "0 8 * * *"},
        enabled=False,
    )

    payload = trigger.to_dict()
    restored = WorkflowTriggerSpec.from_dict(payload)

    assert payload["trigger_type"] == "schedule"
    assert payload["config"] == {"cron": "0 8 * * *"}
    assert restored == trigger
