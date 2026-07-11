from __future__ import annotations

import json
import subprocess
from pathlib import Path

from jyotish_agent.api import app


ROOT = Path(__file__).resolve().parents[1]
KEYWORDS = {
    "type",
    "const",
    "enum",
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "minItems",
    "pattern",
}


def _field_shape(field: dict) -> dict:
    shaped = {key: field[key] for key in KEYWORDS if key in field}
    if isinstance(field.get("items"), dict) and "type" in field["items"]:
        shaped["items_type"] = field["items"]["type"]
    return shaped


def _object_shape(schema: dict) -> dict:
    return {
        "required": sorted(schema.get("required", [])),
        "additionalProperties": schema.get("additionalProperties"),
        "properties": {
            name: _field_shape(field)
            for name, field in sorted(schema["properties"].items())
        },
    }


def test_answer_contract_openapi_matches_typebox_schema():
    completed = subprocess.run(
        [
            "bun",
            "-e",
            'import {AnswerContractV2Schema as S} from "./.pi/extensions/jyotish.ts"; '
            "console.log(JSON.stringify(S))",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    typebox = json.loads(completed.stdout)
    components = app.openapi()["components"]["schemas"]
    openapi = components["AnswerContractV2"]

    assert _object_shape(openapi) == _object_shape(typebox)

    openapi_variants = {}
    for reference in openapi["properties"]["claims"]["items"]["oneOf"]:
        variant = components[reference["$ref"].rsplit("/", 1)[1]]
        discriminator = variant["properties"]["claim_type"]["const"]
        openapi_variants[discriminator] = _object_shape(variant)
    typebox_variants = {
        variant["properties"]["claim_type"]["const"]: _object_shape(variant)
        for variant in typebox["properties"]["claims"]["items"]["anyOf"]
    }
    assert openapi_variants == typebox_variants
