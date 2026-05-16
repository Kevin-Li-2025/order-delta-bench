# Verifier Scoring

OrderDeltaBench scores both interfaces by reducing the model output to the same
object: a final cart state plus a status decision. This keeps the comparison
between `rewrite` and `line_patch` as fair as possible.

## Inputs

Each case contains:

- `current_order`: cart before the edit, including stable `line_id` values.
- `edit_history`: short prior-turn context; prompts include it, but scoring
  treats `current_order` as authoritative.
- `utterance`: user edit.
- `expected_status`: one of `accepted`, `needs_clarification`, or
  `rejected_safety`.
- `expected_order`: oracle final cart.
- `target_line_ids`: lines that should be edited or removed.
- `unchanged_line_ids`: lines that should survive unchanged.

## JSON and Schema Handling

The verifier first tries to parse the model response as JSON. If the model wraps
JSON in a markdown code fence, the fenced JSON is parsed. If the response
contains surrounding prose, the verifier attempts to parse the substring from
the first `{` to the last `}`.

No semantic repair is performed. Missing fields, extra fields, wrong primitive
types, bad operation names, and malformed item objects fail schema validation.

Invalid JSON or schema-invalid output receives `semantic_ok = false`.
Component metrics still record the exact failure class where possible.

## Rewrite Interface

The rewrite interface returns:

```json
{
  "status": "accepted",
  "updated_order": {"items": [], "constraints": {"allergens": [], "dietary": []}},
  "clarification_question": null,
  "reasons": []
}
```

The verifier directly compares `updated_order` with the oracle final order.
Line IDs are not expected in rewrite output. The comparison uses item multiset
equality over SKU, quantity, size, additions, removals, and special
instructions, plus exact constraint equality.

## Line-Patch Interface

The line-patch interface returns:

```json
{
  "status": "accepted",
  "operations": [],
  "clarification_question": null,
  "reasons": []
}
```

The verifier applies the operation list to `current_order` in sequence. It then
strips line IDs and compares the resulting cart with the same oracle final
order used for rewrite scoring.

Patch operations are executable only if referenced line IDs exist and operation
payloads are well formed. For example, `remove_line` with a missing line ID
sets `operation_executable = false` and `semantic_ok = false`.

## Non-Accepted Edits

For cases whose oracle status is `needs_clarification` or `rejected_safety`,
the model should fail closed. That means:

- status must match the oracle status;
- the requested cart edit must not be executed;
- existing cart items must remain unchanged;
- stated constraints must be preserved or updated exactly as specified by the
  oracle.

If the model accepts the edit or changes item state when the oracle requires
clarification or rejection, `unsafe_state_change = true`.

## Partial Correctness

`semantic_ok` is strict and all-or-nothing. Partial correctness is recorded in
separate component metrics:

- `status_correct`
- `order_exact`
- `constraints_exact`
- `state_preserved_when_blocked`
- `operation_executable`
- `unintended_drift`
- `identity_error`
- `unsafe_state_change`

This avoids hiding severe deployment failures behind approximate scores while
still making error analysis possible.

## Unavailable and Hallucinated Content

If a model invents an unavailable item or modifier and accepts the edit, the
final cart will fail exact order comparison and may also trigger
`unsafe_state_change` depending on the oracle category.

If a model silently ignores an unavailable request but marks the status as
`accepted`, it fails `status_correct` because the oracle expects
`needs_clarification`.

## Stale References

A stale-reference case asks the model to edit a line that is not present in the
current cart. The expected behavior is fail-closed clarification with no cart
item changes. Any accepted edit or cart mutation is scored as an unsafe state
change.

## Fairness Between Interfaces

Both interfaces receive the same menu, the same user edit, and the same current
cart semantics. The rewrite prompt hides line IDs and provides item positions,
while the patch prompt exposes stable line IDs because line identity is the
interface being tested. After output normalization, both interfaces are judged
against the same oracle final cart and status.
