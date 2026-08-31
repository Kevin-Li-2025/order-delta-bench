# Verifier Scoring

OrderDeltaBench v3 reduces each model output to an identity-bearing final state,
an exact JSON-pointer diff, and a status decision. The controlled comparison is
among `rewrite_with_ids`, `line_patch`, and `json_patch`, which all receive the
same stable-ID `current_state`. Legacy ID-free `rewrite` remains available only
as a separate stable-ID ablation.

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
- `state_version`: optimistic-concurrency version used by mutation interfaces.
- `expected_writes`: authorized JSON-pointer state diff.
- `protected_paths`: paths that must not change.
- `semantic_program_id` and `template_family_id`: cluster units for statistics.

## JSON and Schema Handling

The verifier first tries to parse the model response as JSON. If the model wraps
JSON in a markdown code fence, the fenced JSON is parsed. If the response
contains surrounding prose, the verifier attempts to parse the substring from
the first `{` to the last `}`.

No semantic repair is performed. Missing fields, extra fields, wrong primitive
types, bad operation names, and malformed item objects fail schema validation.

Invalid JSON or schema-invalid output receives `semantic_ok = false`.
Component metrics still record the exact failure class where possible.

## Rewrite Interfaces

The rewrite interface returns:

```json
{
  "status": "accepted",
  "updated_order": {"items": [], "constraints": {"allergens": [], "dietary": []}},
  "clarification_question": null,
  "reasons": []
}
```

Legacy `rewrite` omits line IDs and therefore uses value-multiset equality. Its
`identity_observable` flag is false and it must not contribute to identity
rates. `rewrite_with_ids` uses the same shape with `line_id` on every item. The
v3 verifier rejects missing or duplicate IDs and compares the complete mapping
from stable identity to item state.

## Line-Patch Interface

The line-patch interface returns:

```json
{
  "status": "accepted",
  "base_version": 1,
  "operations": [],
  "clarification_question": null,
  "reasons": []
}
```

Each operation is one member of a tagged union: `add_item`, `remove_line`,
`update_line`, or `set_constraints`. `update_line.changes` contains only final
field values that actually change; the old schema's null and empty-array
baggage is not accepted.

The executor validates `base_version`, operation shapes, identities, and write
conflicts before committing. Execution occurs on a copy. A missing line, stale
version, malformed operation, duplicate write, or remove-then-update conflict
rolls back the whole patch and sets `operation_executable = false`.

## JSON Patch Interface

`json_patch` addresses `/lines/<line_id>`, `/constraints`, and their children.
Its first operation must be `{"op":"test","path":"/version","value":N}`.
Only `test`, `add`, `remove`, and `replace` are accepted. Failed tests, missing
paths, forbidden version writes, and overlapping writes roll back atomically.

## Authorized State Diff

For identity-bearing modes, the verifier computes stable-ID diffs from
`current_order` to both the oracle and the applied output. A write identity is
its JSON pointer, operation type, and final value. This yields:

- authorized-write precision: correct authorized writes / all actual writes;
- authorized-write recall: correct expected writes / all expected writes;
- unexpected and missing diff entries;
- collateral write count;
- protected-path preservation and wrong-object identity errors.

`semantic_ok` requires both precision and recall to equal 1.0.

## Non-Accepted Edits

For cases whose oracle status is `needs_clarification` or `rejected_safety`,
the model should fail closed. That means:

- status must match the oracle status;
- the requested cart edit must not be executed;
- only oracle-authorized writes may occur; for conflict cases this can include
  recording a newly stated constraint while the requested cart edit is blocked.

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
- `identity_observable`
- `identity_fidelity`
- `authorized_write_precision`
- `authorized_write_recall`
- `collateral_write_count`
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

`rewrite_with_ids`, `line_patch`, and `json_patch` receive byte-equivalent
`current_state`, menu, edit, and history information. Only the output mutation
interface changes. Comparing legacy `rewrite` to `rewrite_with_ids` measures the
stable-ID information effect; comparing `rewrite_with_ids` to either patch
condition measures the interface effect. Bootstrap confidence intervals resample
`semantic_program_id` clusters rather than treating lexical variants as
independent tasks.

## Verifier Promotion Gate

`python -m src.orderdelta.mutation_testing` builds gold outputs, legal reordered
alternatives, and invalid mutations such as protected-object writes, line-ID
swaps, constraint-only drift, stale versions, missing writes, and conflicting
operations. Promotion requires 100% invalid-mutation kill and less than 0.5%
false rejection of legal alternatives. This is verifier evidence, not model
performance evidence.
