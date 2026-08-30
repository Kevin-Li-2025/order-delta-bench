# Error examples

## Qwen/Qwen2.5-7B-Instruct-local / json_patch / add_item_003

- Category: `add_item`
- Edit: One change: Add a small margherita pizza with mushroom.
- Expected status: `accepted`
- Error: `missing_or_stale_version_test`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / rewrite_with_ids / add_item_003

- Category: `add_item`
- Edit: One change: Add a small margherita pizza with mushroom.
- Expected status: `accepted`
- Error: `bad_top_level_keys;updated_order_bad_keys;bad_reasons`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / rewrite_with_ids / constraint_add_safe_004

- Category: `constraint_add_safe`
- Edit: Before checkout, Make sure the order is vegan.
- Expected status: `accepted`
- Error: `None`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / json_patch / constraint_add_safe_004

- Category: `constraint_add_safe`
- Edit: Before checkout, Make sure the order is vegan.
- Expected status: `accepted`
- Error: `missing_or_stale_version_test`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / line_patch / constraint_add_safe_004

- Category: `constraint_add_safe`
- Edit: Before checkout, Make sure the order is vegan.
- Expected status: `accepted`
- Error: `None`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / json_patch / constraint_new_conflict_011

- Category: `constraint_new_conflict`
- Edit: Small correction: Add soy allergy to the order.
- Expected status: `rejected_safety`
- Error: `missing_or_stale_version_test`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / rewrite_with_ids / constraint_new_conflict_011

- Category: `constraint_new_conflict`
- Edit: Small correction: Add soy allergy to the order.
- Expected status: `rejected_safety`
- Error: `None`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / line_patch / constraint_new_conflict_011

- Category: `constraint_new_conflict`
- Edit: Small correction: Add soy allergy to the order.
- Expected status: `rejected_safety`
- Error: `None`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / json_patch / modifier_add_scoped_014

- Category: `modifier_add_scoped`
- Edit: Just to be clear, Put truffle oil on the fries only.
- Expected status: `accepted`
- Error: `missing_or_stale_version_test`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / rewrite_with_ids / modifier_add_scoped_014

- Category: `modifier_add_scoped`
- Edit: Just to be clear, Put truffle oil on the fries only.
- Expected status: `accepted`
- Error: `updated_order_bad_keys`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / line_patch / modifier_add_scoped_014

- Category: `modifier_add_scoped`
- Edit: Just to be clear, Put truffle oil on the fries only.
- Expected status: `accepted`
- Error: `operation_0_changes_extra_keys;schema_invalid_no_execution`
- Unsafe state change: `False`

## Qwen/Qwen2.5-7B-Instruct-local / line_patch / modifier_reversal_000

- Category: `modifier_reversal`
- Edit: Put the cheese back but keep no onion.
- Expected status: `accepted`
- Error: `None`
- Unsafe state change: `False`
