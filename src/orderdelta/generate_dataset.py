from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from src.orderbench.contracts import MENU


def item(line_id: str, sku: str, quantity: int = 1, size: str | None = None, add=None, remove=None) -> dict:
    menu_item = MENU[sku]
    return {
        "line_id": line_id,
        "sku": sku,
        "quantity": quantity,
        "size": size if size is not None else menu_item["default_size"],
        "add": sorted(add or []),
        "remove": sorted(remove or []),
        "special_instructions": "",
    }


def order(items: list[dict], allergens=None, dietary=None) -> dict:
    return {
        "items": copy.deepcopy(items),
        "constraints": {
            "allergens": sorted(allergens or []),
            "dietary": sorted(dietary or []),
        },
    }


def history(*steps: str) -> list[str]:
    return [step.strip() for step in steps if step.strip()]


def case(
    case_id: str,
    category: str,
    utterance: str,
    current_order: dict,
    expected_status: str,
    expected_order: dict,
    rationale: str,
    target_line_ids=None,
    unchanged_line_ids=None,
    reasons=None,
    edit_history=None,
) -> dict:
    return {
        "id": case_id,
        "category": category,
        "utterance": utterance.strip(),
        "edit_history": list(edit_history or []),
        "current_order": current_order,
        "expected_status": expected_status,
        "expected_order": expected_order,
        "target_line_ids": sorted(target_line_ids or []),
        "unchanged_line_ids": sorted(unchanged_line_ids or []),
        "expected_reasons": sorted(reasons or []),
        "rationale": rationale,
    }


PREFIXES = [
    "",
    "Actually, ",
    "Can you update it: ",
    "One change: ",
    "Before checkout, ",
    "Please revise the cart: ",
    "Sorry, ",
    "Make this edit: ",
    "Could you change it so that ",
    "For the current order, ",
    "On this order, ",
    "Small correction: ",
    "I changed my mind: ",
    "For that cart, ",
    "Just to be clear, ",
    "Could you adjust it: ",
    "When you review the cart, ",
    "Instead of leaving it as-is, ",
    "Before you send it through, ",
    "I need one cart edit: ",
]

SUFFIXES = [
    "",
    " Thanks.",
    " That is all.",
    " Please.",
    " Keep the rest the same.",
    " No other changes.",
    " Then I am ready.",
    " For the same customer.",
    " Do not change anything else.",
    " Today.",
    " Leave the other lines alone.",
    " Nothing else should move.",
    " Same cart.",
    " That is the only update.",
    " Please keep every other item as ordered.",
    " Do not duplicate anything.",
]


