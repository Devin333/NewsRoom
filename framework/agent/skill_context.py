from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from framework.agent.skill_call import SkillCall
from framework.agent.skill_observation import SkillObservation
from framework.agent.skill_selection import SkillPromptFormatter, SkillSelectionPolicy


class AgentSkillContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    available_skills: list[Any] = Field(default_factory=list)
    selected_skills: list[Any] = Field(default_factory=list)

    def to_prompt_section(self) -> str:
        """Use SkillPromptFormatter."""
        return SkillPromptFormatter().format_available_skills(self.selected_skills)


class SkillRunnerProtocol(Protocol):
    def run(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: Any | None = None,
    ) -> Any:
        ...


class AgentSkillRuntime:
    def __init__(
        self,
        registry: Any,
        runner: SkillRunnerProtocol,
        selection_policy: SkillSelectionPolicy | None = None,
    ) -> None:
        self.registry = registry
        self.runner = runner
        self.selection_policy = selection_policy or SkillSelectionPolicy()
        self.formatter = SkillPromptFormatter()

    def build_prompt_section(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Select visible skills and format prompt section."""
        return self.formatter.format_available_skills(
            self.list_visible_skills(task, context=context)
        )

    def execute_call(self, call: SkillCall, agent_run_id: str) -> SkillObservation:
        """Validate exposure, run SkillRunner, return SkillObservation."""
        ensured_call = call.ensure_call_id()
        try:
            metadata = self._get_metadata(ensured_call.skill_name)
        except Exception as exc:
            return SkillObservation(
                call_id=ensured_call.call_id or "",
                skill_name=ensured_call.skill_name,
                status="failed",
                errors=[str(exc)],
            )
        if metadata is None or not self.selection_policy.exposure_policy.allows(metadata):
            return SkillObservation(
                call_id=ensured_call.call_id or "",
                skill_name=ensured_call.skill_name,
                status="failed",
                errors=["Skill is not allowed by exposure policy"],
            )
        try:
            result = self.runner.run(
                ensured_call.skill_name,
                dict(ensured_call.arguments),
                context=_build_skill_run_context(
                    skill_name=ensured_call.skill_name,
                    agent_run_id=agent_run_id,
                    call_id=ensured_call.call_id or "",
                    reason=ensured_call.reason,
                ),
            )
        except Exception as exc:
            return SkillObservation(
                call_id=ensured_call.call_id or "",
                skill_name=ensured_call.skill_name,
                status="failed",
                errors=[str(exc)],
            )
        return SkillObservation.from_skill_result(ensured_call, result)

    def list_visible_skills(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> list[Any]:
        """Return skills visible to agent."""
        return self.selection_policy.select(
            task,
            self._list_all_skills(),
            context=context,
        )

    def _list_all_skills(self) -> list[Any]:
        list_all = getattr(self.registry, "list_all", None)
        if callable(list_all):
            try:
                skills = list_all(include_disabled=True)
            except TypeError:
                skills = list_all()
            if isinstance(skills, (list, tuple, set)):
                return list(skills)
            return []
        skills = getattr(self.registry, "skills", None)
        if isinstance(skills, list):
            return list(skills)
        return []

    def _get_metadata(self, skill_name: str) -> Any | None:
        get = getattr(self.registry, "get", None)
        if callable(get):
            return get(skill_name)
        canonical = skill_name.strip().lower()
        for metadata in self._list_all_skills():
            name = _metadata_name(metadata).strip().lower()
            if name == canonical:
                return metadata
        return None


def _build_skill_run_context(
    *,
    skill_name: str,
    agent_run_id: str,
    call_id: str,
    reason: str | None,
) -> Any:
    try:
        from framework.skills import SkillRunContext  # type: ignore
    except Exception:
        return {
            "skill_name": skill_name,
            "caller_type": "agent",
            "run_id": agent_run_id,
            "metadata": {
                "agent_run_id": agent_run_id,
                "call_id": call_id,
                "agent_loop": True,
                "skill_call_reason": reason,
            },
        }
    context = SkillRunContext.for_agent(
        skill_name=skill_name,
        agent_run_id=agent_run_id,
        call_id=call_id,
    )
    metadata = getattr(context, "metadata", None)
    if isinstance(metadata, dict):
        metadata.update(
            {
                "agent_loop": True,
                "skill_call_reason": reason,
            }
        )
    return context


def _metadata_name(metadata: Any) -> str:
    canonical_name = getattr(metadata, "canonical_name", None)
    if callable(canonical_name):
        return str(canonical_name())
    if isinstance(metadata, dict):
        return str(metadata.get("name") or "")
    return str(getattr(metadata, "name", "") or "")
