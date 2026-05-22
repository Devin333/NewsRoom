"""JSON Schema validation for skill input and output."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import BaseModel, Field

from framework.skills.core.result import SkillErrorDetail
from framework.skills.package.loader import SkillPackage


class SchemaValidationIssue(BaseModel):
    code: str
    message: str
    path: str | None = None
    schema_path: str | None = None


class SchemaValidationResult(BaseModel):
    ok: bool
    issues: list[SchemaValidationIssue] = Field(default_factory=list)

    def errors_as_skill_details(self) -> list[SkillErrorDetail]:
        return [
            SkillErrorDetail(
                code=issue.code,
                message=issue.message,
                path=issue.path,
                detail={"schema_path": issue.schema_path} if issue.schema_path else {},
            )
            for issue in self.issues
        ]


class SkillSchemaValidator:
    def load_schema(self, schema_path: str | Path) -> dict:
        """Load and parse JSON schema."""
        path = Path(schema_path)
        if not path.is_file():
            raise FileNotFoundError(str(path))
        with path.open("r", encoding="utf-8") as handle:
            schema = json.load(handle)
        if not isinstance(schema, dict):
            raise ValueError("schema root must be a JSON object")
        return schema

    def validate_data(self, data: dict, schema_path: str | Path) -> SchemaValidationResult:
        """Validate arbitrary data."""
        try:
            schema = self.load_schema(schema_path)
            validator_cls = validator_for(schema)
            validator_cls.check_schema(schema)
        except FileNotFoundError:
            return SchemaValidationResult(
                ok=False,
                issues=[
                    SchemaValidationIssue(
                        code="schema_file_missing",
                        message=f"schema file not found: {schema_path}",
                        path=str(schema_path),
                    )
                ],
            )
        except (json.JSONDecodeError, ValueError, SchemaError) as exc:
            return SchemaValidationResult(
                ok=False,
                issues=[
                    SchemaValidationIssue(
                        code="schema_json_invalid",
                        message=str(exc),
                        path=str(schema_path),
                    )
                ],
            )

        validator = validator_cls(schema)
        issues = [
            SchemaValidationIssue(
                code="schema_validation_failed",
                message=error.message,
                path=_json_path(error.absolute_path),
                schema_path=_json_path(error.absolute_schema_path),
            )
            for error in sorted(
                validator.iter_errors(data),
                key=lambda item: (_json_path(item.absolute_path) or "", item.message),
            )
        ]
        return SchemaValidationResult(ok=not issues, issues=issues)

    def validate_input(self, package: SkillPackage, input_data: dict) -> SchemaValidationResult:
        """Validate package input data. No schema means ok=True."""
        if not package.metadata.input_schema:
            return SchemaValidationResult(ok=True)
        return self.validate_data(input_data, package.resolve_relative_path(package.metadata.input_schema))

    def validate_output(self, package: SkillPackage, output_data: dict) -> SchemaValidationResult:
        """Validate package output data. No schema means ok=True."""
        if not package.metadata.output_schema:
            return SchemaValidationResult(ok=True)
        return self.validate_data(output_data, package.resolve_relative_path(package.metadata.output_schema))


def _json_path(path: Iterable[object]) -> str | None:
    parts = list(path)
    if not parts:
        return None
    return ".".join(str(part) for part in parts)
