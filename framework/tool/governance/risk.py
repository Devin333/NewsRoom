from __future__ import annotations

from enum import Enum

from framework.tool.models.definition import ToolDefinition
from framework.tool.models.policy import is_default_dangerous_tool_name


class ToolRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolRiskClassifier:
    def classify(self, definition: ToolDefinition) -> ToolRiskLevel:
        if definition.is_dangerous or is_default_dangerous_tool_name(definition.name):
            return ToolRiskLevel.CRITICAL
        if definition.side_effect_value in {"publishing", "writes_external_state", "external_write", "network_write"}:
            return ToolRiskLevel.HIGH
        if definition.requires_approval or definition.side_effect_value not in {"", "none", "read_only"}:
            return ToolRiskLevel.MEDIUM
        if definition.required_secret_names:
            return ToolRiskLevel.MEDIUM
        return ToolRiskLevel.LOW
