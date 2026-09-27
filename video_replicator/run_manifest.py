from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def input_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    record: dict[str, Any] = {
        "path": str(resolved),
        "exists": resolved.is_file(),
    }
    if resolved.is_file():
        stat = resolved.stat()
        record.update({
            "size_bytes": stat.st_size,
            "sha256": sha256_file(resolved),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
    return record


def project_artifact_hashes(project_dir: Path, input_video: Path | None = None) -> dict[str, str]:
    root = project_dir.resolve()
    video = input_video or root / "inputs" / "reference.mp4"
    candidates: list[tuple[str, Path]] = [
        ("input_video", video),
        ("product_manifest", root / "inputs" / "product.json"),
        ("deep_analysis", root / "analysis" / "deep-analysis.json"),
        ("replication_framework", root / "analysis" / "replication-framework.json"),
        ("plan", root / "analysis" / "plan.json"),
        ("script_timeline", root / "analysis" / "script-timeline.json"),
        ("generated_prompts", root / "outputs" / "prompts.json"),
        ("compiled_prompt", root / "outputs" / "final_product_swap_prompt.md"),
        ("reference_collage_manifest", root / "outputs" / "reference_collages" / "manifest.json"),
        ("newapi_request_fingerprint", root / "outputs" / "newapi" / "request-fingerprint.json"),
        ("hypit_author", root / "hypit" / "product-swap.svml"),
        ("hypit_run", root / "hypit" / "product-swap.svrun"),
    ]
    product_manifest = root / "inputs" / "product.json"
    if product_manifest.is_file():
        data = json.loads(product_manifest.read_text(encoding="utf-8-sig"))
        for index, relative_path in enumerate(data.get("references", []), start=1):
            path = (root / str(relative_path)).resolve()
            if path.is_relative_to(root):
                candidates.append((f"product_reference_{index}", path))

    collage_manifest = root / "outputs" / "reference_collages" / "manifest.json"
    if collage_manifest.is_file():
        data = json.loads(collage_manifest.read_text(encoding="utf-8-sig"))
        for index, sheet in enumerate(data.get("shot_sheets", []), start=1):
            path = Path(str(sheet.get("output", "")))
            candidates.append((f"reference_sheet_{index}", path))

    return {
        name: sha256_file(path)
        for name, path in candidates
        if path.is_file()
    }


def current_project_artifact_hashes(project_dir: Path) -> dict[str, str]:
    manifest_path = project_dir / "outputs" / "run-manifest.json"
    input_video = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        recorded_path = manifest.get("input_video", {}).get("path")
        if recorded_path:
            input_video = Path(recorded_path)
    return project_artifact_hashes(project_dir, input_video)


REQUIRED_REVIEW_ARTIFACTS = (
    "input_video",
    "product_manifest",
    "deep_analysis",
    "replication_framework",
    "script_timeline",
    "reference_collage_manifest",
    "compiled_prompt",
)


def missing_review_artifacts(hashes: dict[str, str]) -> list[str]:
    missing = [name for name in REQUIRED_REVIEW_ARTIFACTS if not hashes.get(name)]
    if not any(name.startswith("reference_sheet_") for name in hashes):
        missing.append("reference_sheet")
    if not any(name.startswith("product_reference_") for name in hashes):
        missing.append("product_reference")
    return missing


def write_run_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
