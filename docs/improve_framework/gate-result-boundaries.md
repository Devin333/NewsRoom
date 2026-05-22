# Gate Result Boundaries

NewsRoom uses three gate result families with different ownership.

- `framework.governance.GateResult` is the runtime governance gate result used by workflow, tool, and policy enforcement.
- `framework.scoring.gates.GateResult` is a scoring recipe result used inside scoring/ranking pipelines.
- `framework.skills.quality.SkillQualityGateResult` is a Skill Runtime package/output quality result.

Do not merge these types. Convert explicitly at integration boundaries when a runtime gate needs to record evidence from scoring or skill quality.
