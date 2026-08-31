from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
SAFE_FIELDS = (
    "id",
    "name",
    "created",
    "owned_by",
    "description",
    "architecture",
    "context_length",
    "per_request_limits",
    "pricing",
    "quantization",
    "regions",
    "supported_features",
    "supported_sampling_parameters",
)


def fetch_catalog(
    base_url: str,
    api_key: str,
    timeout: float = 90.0,
    max_retries: int = 2,
) -> list[dict[str, Any]]:
    url = urllib.parse.urljoin(base_url, "models") + "?verbose=true"
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
            return list(payload.get("data", []))
        except (TimeoutError, urllib.error.URLError):
            if attempt >= max_retries:
                raise
            time.sleep(1.5 * (2**attempt))
    raise AssertionError("unreachable")


def sanitized_snapshot(
    catalog: list[dict[str, Any]], selected_models: list[str], base_url: str
) -> dict[str, Any]:
    by_id = {str(row.get("id")): row for row in catalog}
    missing = sorted(set(selected_models) - set(by_id))
    if missing:
        raise ValueError(f"models absent from live catalog: {missing}")
    unsupported = sorted(
        model
        for model in selected_models
        if "structured_outputs" not in (by_id[model].get("supported_features") or [])
    )
    if unsupported:
        raise ValueError(f"models do not advertise structured_outputs: {unsupported}")
    return {
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "endpoint": urllib.parse.urljoin(base_url, "models") + "?verbose=true",
        "selection_gate": "advertises_structured_outputs",
        "models": [
            {field: by_id[model].get(field) for field in SAFE_FIELDS}
            for model in selected_models
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("NEBIUS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()

    api_key = os.environ.get("NEBIUS_API_KEY")
    if not api_key:
        raise SystemExit("NEBIUS_API_KEY is required but was not found in the environment.")
    snapshot = sanitized_snapshot(
        fetch_catalog(args.base_url, api_key, args.timeout, args.max_retries),
        args.models,
        args.base_url,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(args.out)
    print(f"wrote {len(snapshot['models'])} model records to {args.out}")


if __name__ == "__main__":
    main()
