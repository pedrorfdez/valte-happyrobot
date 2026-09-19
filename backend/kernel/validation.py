"""Validates objects against the JSON Schemas in ../../schemas (the single
source of truth). Raises HTTPException 422 with all messages."""

import json
from pathlib import Path

import jsonschema
from fastapi import HTTPException

SCHEMAS_DIR = Path(__file__).resolve().parents[2] / "schemas"
_validators: dict[str, jsonschema.Draft7Validator] = {}

for p in SCHEMAS_DIR.glob("*.schema.json"):
    name = p.stem.removesuffix(".schema")
    _validators[name] = jsonschema.Draft7Validator(json.loads(p.read_text()))


def validate(obj: dict, schema: str):
    errs = [e.message for e in _validators[schema].iter_errors(obj)]
    if errs:
        raise HTTPException(422, {"schema": schema, "errors": errs[:10]})
