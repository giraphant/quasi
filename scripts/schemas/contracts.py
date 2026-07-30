"""Deterministic projections of the canonical vault artifact schemas.

The Pydantic frontmatter model and BodySchema remain the only product-shape
sources.  Runtime producers receive the canonical projection below; audit and
typecheck keep consuming the same registry directly, including migration-only
aliases that are deliberately absent from producer contracts.
"""

from __future__ import annotations

from typing import Any

from .registry import schema_for_type


def artifact_contract_for_type(type_name: str) -> dict[str, Any]:
    """Return the canonical producer/search projection for one artifact type."""

    schemas = schema_for_type(type_name)
    if schemas is None:
        raise KeyError(f"unknown canonical artifact type: {type_name}")
    frontmatter_model, body_schema = schemas
    if not body_schema.artifact_schema_version:
        raise ValueError(f"{type_name} has no runtime artifact schema version")

    frontmatter_schema = frontmatter_model.model_json_schema(mode="validation")
    properties = frontmatter_schema.get("properties", {})
    required = frontmatter_schema.get("required", [])
    identity_properties = {
        name: properties[name]
        for name in body_schema.identity_fields
        if name in properties
    }

    sections: list[dict[str, Any]] = []
    for section in body_schema.sections:
        item: dict[str, Any] = {
            "h2": section.h2,
            "kind": section.kind,
            "required": section.required,
            "description": section.description,
        }
        if section.child_kind is not None:
            item["child_kind"] = section.child_kind
        if section.columns:
            item["columns"] = section.columns
        if section.recommended_items is not None:
            item["recommended_items"] = {
                "min": section.recommended_items[0],
                "max": section.recommended_items[1],
            }
        if section.condition:
            item["condition"] = section.condition
        sections.append(item)

    return {
        "schema_version": body_schema.artifact_schema_version,
        "artifact_type": type_name,
        "path_pattern": body_schema.path_pattern,
        "frontmatter": {
            "field_order": list(frontmatter_model.model_fields),
            "json_schema": frontmatter_schema,
        },
        "identity": {
            "fields": body_schema.identity_fields,
            "required": [
                name for name in required if name in body_schema.identity_fields
            ],
            "properties": identity_properties,
        },
        "document": {
            "h1": body_schema.h1,
            "metadata_lines": body_schema.metadata_lines,
            "section_order": [section.h2 for section in body_schema.sections],
            "additional_h2": False,
            "sections": sections,
        },
    }
