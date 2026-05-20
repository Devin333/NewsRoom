from __future__ import annotations

from typing import Any


class PydanticToolSchemaAdapter:
    def schema_from_model(self, model: type[Any]) -> dict[str, Any]:
        if hasattr(model, "model_json_schema"):
            return dict(model.model_json_schema())
        if hasattr(model, "schema"):
            return dict(model.schema())
        raise TypeError("model does not provide a pydantic JSON schema method")

    def validate_with_model(self, model: type[Any], arguments: dict[str, Any]) -> Any:
        if hasattr(model, "model_validate"):
            return model.model_validate(arguments)
        return model(**arguments)
