#!/usr/bin/env python3
"""Super Avvocato — internal snapshot system ("git interno").

A minimal, numbered snapshot tool: every commit gets an incrementing #0001,
#0002, … and a tar.gz archive of the whole project (minus noise). Works
independently of real git so Romeo can save checkpoints with a simple:

    ./scripts/snapshot.py commit -m "V7.11 Pro tools"

Subcommands:
    commit   — snapshot current state with a message
    list     — show every snapshot with # / date / size / message
    show     — inspect one snapshot (manifest + file count)
    restore  — extract a snapshot to a target directory (never overwrites root)
    diff     — list files that changed between a snapshot and current tree

Storage layout:
    .snapshots/
        index.json                          # list of every commit
        commits/NNNN_YYYY-MM-DDTHH-MM-SS/
            snapshot.tar.gz                 # archive of tracked files
            manifest.json                   # message, date, size, file list

Excludes:
    venv/, __pycache__/, *.pyc, .git/, .snapshots/, .DS_Store, logs/,
    data/raw/, data/processed/, data/index/, data/uploads/, data/app.db
    (the corpus-raw files and user DB — too heavy and regenerable).
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ── configuration ──────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / ".snapshots"
INDEX_FILE = SNAP_DIR / "index.json"
COMMITS_DIR = SNAP_DIR / "commits"

# Paths relative to ROOT that should never end up inside a snapshot.
# Patterns follow fnmatch semantics (globstar handled per-segment).
EXCLUDE_DIRS = {
    "venv",
    ".venv",
    ".git",
    ".snapshots",
    "node_modules",
    "__pycache__",
    "logs",
    "data/raw",         # 422MB of source PDFs/HTML — regeneratable via ingest
    "data/processed",   # 26MB derived
    "data/index",       # 24MB BM25 / embeddings
    "data/uploads",     # 48MB user uploads
}

EXCLUDE_FILES = {
    ".DS_Store",
    "data/app.db",       # user DB — live state, not code
    "data/.secret_key",
    "*.pyc",
    "*.pyo",
    "*.log",
}


# ── helpers ────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")


def _load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text("utf-8"))
    except json.JSONDecodeError:
        print(f"warning: {INDEX_FILE} is corrupt — treating as empty", file=sys.stderr)
        return []


def _save_index(entries: list[dict]) -> None:
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    INDEX_FILE.write_text(json.dumps(entries, indent=2, ensure_ascii=False), "utf-8")


def _is_excluded(rel: Path) -> bool:
    """True if *rel* (relative to ROOT) matches any exclude rule."""
    parts = rel.parts
    # Any parent segment in EXCLUDE_DIRS?
    for i in range(len(parts)):
        prefix = "/".join(parts[: i + 1])
        if prefix in EXCLUDE_DIRS or parts[i] in EXCLUDE_DIRS:
            return True
    name = rel.name
    full = str(rel)
    for pattern in EXCLUDE_FILES:
        if "/" in pattern:
            if fnmatch.fnmatch(full, pattern):
                return True
        elif fnmatch.fnmatch(name, pattern):
            return True
    return False


def _iter_tracked(root: Path):
    """Yield (absolute path, relative path) for every file we should include."""
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        # Prune excluded directories in-place so we don't recurse into them.
        dirnames[:] = [
            d for d in dirnames
            if not _is_excluded(rel_dir / d)
        ]
        for fname in filenames:
            rel = rel_dir / fname
            if _is_excluded(rel):
                continue
            yield root / rel, rel


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


# ── subcommands ────────────────────────────────────────────────────────────

def cmd_commit(args: argparse.Namespace) -> int:
    message = (args.message or "").strip()
    if not message:
        print("error: commit message is required (-m)", file=sys.stderr)
        return 2

    entries = _load_index()
    next_num = (entries[-1]["number"] + 1) if entries else 1
    stamp = _now()
    slot = f"{next_num:04d}_{stamp}"
    commit_dir = COMMITS_DIR / slot
    commit_dir.mkdir(parents=True, exist_ok=True)

    archive = commit_dir / "snapshot.tar.gz"
    files_meta: list[dict] = []
    total_size = 0

    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for abs_path, rel in _iter_tracked(ROOT):
            try:
                size = abs_path.stat().st_size
            except OSError:
                continue
            total_size += size
            tar.add(abs_path, arcname=str(rel))
            files_meta.append({
                "path": str(rel),
                "size": size,
                "sha256": _file_hash(abs_path) if size < 5_000_000 else None,
            })

    manifest = {
        "number": next_num,
        "timestamp": stamp,
        "message": message,
        "file_count": len(files_meta),
        "raw_total_bytes": total_size,
        "archive_bytes": archive.stat().st_size,
        "files": files_meta,
    }
    (commit_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8"
    )

    entries.append({
        "number": next_num,
        "timestamp": stamp,
        "slot": slot,
        "message": message,
        "file_count": len(files_meta),
        "archive_bytes": archive.stat().st_size,
    })
    _save_index(entries)

    print(f"✓ commit #{next_num:04d} — {message}")
    print(f"  {len(files_meta)} files · {_human_size(total_size)} raw · "
          f"{_human_size(archive.stat().st_size)} packed")
    print(f"  {commit_dir.relative_to(ROOT)}")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    entries = _load_index()
    if not entries:
        print("no snapshots yet — run `snapshot.py commit -m \"...\"` to start")
        return 0
    print(f"{'#':>5}  {'date (UTC)':<20}  {'size':>9}  message")
    print("─" * 70)
    for e in entries:
        print(f"#{e['number']:04d}  "
              f"{e['timestamp']:<20}  "
              f"{_human_size(e['archive_bytes']):>9}  "
              f"{e['message']}")
    return 0


def _find(number: int) -> dict | None:
    for e in _load_index():
        if e["number"] == number:
            return e
    return None


def cmd_show(args: argparse.Namespace) -> int:
    entry = _find(args.number)
    if not entry:
        print(f"no snapshot #{args.number:04d}", file=sys.stderr)
        return 1
    manifest_path = COMMITS_DIR / entry["slot"] / "manifest.json"
    m = json.loads(manifest_path.read_text("utf-8"))
    print(f"commit #{m['number']:04d}")
    print(f"  timestamp   {m['timestamp']}")
    print(f"  message     {m['message']}")
    print(f"  files       {m['file_count']}")
    print(f"  raw size    {_human_size(m['raw_total_bytes'])}")
    print(f"  archive     {_human_size(m['archive_bytes'])}")
    if args.files:
        print("  ── files ──")
        for f in m["files"]:
            print(f"    {_human_size(f['size']):>9}  {f['path']}")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    entry = _find(args.number)
    if not entry:
        print(f"no snapshot #{args.number:04d}", file=sys.stderr)
        return 1
    target = Path(args.target).resolve()
    if target.exists() and any(target.iterdir()):
        if not args.force:
            print(f"error: {target} is not empty (use --force to overwrite)",
                  file=sys.stderr)
            return 2
    target.mkdir(parents=True, exist_ok=True)
    archive = COMMITS_DIR / entry["slot"] / "snapshot.tar.gz"
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(target)  # noqa: S202 — our own archives, not user input
    print(f"✓ restored #{entry['number']:04d} → {target}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    entry = _find(args.number)
    if not entry:
        print(f"no snapshot #{args.number:04d}", file=sys.stderr)
        return 1
    manifest = json.loads((COMMITS_DIR / entry["slot"] / "manifest.json")
                          .read_text("utf-8"))
    snap_files = {f["path"]: f for f in manifest["files"]}

    current: dict[str, tuple[int, str | None]] = {}
    for abs_path, rel in _iter_tracked(ROOT):
        size = abs_path.stat().st_size
        sha = _file_hash(abs_path) if size < 5_000_000 else None
        current[str(rel)] = (size, sha)

    added, modified, removed = [], [], []
    for path, (size, sha) in current.items():
        if path not in snap_files:
            added.append(path)
            continue
        old = snap_files[path]
        if old["size"] != size or (old.get("sha256") and sha and old["sha256"] != sha):
            modified.append(path)
    for path in snap_files:
        if path not in current:
            removed.append(path)

    def show(label: str, paths: list[str], prefix: str) -> None:
        if not paths:
            return
        print(f"{label} ({len(paths)}):")
        for p in sorted(paths):
            print(f"  {prefix} {p}")

    show("added",    added,    "+")
    show("modified", modified, "~")
    show("removed",  removed,  "-")
    if not (added or modified or removed):
        print("no changes vs snapshot")
    return 0


# ── CLI wiring ─────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="snapshot",
        description="Super Avvocato internal snapshot tool (numbered mini-git).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("commit", help="save a new numbered snapshot")
    pc.add_argument("-m", "--message", required=True, help="commit message")
    pc.set_defaults(fn=cmd_commit)

    pl = sub.add_parser("list", help="list every snapshot")
    pl.set_defaults(fn=cmd_list)

    ps = sub.add_parser("show", help="inspect a snapshot manifest")
    ps.add_argument("number", type=int, help="commit number (e.g. 1)")
    ps.add_argument("--files", action="store_true", help="also list every file")
    ps.set_defaults(fn=cmd_show)

    pr = sub.add_parser("restore", help="extract a snapshot to a directory")
    pr.add_argument("number", type=int, help="commit number")
    pr.add_argument("target", help="directory to extract into")
    pr.add_argument("--force", action="store_true", help="allow non-empty target")
    pr.set_defaults(fn=cmd_restore)

    pd = sub.add_parser("diff", help="list files changed vs a snapshot")
    pd.add_argument("number", type=int, help="commit number to compare against")
    pd.set_defaults(fn=cmd_diff)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
