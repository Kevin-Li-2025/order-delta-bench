from __future__ import annotations

import copy
import json

from src.orderbench.contracts import MENU_FOR_PROMPT

from .contracts import (
    JSON_PATCH_SCHEMA,
    PATCH_SCHEMA,
    REWRITE_SCHEMA,
    REWRITE_WITH_IDS_SCHEMA,
)
from .evaluate import strip_line_ids
from .state import order_to_state

SYSTEM_PROMPT = """You update a restaurant cart for a transactional ordering API.
Return only one JSON object and no markdown.
Use exact sku and modifier IDs from the menu.
Do not invent unavailable items or modifiers.
If an edit refers to a cart line that does not exist, set status to "needs_clarification".
If an edit would create or preserve an executable allergen conflict, set status to "rejected_safety".
If an edit conflicts with a dietary constraint, set status to "needs_clarification".
When status is not "accepted", do not execute the requested cart edit.
"""


def _legacy_rewrite_current_order(case: dict) -> dict:
    order = strip_line_ids(case["current_order"])
    rows = []
    for idx, row in enumerate(order["items"], start=1):
        with_position = copy.deepcopy(row)
        with_position["position"] = idx
        rows.append(with_position)
    return {"items": rows, "constraints": order["constraints"]}


def _identity_current_state(case: dict) -> dict:
    return order_to_state(case["current_order"], int(case.get("state_version", 1)))


def _edit_history(case: dict) -> list[str]:
    history = case.get("edit_history") or []
    return [str(step) for step in history]


def build_user_prompt(case: dict, mode: str) -> str:
    edit_history = _edit_history(case)
    if mode == "rewrite":
        payload = {
            "task": "Apply the customer edit to the current cart and return the complete updated_order. Do not include line_id or position fields in updated_order.",
            "interface": "legacy_id_free_full_order_rewrite",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_order": _legacy_rewrite_current_order(case),
            "menu": MENU_FOR_PROMPT,
            "schema": REWRITE_SCHEMA,
            "rules": [
                "Use edit_history only as context; current_order is the authoritative state to update.",
                "The current_order item position is for reference only; do not output it.",
                "Return the full final order, including unchanged items.",
                "Use null for clarification_question when status is accepted.",
                "If status is not accepted, keep the cart items unchanged and explain the reason.",
                "For no cheese on pizza, remove mozzarella. For no cheese on burger, remove cheese.",
                "For putting a removed modifier back, remove it from the remove list rather than adding it.",
            ],
        }
    elif mode == "rewrite_with_ids":
        payload = {
            "task": "Apply the customer edit and return the complete identity-bearing updated_order.",
            "interface": "full_order_rewrite_with_stable_ids",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_state": _identity_current_state(case),
            "menu": MENU_FOR_PROMPT,
            "schema": REWRITE_WITH_IDS_SCHEMA,
            "rules": [
                "Use edit_history only as context; current_state is authoritative.",
                "Preserve every existing line_id on the same logical object.",
                "Use N1, then N2, for newly created lines; never recycle a removed line_id.",
                "Return the full final order, including unchanged lines and constraints.",
                "If status is not accepted, apply only constraint writes implied by the customer statement; do not execute the blocked cart edit.",
            ],
        }
    elif mode == "line_patch":
        payload = {
            "task": "Apply the customer edit with minimal typed operations over stable line_id values.",
            "interface": "tagged_line_id_patch",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_state": _identity_current_state(case),
            "menu": MENU_FOR_PROMPT,
            "schema": PATCH_SCHEMA,
            "operation_rules": [
                "Use edit_history only as context; current_state is authoritative.",
                "Set base_version to current_state.version.",
                "Use remove_line with a line_id to delete one existing line.",
                "Use update_line with a line_id and a changes object containing only final field values that change.",
                "Use add_item without a line_id; the server assigns the next N identifier.",
                "Use set_constraints when allergens or dietary constraints change.",
                "If status is not accepted, operations may contain only authorized constraint writes, if any.",
                "Do not issue two operations that write the same line or field.",
            ],
        }
    elif mode == "json_patch":
        payload = {
            "task": "Apply the customer edit as an RFC 6902-style JSON Patch over the identity-bearing state.",
            "interface": "json_patch_with_version_test",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_state": _identity_current_state(case),
            "menu": MENU_FOR_PROMPT,
            "schema": JSON_PATCH_SCHEMA,
            "operation_rules": [
                "Use edit_history only as context; current_state is authoritative.",
                "The first operation must be test /version with the exact current version.",
                "Address lines as /lines/<line_id> and fields as /lines/<line_id>/<field>.",
                "Use N1, then N2, as the key for newly added lines; added line values exclude line_id.",
                "Use add, remove, replace, and test only. All operations are applied atomically.",
                "If status is not accepted, patch may contain only the version test plus authorized constraint writes, if any.",
            ],
        }
    else:
        raise ValueError(f"unknown mode: {mode}")
    return json.dumps(payload, sort_keys=True)