def vary(utterance: str, i: int) -> str:
    prefix = PREFIXES[i % len(PREFIXES)]
    suffix = SUFFIXES[(i // len(PREFIXES)) % len(SUFFIXES)]
    if prefix.endswith("that ") and utterance[:1].isupper():
        utterance = utterance[:1].lower() + utterance[1:]
    return f"{prefix}{utterance}{suffix}"


def build_cases(cases_per_category: int) -> list[dict]:
    builders = [
        add_item,
        remove_scoped_duplicate,
        quantity_increase,
        quantity_decrease,
        modifier_add_scoped,
        modifier_reversal,
        size_change_scoped,
        replace_item,
        constraint_add_safe,
        constraint_new_conflict,
        unavailable_add,
        stale_reference,
    ]
    rows: list[dict] = []
    for builder in builders:
        rows.extend(builder(cases_per_category))
    return rows


def add_item(n: int) -> list[dict]:
    templates = [
        (
            [item("L1", "classic_burger")],
            "Add a large cola.",
            [item("L1", "classic_burger"), item("N1", "cola", size="large")],
            history("Started with a classic burger.", "Customer confirmed no side yet."),
        ),
        (
            [item("L1", "vegan_bowl", size="large", add=["avocado"])],
            "Add regular fries.",
            [item("L1", "vegan_bowl", size="large", add=["avocado"]), item("N1", "fries")],
            history("Customer upgraded the vegan bowl to large.", "Avocado was already added."),
        ),
        (
            [item("L1", "fries")],
            "Add a double classic burger with jalapeno.",
            [item("L1", "fries"), item("N1", "classic_burger", size="double", add=["jalapeno"])],
            history("Customer first asked for fries only."),
        ),
        (
            [item("L1", "cola", size="large"), item("L2", "fries", remove=["salt"])],
            "Add a small margherita pizza with mushroom.",
            [item("L1", "cola", size="large"), item("L2", "fries", remove=["salt"]), item("N1", "margherita_pizza", size="small", add=["mushroom"])],
            history("The drink is already large.", "The fries are unsalted."),
        ),
        (
            [item("L1", "satay_noodles", add=["broccoli"])],
            "Add a regular cola.",
            [item("L1", "satay_noodles", add=["broccoli"]), item("N1", "cola")],
            history("Broccoli was added to the noodles in the previous step."),
        ),
        (
            [item("L1", "chicken_wrap", remove=["cucumber"])],
            "Put in large fries with truffle oil too.",
            [item("L1", "chicken_wrap", remove=["cucumber"]), item("N1", "fries", size="large", add=["truffle_oil"])],
            history("Customer removed cucumber from the wrap."),
        ),
        (
            [item("L1", "margherita_pizza", add=["jalapeno"]), item("L2", "cola")],
            "Add one vegan bowl with extra tofu.",
            [item("L1", "margherita_pizza", add=["jalapeno"]), item("L2", "cola"), item("N1", "vegan_bowl", add=["extra_tofu"])],
            history("Pizza already has jalapeno.", "Cola should stay on the cart."),
        ),
        (
            [item("L1", "classic_burger", add=["bacon"]), item("L2", "cola")],
            "Add a large order of satay noodles.",
            [item("L1", "classic_burger", add=["bacon"]), item("L2", "cola"), item("N1", "satay_noodles", size="large")],
            history("Bacon was added to the burger.", "Drink was confirmed."),
        ),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, steps = templates[i % len(templates)]
        rows.append(case(
            f"add_item_{i:03d}",
            "add_item",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "A valid new item should be appended without changing existing lines.",
            unchanged_line_ids=[row["line_id"] for row in current],
            edit_history=steps,
        ))
    return rows


def remove_scoped_duplicate(n: int) -> list[dict]:
    templates = [
        (
            [item("L1", "classic_burger", remove=["onion"]), item("L2", "classic_burger", size="double"), item("L3", "fries")],
            "Remove the double burger.",
            [item("L1", "classic_burger", remove=["onion"]), item("L3", "fries")],
            ["L2"],
            ["L1", "L3"],
            history("One burger was customized without onion.", "A second burger was later upgraded to double."),
        ),
        (
            [item("L1", "margherita_pizza", size="small"), item("L2", "margherita_pizza", size="large", add=["mushroom"])],
            "Take out the mushroom pizza.",
            [item("L1", "margherita_pizza", size="small")],
            ["L2"],
            ["L1"],
            history("The first pizza stayed plain.", "Mushroom was added only to the large pizza."),
        ),
        (
            [item("L1", "vegan_bowl", add=["avocado"]), item("L2", "vegan_bowl"), item("L3", "cola")],
            "Remove the plain vegan bowl.",
            [item("L1", "vegan_bowl", add=["avocado"]), item("L3", "cola")],
            ["L2"],
            ["L1", "L3"],
            history("One bowl got avocado.", "The other vegan bowl remained plain."),
        ),
        (
            [item("L1", "fries", size="large", add=["truffle_oil"]), item("L2", "fries"), item("L3", "classic_burger")],
            "Delete the regular fries.",
            [item("L1", "fries", size="large", add=["truffle_oil"]), item("L3", "classic_burger")],
            ["L2"],
            ["L1", "L3"],
            history("Large fries have truffle oil.", "Regular fries were a separate side."),
        ),
        (
            [item("L1", "cola", size="large"), item("L2", "cola"), item("L3", "satay_noodles")],
            "Remove the large cola.",
            [item("L2", "cola"), item("L3", "satay_noodles")],
            ["L1"],
            ["L2", "L3"],
            history("Customer added two colas in different sizes."),
        ),
        (
            [item("L1", "classic_burger", add=["bacon"]), item("L2", "classic_burger", remove=["cheese"]), item("L3", "cola")],
            "Take off the burger with bacon.",
            [item("L2", "classic_burger", remove=["cheese"]), item("L3", "cola")],
            ["L1"],
            ["L2", "L3"],
            history("One burger has bacon.", "The other burger is no cheese."),
        ),
        (
            [item("L1", "chicken_wrap", add=["jalapeno"]), item("L2", "chicken_wrap", remove=["cucumber"]), item("L3", "fries")],
            "Remove the wrap without cucumber.",
            [item("L1", "chicken_wrap", add=["jalapeno"]), item("L3", "fries")],
            ["L2"],
            ["L1", "L3"],
            history("Jalapeno applies to the first wrap.", "The second wrap has cucumber removed."),
        ),
        (
            [item("L1", "satay_noodles", add=["chili_crisp"]), item("L2", "satay_noodles", remove=["tofu"]), item("L3", "cola")],
            "Remove the noodles with no tofu.",
            [item("L1", "satay_noodles", add=["chili_crisp"]), item("L3", "cola")],
            ["L2"],
            ["L1", "L3"],
            history("One satay noodle line has chili crisp.", "The other satay noodle line has tofu removed."),
        ),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged, steps = templates[i % len(templates)]
        rows.append(case(
            f"remove_scoped_duplicate_{i:03d}",
            "remove_scoped_duplicate",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "The edit identifies one of several similar lines; the other lines must survive unchanged.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=steps,
        ))
    return rows


def quantity_increase(n: int) -> list[dict]:
    templates = [
        ([item("L1", "cola", quantity=2), item("L2", "fries")], "Make the colas four total.", [item("L1", "cola", quantity=4), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "fries"), item("L2", "classic_burger")], "I need three fries instead.", [item("L1", "fries", quantity=3), item("L2", "classic_burger")], ["L1"], ["L2"]),
        ([item("L1", "vegan_bowl", quantity=2), item("L2", "cola")], "Change the vegan bowls to five.", [item("L1", "vegan_bowl", quantity=5), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger"), item("L2", "cola")], "Make the cola three total.", [item("L1", "classic_burger"), item("L2", "cola", quantity=3)], ["L2"], ["L1"]),
        ([item("L1", "fries"), item("L2", "margherita_pizza", quantity=2)], "Make the pizzas four.", [item("L1", "fries"), item("L2", "margherita_pizza", quantity=4)], ["L2"], ["L1"]),
        ([item("L1", "cola"), item("L2", "satay_noodles", quantity=2)], "I need four satay noodles.", [item("L1", "cola"), item("L2", "satay_noodles", quantity=4)], ["L2"], ["L1"]),
        ([item("L1", "chicken_wrap"), item("L2", "classic_burger")], "Make the burgers two total.", [item("L1", "chicken_wrap"), item("L2", "classic_burger", quantity=2)], ["L2"], ["L1"]),
        ([item("L1", "cola"), item("L2", "fries", size="large", quantity=2)], "Set the large fries to six.", [item("L1", "cola"), item("L2", "fries", size="large", quantity=6)], ["L2"], ["L1"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"quantity_increase_{i:03d}",
            "quantity_increase",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "Quantity edits should set the requested final quantity, not add an extra line.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("Customer already has a multi-line cart.", "This is a quantity-only revision."),
        ))
    return rows


def quantity_decrease(n: int) -> list[dict]:
    templates = [
        ([item("L1", "fries", quantity=2), item("L2", "cola")], "Remove one fries.", [item("L1", "fries", quantity=1), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger", quantity=3), item("L2", "fries")], "Make that two classic burgers.", [item("L1", "classic_burger", quantity=2), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "cola", quantity=4), item("L2", "margherita_pizza")], "Only two colas now.", [item("L1", "cola", quantity=2), item("L2", "margherita_pizza")], ["L1"], ["L2"]),
        ([item("L1", "cola"), item("L2", "vegan_bowl", quantity=5)], "Make the vegan bowls three.", [item("L1", "cola"), item("L2", "vegan_bowl", quantity=3)], ["L2"], ["L1"]),
        ([item("L1", "fries"), item("L2", "satay_noodles", quantity=4)], "Only one satay noodles now.", [item("L1", "fries"), item("L2", "satay_noodles", quantity=1)], ["L2"], ["L1"]),
        ([item("L1", "chicken_wrap", quantity=3), item("L2", "cola")], "Drop the wraps to two.", [item("L1", "chicken_wrap", quantity=2), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "margherita_pizza", quantity=3), item("L2", "fries")], "Make it just one pizza.", [item("L1", "margherita_pizza", quantity=1), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger"), item("L2", "cola", quantity=5)], "Reduce the colas to four.", [item("L1", "classic_burger"), item("L2", "cola", quantity=4)], ["L2"], ["L1"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"quantity_decrease_{i:03d}",
            "quantity_decrease",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "A decrement should update quantity without deleting unrelated cart lines.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("Customer is revising quantities before checkout."),
        ))
    return rows


def modifier_add_scoped(n: int) -> list[dict]:
    templates = [
        ([item("L1", "classic_burger"), item("L2", "chicken_wrap")], "Add jalapeno to the wrap only.", [item("L1", "classic_burger"), item("L2", "chicken_wrap", add=["jalapeno"])], ["L2"], ["L1"]),
        ([item("L1", "vegan_bowl"), item("L2", "fries")], "Put avocado on the bowl, not the fries.", [item("L1", "vegan_bowl", add=["avocado"]), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger"), item("L2", "margherita_pizza")], "Add mushroom to the pizza only.", [item("L1", "classic_burger"), item("L2", "margherita_pizza", add=["mushroom"])], ["L2"], ["L1"]),
        ([item("L1", "fries"), item("L2", "classic_burger")], "Add bacon to the burger, not the fries.", [item("L1", "fries"), item("L2", "classic_burger", add=["bacon"])], ["L2"], ["L1"]),
        ([item("L1", "satay_noodles"), item("L2", "vegan_bowl")], "Add chili crisp to the satay noodles only.", [item("L1", "satay_noodles", add=["chili_crisp"]), item("L2", "vegan_bowl")], ["L1"], ["L2"]),
        ([item("L1", "chicken_wrap"), item("L2", "classic_burger", add=["bacon"])], "Add avocado to the wrap.", [item("L1", "chicken_wrap", add=["avocado"]), item("L2", "classic_burger", add=["bacon"])], ["L1"], ["L2"]),
        ([item("L1", "margherita_pizza"), item("L2", "fries")], "Put truffle oil on the fries only.", [item("L1", "margherita_pizza"), item("L2", "fries", add=["truffle_oil"])], ["L2"], ["L1"]),
        ([item("L1", "vegan_bowl"), item("L2", "satay_noodles")], "Add extra tofu to the vegan bowl, not the noodles.", [item("L1", "vegan_bowl", add=["extra_tofu"]), item("L2", "satay_noodles")], ["L1"], ["L2"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"modifier_add_scoped_{i:03d}",
            "modifier_add_scoped",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "The new modifier applies only to the referenced line.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("The cart already contains multiple items.", "The next edit is scoped to one item."),
        ))
    return rows


def modifier_reversal(n: int) -> list[dict]:
    templates = [
        ([item("L1", "classic_burger", remove=["cheese", "onion"]), item("L2", "fries")], "Put the cheese back but keep no onion.", [item("L1", "classic_burger", remove=["onion"]), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "vegan_bowl", add=["avocado"], remove=["sesame_dressing"])], "Actually keep the sesame dressing but still add avocado.", [item("L1", "vegan_bowl", add=["avocado"])], ["L1"], []),
        ([item("L1", "chicken_wrap", add=["jalapeno"], remove=["cucumber"])], "Remove the jalapeno but keep it without cucumber.", [item("L1", "chicken_wrap", remove=["cucumber"])], ["L1"], []),
        ([item("L1", "margherita_pizza", add=["mushroom"], remove=["basil"]), item("L2", "cola")], "Put basil back on the pizza, but keep the mushroom.", [item("L1", "margherita_pizza", add=["mushroom"]), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "fries", add=["truffle_oil"], remove=["salt"]), item("L2", "classic_burger")], "Take off the truffle oil but keep the fries unsalted.", [item("L1", "fries", remove=["salt"]), item("L2", "classic_burger")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger", add=["bacon"], remove=["tomato"]), item("L2", "cola")], "Remove the bacon but keep no tomato.", [item("L1", "classic_burger", remove=["tomato"]), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "satay_noodles", add=["chili_crisp"], remove=["tofu"])], "Put tofu back but keep the chili crisp.", [item("L1", "satay_noodles", add=["chili_crisp"])], ["L1"], []),
        ([item("L1", "vegan_bowl", add=["extra_tofu"], remove=["carrot"]), item("L2", "fries")], "Cancel the extra tofu but keep no carrot.", [item("L1", "vegan_bowl", remove=["carrot"]), item("L2", "fries")], ["L1"], ["L2"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"modifier_reversal_{i:03d}",
            "modifier_reversal",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "The model must reverse only one previous modifier decision while preserving the other.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("Earlier turns created both added and removed modifiers.", "Only one previous modifier decision should be reversed now."),
        ))
    return rows


def size_change_scoped(n: int) -> list[dict]:
    templates = [
        ([item("L1", "margherita_pizza", size="small", add=["mushroom"]), item("L2", "margherita_pizza", size="large")], "Make the mushroom pizza large.", [item("L1", "margherita_pizza", size="large", add=["mushroom"]), item("L2", "margherita_pizza", size="large")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger"), item("L2", "classic_burger", size="double", add=["bacon"])], "Make the plain burger double too.", [item("L1", "classic_burger", size="double"), item("L2", "classic_burger", size="double", add=["bacon"])], ["L1"], ["L2"]),
        ([item("L1", "vegan_bowl", size="regular"), item("L2", "vegan_bowl", size="large", add=["avocado"])], "The regular bowl should be large.", [item("L1", "vegan_bowl", size="large"), item("L2", "vegan_bowl", size="large", add=["avocado"])], ["L1"], ["L2"]),
        ([item("L1", "fries"), item("L2", "fries", size="large", add=["truffle_oil"])], "Make the plain fries large.", [item("L1", "fries", size="large"), item("L2", "fries", size="large", add=["truffle_oil"])], ["L1"], ["L2"]),
        ([item("L1", "cola"), item("L2", "cola", size="large")], "Make the regular cola large.", [item("L1", "cola", size="large"), item("L2", "cola", size="large")], ["L1"], ["L2"]),
        ([item("L1", "satay_noodles", size="regular", add=["broccoli"]), item("L2", "satay_noodles", size="large")], "Make the broccoli noodles large.", [item("L1", "satay_noodles", size="large", add=["broccoli"]), item("L2", "satay_noodles", size="large")], ["L1"], ["L2"]),
        ([item("L1", "margherita_pizza", size="large", add=["jalapeno"]), item("L2", "margherita_pizza", size="small")], "Make the plain pizza large too.", [item("L1", "margherita_pizza", size="large", add=["jalapeno"]), item("L2", "margherita_pizza", size="large")], ["L2"], ["L1"]),
        ([item("L1", "vegan_bowl", size="large"), item("L2", "vegan_bowl", size="regular", add=["extra_tofu"])], "Make the extra tofu bowl large.", [item("L1", "vegan_bowl", size="large"), item("L2", "vegan_bowl", size="large", add=["extra_tofu"])], ["L2"], ["L1"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"size_change_scoped_{i:03d}",
            "size_change_scoped",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "A size edit must find the right duplicate line and leave the other duplicate unchanged.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("The cart has two similar lines.", "The size edit is intended for only one line."),
        ))
    return rows


def replace_item(n: int) -> list[dict]:
    templates = [
        ([item("L1", "chicken_wrap"), item("L2", "cola")], "Swap the wrap for a large vegan bowl.", [item("N1", "vegan_bowl", size="large"), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "classic_burger"), item("L2", "fries")], "Replace the burger with satay noodles.", [item("N1", "satay_noodles"), item("L2", "fries")], ["L1"], ["L2"]),
        ([item("L1", "margherita_pizza", add=["mushroom"]), item("L2", "cola")], "Change the pizza to a chicken wrap.", [item("N1", "chicken_wrap"), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "cola"), item("L2", "vegan_bowl", add=["avocado"])], "Replace the vegan bowl with a double classic burger.", [item("L1", "cola"), item("N1", "classic_burger", size="double")], ["L2"], ["L1"]),
        ([item("L1", "fries", add=["truffle_oil"]), item("L2", "satay_noodles")], "Swap the satay noodles for a large pizza.", [item("L1", "fries", add=["truffle_oil"]), item("N1", "margherita_pizza", size="large")], ["L2"], ["L1"]),
        ([item("L1", "classic_burger", remove=["onion"]), item("L2", "cola")], "Change the no onion burger to a chicken wrap.", [item("N1", "chicken_wrap"), item("L2", "cola")], ["L1"], ["L2"]),
        ([item("L1", "vegan_bowl"), item("L2", "fries")], "Replace the fries with a large cola.", [item("L1", "vegan_bowl"), item("N1", "cola", size="large")], ["L2"], ["L1"]),
        ([item("L1", "satay_noodles", add=["broccoli"]), item("L2", "margherita_pizza")], "Swap the broccoli noodles for a vegan bowl with extra tofu.", [item("N1", "vegan_bowl", add=["extra_tofu"]), item("L2", "margherita_pizza")], ["L1"], ["L2"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, target, unchanged = templates[i % len(templates)]
        rows.append(case(
            f"replace_item_{i:03d}",
            "replace_item",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected),
            "Replacement should remove the referenced item and add the substitute without touching sides or drinks.",
            target_line_ids=target,
            unchanged_line_ids=unchanged,
            edit_history=history("Customer is substituting one line, not rebuilding the whole order."),
        ))
    return rows


def constraint_add_safe(n: int) -> list[dict]:
    templates = [
        ([item("L1", "fries"), item("L2", "cola")], "Also note I have a peanut allergy.", [item("L1", "fries"), item("L2", "cola")], ["peanut"], []),
        ([item("L1", "cola")], "I cannot have gluten.", [item("L1", "cola")], ["gluten"], []),
        ([item("L1", "fries", remove=["salt"])], "Mark this as dairy-free.", [item("L1", "fries", remove=["salt"])], ["dairy"], []),
        ([item("L1", "cola", size="large"), item("L2", "fries")], "Add a sesame allergy note.", [item("L1", "cola", size="large"), item("L2", "fries")], ["sesame"], []),
        ([item("L1", "fries"), item("L2", "cola")], "Make sure the order is vegan.", [item("L1", "fries"), item("L2", "cola")], [], ["vegan"]),
        ([item("L1", "margherita_pizza", remove=["mozzarella"]), item("L2", "cola")], "Also mark dairy as an allergy.", [item("L1", "margherita_pizza", remove=["mozzarella"]), item("L2", "cola")], ["dairy"], []),
        ([item("L1", "classic_burger", remove=["bun"], add=["gluten_free_bun"]), item("L2", "cola")], "Record gluten as an allergy.", [item("L1", "classic_burger", remove=["bun"], add=["gluten_free_bun"]), item("L2", "cola")], ["gluten"], []),
        ([item("L1", "margherita_pizza"), item("L2", "fries")], "Mark the order vegetarian.", [item("L1", "margherita_pizza"), item("L2", "fries")], [], ["vegetarian"]),
    ]
    rows = []
    for i in range(n):
        current, utt, expected, allergens, dietary = templates[i % len(templates)]
        rows.append(case(
            f"constraint_add_safe_{i:03d}",
            "constraint_add_safe",
            vary(utt, i),
            order(current),
            "accepted",
            order(expected, allergens=allergens, dietary=dietary),
            "A new safe constraint should be recorded without changing safe items.",
            unchanged_line_ids=[row["line_id"] for row in current],
            edit_history=history("Customer is adding a dietary or allergy constraint late in the order."),
        ))
    return rows


def constraint_new_conflict(n: int) -> list[dict]:
    templates = [
        ([item("L1", "satay_noodles")], "Actually I have a peanut allergy.", ["peanut"], [], "allergen_conflict", "rejected_safety"),
        ([item("L1", "margherita_pizza")], "I forgot to say I cannot have gluten.", ["gluten"], [], "allergen_conflict", "rejected_safety"),
        ([item("L1", "classic_burger", add=["extra_cheese"])], "Make sure it is vegan.", [], ["vegan"], "dietary_conflict", "needs_clarification"),
        ([item("L1", "vegan_bowl")], "Add soy allergy to the order.", ["soy"], [], "allergen_conflict", "rejected_safety"),
        ([item("L1", "vegan_bowl", remove=["tofu"])], "I have a sesame allergy.", ["sesame"], [], "allergen_conflict", "rejected_safety"),
        ([item("L1", "chicken_wrap")], "Mark this dairy-free.", ["dairy"], [], "allergen_conflict", "rejected_safety"),
        ([item("L1", "classic_burger", remove=["cheese"])], "Make this vegetarian.", [], ["vegetarian"], "dietary_conflict", "needs_clarification"),
        ([item("L1", "margherita_pizza", add=["extra_cheese"])], "Make it vegan.", [], ["vegan"], "dietary_conflict", "needs_clarification"),
    ]
    rows = []
    for i in range(n):
        current, utt, allergens, dietary, reason, status = templates[i % len(templates)]
        rows.append(case(
            f"constraint_new_conflict_{i:03d}",
            "constraint_new_conflict",
            vary(utt, i),
            order(current),
            status,
            order(current, allergens=allergens, dietary=dietary),
            "A newly stated constraint conflicts with the existing cart, so the agent must not accept execution.",
            unchanged_line_ids=[row["line_id"] for row in current],
            reasons=[reason],
            edit_history=history("The customer added the constraint after the item was already in the cart."),
        ))
    return rows


def unavailable_add(n: int) -> list[dict]:
    templates = [
        ([item("L1", "classic_burger")], "Add onion rings.", "unavailable_item"),
        ([item("L1", "fries")], "Add gravy to the fries.", "unavailable_modifier"),
        ([item("L1", "vegan_bowl")], "Put mozzarella on the bowl.", "unavailable_modifier"),
        ([item("L1", "cola")], "Add a cappuccino.", "unavailable_item"),
        ([item("L1", "classic_burger")], "Put pineapple on the burger.", "unavailable_modifier"),
        ([item("L1", "margherita_pizza")], "Add anchovies to the pizza.", "unavailable_modifier"),
        ([item("L1", "fries")], "Add ranch to the fries.", "unavailable_modifier"),
        ([item("L1", "cola", size="large")], "Make the cola decaf.", "unavailable_modifier"),
    ]
    rows = []
    for i in range(n):
        current, utt, reason = templates[i % len(templates)]
        rows.append(case(
            f"unavailable_add_{i:03d}",
            "unavailable_add",
            vary(utt, i),
            order(current),
            "needs_clarification",
            order(current),
            "Unavailable items or modifiers must not be invented or silently ignored.",
            unchanged_line_ids=[row["line_id"] for row in current],
            reasons=[reason],
            edit_history=history("The customer asks for something that may not exist in the menu."),
        ))
    return rows


def stale_reference(n: int) -> list[dict]:
    templates = [
        ([item("L1", "cola")], "Remove the fries too."),
        ([item("L1", "classic_burger")], "Make the wrap large."),
        ([item("L1", "fries")], "Take avocado off the bowl."),
        ([item("L1", "margherita_pizza")], "Remove the burger."),
        ([item("L1", "classic_burger")], "Take jalapeno off the wrap."),
        ([item("L1", "cola")], "Remove the second cola."),
        ([item("L1", "satay_noodles")], "Make the pizza small."),
        ([item("L1", "fries"), item("L2", "cola")], "No cheese on the burger."),
    ]
    rows = []
    for i in range(n):
        current, utt = templates[i % len(templates)]
        rows.append(case(
            f"stale_reference_{i:03d}",
            "stale_reference",
            vary(utt, i),
            order(current),
            "needs_clarification",
            order(current),
            "The user refers to a line that is not in the current cart; the agent must fail closed.",
            unchanged_line_ids=[row["line_id"] for row in current],
            reasons=["stale_reference"],
            edit_history=history("Earlier in the dialogue, the referenced item may have existed.", "The current cart shown here is authoritative."),
        ))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("data/orderdelta_v1.jsonl"))
    parser.add_argument("--cases-per-category", type=int, default=10)
    args = parser.parse_args()

    rows = build_cases(args.cases_per_category)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"wrote {len(rows)} cases to {args.out}")


if __name__ == "__main__":
    main()
