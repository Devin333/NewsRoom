from __future__ import annotations

from framework.harness.subagents import SubAgentSpec

from business.research.domain.reader_repair import READER_REPAIR_NAMESPACE


def build_reader_repair_subagent_specs() -> tuple[SubAgentSpec, SubAgentSpec]:
    proposer = SubAgentSpec(
        subagent_id="reader_repair_proposer",
        role="repair_proposer",
        purpose="Generate localized reader repair candidates from approved repair context packs.",
        input_schema={"required": ["reader_repair_context_pack"]},
        output_schema={"required": ["repair_summary", "target_region_refs", "patch_operations"]},
        allowed_tools=("retrieval.read_source",),
        allowed_memory_namespaces=(READER_REPAIR_NAMESPACE,),
        context_policy={"allow_sibling_history": False, "allow_private_notes_export": False},
        budget={"max_turns": 4, "max_tool_calls": 2, "max_memory_ops": 0},
    )
    verifier = SubAgentSpec(
        subagent_id="reader_repair_verifier",
        role="repair_verifier",
        purpose="Verify repair candidates with schema, source lineage, localized patch, citation, table, formula, and section gates.",
        input_schema={"required": ["repair_candidate", "source_refs", "gate_inputs"]},
        output_schema={"required": ["verification_results"]},
        allowed_tools=("retrieval.read_source",),
        allowed_memory_namespaces=(READER_REPAIR_NAMESPACE,),
        context_policy={"allow_sibling_history": False, "allow_proposer_private_notes": False},
        budget={"max_turns": 4, "max_tool_calls": 2, "max_memory_ops": 0},
    )
    return proposer, verifier


__all__ = ["build_reader_repair_subagent_specs"]
