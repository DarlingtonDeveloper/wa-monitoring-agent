"""Schema validation for the WA Monitoring Agent pipeline."""

import json
from pathlib import Path

import jsonschema

_SCHEMA_DIR = Path(__file__).parent

def _load_schema(name: str) -> dict:
    with open(_SCHEMA_DIR / name) as f:
        return json.load(f)

def validate_items(data: list) -> list[str]:
    """Validate scored items against items.schema.json. Returns list of errors (empty = valid)."""
    schema = _load_schema("items.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(data)]

def validate_analysis(data: dict) -> list[str]:
    """Validate analysis output against analysis.schema.json. Returns list of errors (empty = valid)."""
    schema = _load_schema("analysis.schema.json")
    validator = jsonschema.Draft202012Validator(schema)
    return [e.message for e in validator.iter_errors(data)]
