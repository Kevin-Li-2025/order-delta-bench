from __future__ import annotations

ORDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["accepted", "needs_clarification", "rejected_safety"],
        },
        "items": {
            "type": "array",
            "items": {
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
                "required": [
                    "sku",
                    "quantity",
                    "size",
                    "add",
                    "remove",
                    "special_instructions",
                ],
            },
        },
        "constraints": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "allergens": {"type": "array", "items": {"type": "string"}},
                "dietary": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["allergens", "dietary"],
        },
        "clarification_question": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "status",
        "items",
        "constraints",
        "clarification_question",
        "reasons",
    ],
}

RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "order_contract",
        "strict": True,
        "schema": ORDER_SCHEMA,
    },
}

STATUS_VALUES = {"accepted", "needs_clarification", "rejected_safety"}

MENU = {
    "classic_burger": {
        "name": "Classic Burger",
        "kind": "main",
        "sizes": ["single", "double"],
        "default_size": "single",
        "allergens": ["gluten", "dairy"],
        "tags": [],
        "default_modifiers": [
            "bun",
            "beef_patty",
            "cheese",
            "lettuce",
            "tomato",
            "onion",
            "house_sauce",
        ],
        "removable": ["cheese", "lettuce", "tomato", "onion", "house_sauce", "bun"],
        "addable": ["bacon", "avocado", "extra_cheese", "fried_egg", "jalapeno", "gluten_free_bun"],
    },
    "vegan_bowl": {
        "name": "Vegan Bowl",
        "kind": "main",
        "sizes": ["regular", "large"],
        "default_size": "regular",
        "allergens": ["soy", "sesame"],
        "tags": ["vegan"],
        "default_modifiers": ["rice", "tofu", "broccoli", "carrot", "sesame_dressing"],
        "removable": ["tofu", "broccoli", "carrot", "sesame_dressing"],
        "addable": ["avocado", "extra_tofu", "chili_crisp"],
    },
    "chicken_wrap": {
        "name": "Chicken Wrap",
        "kind": "main",
        "sizes": ["regular"],
        "default_size": "regular",
        "allergens": ["gluten", "dairy"],
        "tags": [],
        "default_modifiers": ["tortilla", "grilled_chicken", "yogurt_sauce", "cucumber", "lettuce"],
        "removable": ["yogurt_sauce", "cucumber", "lettuce"],
        "addable": ["avocado", "extra_chicken", "jalapeno"],
    },
    "satay_noodles": {
        "name": "Satay Noodles",
        "kind": "main",
        "sizes": ["regular", "large"],
        "default_size": "regular",
        "allergens": ["peanut", "gluten", "soy"],
        "tags": [],
        "default_modifiers": ["noodles", "satay_sauce", "spring_onion", "tofu"],
        "removable": ["spring_onion", "tofu"],
        "addable": ["extra_satay_sauce", "chili_crisp", "broccoli"],
    },
    "margherita_pizza": {
        "name": "Margherita Pizza",
        "kind": "main",
        "sizes": ["small", "large"],
        "default_size": "small",
        "allergens": ["gluten", "dairy"],
        "tags": ["vegetarian"],
        "default_modifiers": ["dough", "tomato_sauce", "mozzarella", "basil"],
        "removable": ["mozzarella", "basil"],
        "addable": ["mushroom", "jalapeno", "extra_cheese"],
    },
    "fries": {
        "name": "Fries",
        "kind": "side",
        "sizes": ["regular", "large"],
        "default_size": "regular",
        "allergens": [],
        "tags": ["vegan"],
        "default_modifiers": ["salt"],
        "removable": ["salt"],
        "addable": ["truffle_oil", "cheese_sauce"],
    },
    "cola": {
        "name": "Cola",
        "kind": "drink",
        "sizes": ["regular", "large"],
        "default_size": "regular",
        "allergens": [],
        "tags": ["vegan"],
        "default_modifiers": [],
        "removable": [],
        "addable": [],
    },
}

MENU_FOR_PROMPT = {
    sku: {
        key: value
        for key, value in item.items()
        if key in {
            "name",
            "sizes",
            "default_size",
            "allergens",
            "tags",
            "removable",
            "addable",
        }
    }
    for sku, item in MENU.items()
}

ALLERGEN_ALIASES = {
    "dairy": {"dairy", "milk", "cheese", "lactose"},
    "gluten": {"gluten", "wheat"},
    "peanut": {"peanut", "peanuts"},
    "soy": {"soy", "soya"},
    "sesame": {"sesame"},
}

