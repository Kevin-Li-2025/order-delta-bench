from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def git_file_sha256(root: Path, commit: str, relative_path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout).hexdigest()


def verify_manifest(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    mismatches: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    commit = str(manifest.get("git_commit") or "")
    for relative_path, expected in sorted(manifest["files"].items()):
        path = root / relative_path
        observed = git_file_sha256(root, commit, relative_path) if commit else None
        if observed is not None:
            sources[relative_path] = f"git:{commit}"
        else:
            observed = file_sha256(path) if path.is_file() else None
            sources[relative_path] = "working_tree"
        if observed != expected:
            mismatches.append({
                "path": relative_path,
                "expected_sha256": expected,
                "observed_sha256": observed,
            })
    return {
        "manifest": str(manifest_path),
        "files": len(manifest["files"]),
        "sources": sources,
        "mismatches": len(mismatches),
        "mismatch_examples": mismatches[:50],
        "verified": not mismatches,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = verify_manifest(args.manifest, args.root)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.out.with_suffix(args.out.suffix + ".tmp")
        temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.out)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["verified"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
