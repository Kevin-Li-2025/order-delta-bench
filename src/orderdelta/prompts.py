from __future__ import annotations

import copy
import json

from src.orderbench.contracts import MENU_FOR_PROMPT

from .contracts import PATCH_SCHEMA, REWRITE_SCHEMA
from .evaluate import strip_line_ids

SYSTEM_PROMPT = """You update a restaurant cart for a transactional ordering API.
Return only one JSON object and no markdown.
Use exact sku and modifier IDs from the menu.
Do not invent unavailable items or modifiers.
If an edit refers to a cart line that does not exist, set status to "needs_clarification".
If an edit would create or preserve an executable allergen conflict, set status to "rejected_safety".
If an edit conflicts with a dietary constraint, set status to "needs_clarification".
When status is not "accepted", do not execute the requested cart edit.
"""


def _rewrite_current_order(case: dict) -> dict:
    order = strip_line_ids(case["current_order"])
    rows = []
    for idx, row in enumerate(order["items"], start=1):
        with_position = copy.deepcopy(row)
        with_position["position"] = idx
        rows.append(with_position)
    return {"items": rows, "constraints": order["constraints"]}


def _patch_current_order(case: dict) -> dict:
    return copy.deepcopy(case["current_order"])


def _edit_history(case: dict) -> list[str]:
    history = case.get("edit_history") or []
    return [str(step) for step in history]


def build_user_prompt(case: dict, mode: str) -> str:
    edit_history = _edit_history(case)
    if mode == "rewrite":
        payload = {
            "task": "Apply the customer edit to the current cart and return the complete updated_order. Do not include line_id or position fields in updated_order.",
            "interface": "full_order_rewrite",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_order": _rewrite_current_order(case),
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
    elif mode == "line_patch":
        payload = {
            "task": "Apply the customer edit to the current cart by returning minimal operations over stable line_id values.",
            "interface": "line_id_patch",
            "customer_edit": case["utterance"],
            "edit_history": edit_history,
            "current_order": _patch_current_order(case),
            "menu": MENU_FOR_PROMPT,
            "schema": PATCH_SCHEMA,
            "operation_rules": [
                "Use edit_history only as context; current_order is the authoritative state to update.",
                "Use remove_line with a line_id to delete one existing line.",
                "Use update_line with a line_id to change quantity, size, add, remove, remove_add, or remove_remove.",
                "Use add_item for a new item; item must contain sku, quantity, size, add, remove, and special_instructions.",
                "Use set_constraints when allergens or dietary constraints change.",
                "For fields not changed by an operation, use null for quantity and size, empty lists for add/remove/remove_add/remove_remove, and null for item or constraints.",
                "If status is not accepted, operations must be empty.",
                "For putting a removed modifier back, use remove_remove. For removing a previously added modifier, use remove_add.",
            ],
        }
    else:
        raise ValueError(f"unknown mode: {mode}")
    return json.dumps(payload, sort_keys=True)
