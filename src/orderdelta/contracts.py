from __future__ import annotations

STATUS_VALUES = {"accepted", "needs_clarification", "rejected_safety"}

CONSTRAINTS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "allergens": {"type": "array", "items": {"type": "string"}},
        "dietary": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["allergens", "dietary"],
}

ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "sku": {"type": "string"},
        "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
        "size": {"type": ["string", "null"]},
        "add": {"type": "array", "items": {"type": "string"}},
        "remove": {"type": "array", "items": {"type": "string"}},
        "special_instructions": {"type": "string"},
    },
    "required": ["sku", "quantity", "size", "add", "remove", "special_instructions"],
}

LINE_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "line_id": {"type": "string"},
        **ITEM_SCHEMA["properties"],
    },
    "required": ["line_id", *ITEM_SCHEMA["required"]],
}

ORDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {"type": "array", "items": ITEM_SCHEMA},
        "constraints": CONSTRAINTS_SCHEMA,
    },
    "required": ["items", "constraints"],
}

LINE_ORDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {"type": "array", "items": LINE_ITEM_SCHEMA},
        "constraints": CONSTRAINTS_SCHEMA,
    },
    "required": ["items", "constraints"],
}

REWRITE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["accepted", "needs_clarification", "rejected_safety"],
        },
        "updated_order": ORDER_SCHEMA,
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "updated_order", "clarification_question", "reasons"],
}

REWRITE_WITH_IDS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": sorted(STATUS_VALUES)},
        "updated_order": LINE_ORDER_SCHEMA,
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "updated_order", "clarification_question", "reasons"],
}

UPDATE_CHANGES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "minProperties": 1,
    "properties": {
        "quantity": {"type": "integer", "minimum": 1, "maximum": 20},
        "size": {"type": ["string", "null"]},
        "add": {"type": "array", "items": {"type": "string"}},
        "remove": {"type": "array", "items": {"type": "string"}},
        "special_instructions": {"type": "string"},
    },
}

PATCH_OPERATION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"const": "add_item"},
                "item": ITEM_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["op", "item", "reason"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"const": "remove_line"},
                "line_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["op", "line_id", "reason"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"const": "update_line"},
                "line_id": {"type": "string"},
                "changes": UPDATE_CHANGES_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["op", "line_id", "changes", "reason"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"const": "set_constraints"},
                "constraints": CONSTRAINTS_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["op", "constraints", "reason"],
        },
    ]
}

PATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["accepted", "needs_clarification", "rejected_safety"],
        },
        "base_version": {"type": "integer", "minimum": 1},
        "operations": {"type": "array", "items": PATCH_OPERATION_SCHEMA},
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "base_version", "operations", "clarification_question", "reasons"],
}

JSON_PATCH_OPERATION_SCHEMA = {
    "oneOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"enum": ["test", "add", "replace"]},
                "path": {"type": "string", "pattern": "^/"},
                "value": {},
            },
            "required": ["op", "path", "value"],
        },
        {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "op": {"const": "remove"},
                "path": {"type": "string", "pattern": "^/"},
            },
            "required": ["op", "path"],
        },
    ]
}

JSON_PATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {"type": "string", "enum": sorted(STATUS_VALUES)},
        "patch": {"type": "array", "items": JSON_PATCH_OPERATION_SCHEMA},
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "patch", "clarification_question", "reasons"],
}

RESPONSE_FORMATS = {
    "rewrite": {
        "type": "json_schema",
        "json_schema": {"name": "order_rewrite", "strict": True, "schema": REWRITE_SCHEMA},
    },
    "rewrite_with_ids": {
        "type": "json_schema",
        "json_schema": {
            "name": "order_rewrite_with_ids",
            "strict": True,
            "schema": REWRITE_WITH_IDS_SCHEMA,
        },
    },
    "line_patch": {
        "type": "json_schema",
        "json_schema": {"name": "order_delta", "strict": True, "schema": PATCH_SCHEMA},
    },
    "json_patch": {
        "type": "json_schema",
        "json_schema": {"name": "order_json_patch", "strict": True, "schema": JSON_PATCH_SCHEMA},
    },
}
