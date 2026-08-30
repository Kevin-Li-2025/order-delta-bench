# V3 verifier evidence

`v3_mutation_report.json` is an offline verifier receipt over all 360 v3 cases
and four evaluator modes. It records three distinct gates:

- every generated oracle output must pass;
- every generated semantically equivalent alternative must pass;
- every generated invalid mutation must fail `semantic_ok`.

The current receipt covers 1,440 oracle outputs, 1,440 legal alternatives, and
6,453 invalid mutations. It has zero oracle failures, zero false rejections,
and zero surviving invalid mutations.

Reproduce it without a model or API key:

```bash
python3 -m src.orderdelta.mutation_testing \
  --dataset data/orderdelta_v3_identity_controlled.jsonl \
  --out /tmp/v3_mutation_report.json

cmp results/verification/v3_mutation_report.json \
  /tmp/v3_mutation_report.json
```

This receipt validates the implemented mutation operators and verifier paths.
It is not evidence that the mutation set is complete, that a provider supports
every schema keyword, or that any model performs better under one interface.
