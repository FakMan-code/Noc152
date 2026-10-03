"""Generic source ingestion: local path or public git clone."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse


@dataclass
class SourceFile:
    relative_path: str
    absolute_path: Path
    size_bytes: int


def is_git_url(value: str) -> bool:
    v = value.strip()
    if v.startswith("git@"):
        return True
    parsed = urlparse(v)
    if parsed.scheme in {"http", "https", "ssh", "git"} and (
        v.endswith(".git") or "github.com" in v or "gitlab.com" in v or "bitbucket.org" in v
    ):
        return True
    return False


def materialize_source(source: str, cache_dir: Path) -> tuple[Path, str, bool]:
    """
    Returns (root_path, source_uri, owns_temp_dir).
    If source is a git URL, shallow-clones into cache_dir.
    """
    source = source.strip()
    if is_git_url(source):
        cache_dir.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-zA-Z0-9._-]+", "_", source.rstrip("/").split("/")[-1].removesuffix(".git"))
        dest = cache_dir / name
        if dest.exists():
            shutil.rmtree(dest)
        cmd = ["git", "clone", "--depth", "1", source, str(dest)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return dest, source, True

    path = Path(source).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Source not found: {path}")
    return path, str(path), False


def should_ignore(rel: str, ignore_dirs: set[str], ignore_globs: list[str]) -> bool:
    parts = Path(rel).parts
    if any(p in ignore_dirs for p in parts):
        return True
    name = Path(rel).name
    for pattern in ignore_globs:
        if Path(name).match(pattern) or Path(rel).match(pattern):
            return True
    return False


def is_text_candidate(path: Path, text_exts: set[str], special_names: set[str]) -> bool:
    if path.name in special_names:
        return True
    if path.suffix.lower() in text_exts:
        return True
    # Dockerfile.* variants
    if path.name.startswith("Dockerfile"):
        return True
    return False


def walk_source(
    root: Path,
    *,
    text_exts: set[str],
    special_names: set[str],
    ignore_dirs: set[str],
    ignore_globs: list[str],
    max_file_bytes: int,
    max_files: int,
) -> Iterator[SourceFile]:
    count = 0
    for abs_path in sorted(root.rglob("*")):
        if not abs_path.is_file():
            continue
        try:
            rel = abs_path.relative_to(root).as_posix()
        except ValueError:
            continue
        if should_ignore(rel, ignore_dirs, ignore_globs):
            continue
        if not is_text_candidate(abs_path, text_exts, special_names):
            continue
        size = abs_path.stat().st_size
        if size == 0 or size > max_file_bytes:
            continue
        yield SourceFile(relative_path=rel, absolute_path=abs_path, size_bytes=size)
        count += 1
        if count >= max_files:
            return
