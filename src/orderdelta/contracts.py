from __future__ import annotations

from src.orderbench.contracts import MENU, MENU_FOR_PROMPT

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

PATCH_OPERATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "op": {
            "type": "string",
            "enum": ["add_item", "remove_line", "update_line", "set_constraints", "noop"],
        },
        "line_id": {"type": ["string", "null"]},
        "item": {"type": ["object", "null"], **{k: v for k, v in ITEM_SCHEMA.items() if k != "type"}},
        "quantity": {"type": ["integer", "null"], "minimum": 1, "maximum": 20},
        "size": {"type": ["string", "null"]},
        "add": {"type": "array", "items": {"type": "string"}},
        "remove": {"type": "array", "items": {"type": "string"}},
        "remove_add": {"type": "array", "items": {"type": "string"}},
        "remove_remove": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": ["object", "null"], **{k: v for k, v in CONSTRAINTS_SCHEMA.items() if k != "type"}},
        "reason": {"type": "string"},
    },
    "required": [
        "op",
        "line_id",
        "item",
        "quantity",
        "size",
        "add",
        "remove",
        "remove_add",
        "remove_remove",
        "constraints",
        "reason",
    ],
}

PATCH_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["accepted", "needs_clarification", "rejected_safety"],
        },
        "operations": {"type": "array", "items": PATCH_OPERATION_SCHEMA},
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "operations", "clarification_question", "reasons"],
}

RESPONSE_FORMATS = {
    "rewrite": {
        "type": "json_schema",
        "json_schema": {"name": "order_rewrite", "strict": True, "schema": REWRITE_SCHEMA},
    },
    "line_patch": {
        "type": "json_schema",
        "json_schema": {"name": "order_delta", "strict": True, "schema": PATCH_SCHEMA},
    },
}

