# Remote cleanup receipt

The disposable remote root was:

`/ssd/scxi253/orderdelta-v3-pilot-20260831T0545-codex`

After all raw outputs, logs, runtime metadata, hashes, and executed source were
copied to this local directory and checked, the remote root was deleted.

A final read-only verification at `2026-08-31T05:57:03+08:00` reported:

- the exact project root was absent;
- no path whose name contained `orderdelta` or `order-delta` remained under
  `/ssd/scxi253` to depth 3;
- no such path remained under `/data/home/scxi253` to depth 5; and
- no active Slurm job for user `scxi253` had an OrderDelta-like job name.

The pre-existing shared Qwen model and CUDA/PyTorch container were not created
for OrderDelta and were deliberately left untouched.
