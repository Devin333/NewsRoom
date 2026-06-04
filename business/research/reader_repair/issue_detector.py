from __future__ import annotations

from business.research.domain import ResearchDocument, ResearchReaderPayload, stable_research_id
from business.research.domain.reader_repair import ReaderIssue, ReaderIssueType
from business.research.reader_repair.issue_signature import build_reader_issue_signature
from business.research.reader.gates import validate_reader_navigation, validate_reader_payload_schema, validate_reader_source_lineage


class ReaderRepairIssueDetector:
    def detect(
        self,
        payload: ResearchReaderPayload,
        *,
        run_id: str | None = None,
        step_id: str = "build_reader_payload",
        source_format: str | None = "pdf",
    ) -> list[ReaderIssue]:
        issues: list[ReaderIssue] = []
        gate_checks = (
            (validate_reader_payload_schema(payload), "reader_payload_schema_error", "Reader payload violates schema."),
            (validate_reader_source_lineage(payload), "source_lineage_missing", "Reader payload has no source refs."),
            (validate_reader_navigation(payload), "section_boundary_error", "Reader payload navigation is missing or inconsistent."),
        )
        for gate_result, issue_type, symptom in gate_checks:
            if not gate_result.passed:
                issues.append(
                    self._issue(
                        payload=payload,
                        issue_type=issue_type,
                        symptom=gate_result.reasons[0] if gate_result.reasons else symptom,
                        run_id=run_id,
                        step_id=step_id,
                        source_format=source_format,
                        detector_evidence=[gate_result.gate_name],
                    )
                )
        issues.extend(self._detect_document_asset_issues(payload.document, payload=payload, run_id=run_id, step_id=step_id, source_format=source_format))
        return _dedupe_issues(issues)

    def _detect_document_asset_issues(
        self,
        document: ResearchDocument,
        *,
        payload: ResearchReaderPayload,
        run_id: str | None,
        step_id: str,
        source_format: str | None,
    ) -> list[ReaderIssue]:
        issues: list[ReaderIssue] = []
        if not document.sections:
            issues.append(
                self._issue(
                    payload=payload,
                    issue_type="section_boundary_error",
                    symptom="Reader payload has no section boundary navigation.",
                    run_id=run_id,
                    step_id=step_id,
                    source_format=source_format,
                    detector_evidence=["payload.navigation"],
                )
            )
            issues.append(
                self._issue(
                    payload=payload,
                    issue_type="missing_required_section",
                    symptom="Reader document has no sections.",
                    run_id=run_id,
                    step_id=step_id,
                    source_format=source_format,
                    detector_evidence=["document.sections"],
                )
            )
        for table in document.tables:
            if table.rows and table.columns and any(set(row) - set(table.columns) for row in table.rows):
                issues.append(
                    self._issue(
                        payload=payload,
                        issue_type="table_parse_error",
                        symptom="Table row contains cells outside declared columns.",
                        run_id=run_id,
                        step_id=step_id,
                        source_format=source_format,
                        source_refs=[table.source_ref],
                        detector_evidence=[table.table_id],
                    )
                )
        for equation in document.equations:
            if "??" in equation.latex or "placeholder" in equation.latex.casefold():
                issues.append(
                    self._issue(
                        payload=payload,
                        issue_type="formula_render_error",
                        symptom="Formula contains an unresolved placeholder.",
                        run_id=run_id,
                        step_id=step_id,
                        source_format=source_format,
                        source_refs=[equation.source_ref],
                        detector_evidence=[equation.equation_id],
                    )
                )
        for reference in document.references:
            if not reference.title.strip():
                issues.append(
                    self._issue(
                        payload=payload,
                        issue_type="reference_parse_error",
                        symptom="Reference title is missing.",
                        run_id=run_id,
                        step_id=step_id,
                        source_format=source_format,
                        source_refs=[reference.source_ref],
                        detector_evidence=[reference.reference_id],
                    )
                )
        return issues

    def _issue(
        self,
        *,
        payload: ResearchReaderPayload,
        issue_type: ReaderIssueType,
        symptom: str,
        run_id: str | None,
        step_id: str,
        source_format: str | None,
        source_refs: list[str] | None = None,
        detector_evidence: list[str] | None = None,
    ) -> ReaderIssue:
        signature = build_reader_issue_signature(
            issue_type=issue_type,
            symptom=symptom,
            step_id=step_id,
            source_format=source_format,
        )
        refs = source_refs or payload.source_lineage.source_refs
        return ReaderIssue(
            issue_id=stable_research_id("reader_issue", payload.payload_id, signature.value),
            paper_id=payload.paper.paper_id,
            run_id=run_id,
            step_id=step_id,
            issue_type=issue_type,
            severity="critical" if issue_type == "source_lineage_missing" else "high",
            error_signature=signature.value,
            symptom=symptom,
            source_refs=refs,
            payload_ref=payload.payload_id,
            detector_evidence=detector_evidence or [],
            metadata={"source_format": source_format},
        )


def _dedupe_issues(issues: list[ReaderIssue]) -> list[ReaderIssue]:
    seen: set[str] = set()
    result: list[ReaderIssue] = []
    for issue in issues:
        if issue.error_signature not in seen:
            seen.add(issue.error_signature)
            result.append(issue)
    return result


__all__ = ["ReaderRepairIssueDetector"]
