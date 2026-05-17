"""Atlas store — markdown wiki with read/write/search."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Page:
    path: str  # relative to atlas root
    title: str
    content: str


@dataclass
class PageWrite:
    path: str  # where to write (creates if new, overwrites if exists)
    title: str
    content: str  # full markdown body
    summary: str  # one-line for index.md


class Atlas:
    def __init__(self, root: Path):
        self.root = root
        self._lock = threading.Lock()
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        for d in ("sources", "concepts", "entities", "projects"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not (self.root / "index.md").exists():
            (self.root / "index.md").write_text("# Atlas Index\n")
        if not (self.root / "log.md").exists():
            (self.root / "log.md").write_text("# Atlas Log\n")

    def read(self, query: str, limit: int = 20) -> list[Page]:
        """Read index.md, find pages matching query keywords, return content."""
        index_text = (self.root / "index.md").read_text()
        keywords = query.lower().split()
        matches: list[Page] = []

        for line in index_text.splitlines():
            if not line.startswith("- ["):
                continue
            line_lower = line.lower()
            if any(kw in line_lower for kw in keywords):
                path = self._parse_index_path(line)
                if not path:
                    continue
                try:
                    resolved = self._safe_resolve(path)
                except ValueError:
                    continue
                if resolved.exists():
                    content = resolved.read_text()
                    title = self._extract_title(content)
                    matches.append(Page(path=path, title=title, content=content))
                    if len(matches) >= limit:
                        break

        return matches

    def read_all_summaries(self) -> str:
        """Return the full index.md content."""
        return (self.root / "index.md").read_text()

    def _safe_resolve(self, relative: str) -> Path:
        """Resolve a relative path and ensure it stays within the atlas root."""
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(f"Path traversal blocked: {relative}")
        return resolved

    def write(self, writes: list[PageWrite], log_entry: str) -> None:
        """Atomic batch: write pages, update index, append log."""
        with self._lock:
            for w in writes:
                path = self._safe_resolve(w.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {w.title}\n\n{w.content}")

            self._update_index(writes)
            self._append_log(log_entry)

    def _update_index(self, writes: list[PageWrite]) -> None:
        """Add/update entries in index.md."""
        index_path = self.root / "index.md"
        lines = index_path.read_text().splitlines()

        existing: dict[str, int] = {}
        for i, line in enumerate(lines):
            path = self._parse_index_path(line)
            if path:
                existing[path] = i

        for w in writes:
            entry = f"- [{w.title}]({w.path}) — {w.summary}"
            if w.path in existing:
                lines[existing[w.path]] = entry
            else:
                lines.append(entry)

        index_path.write_text("\n".join(lines) + "\n")

    def _append_log(self, entry: str) -> None:
        """Append timestamped entry to log.md."""
        log_path = self.root / "log.md"
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with open(log_path, "a") as f:
            f.write(f"\n## [{timestamp}] {entry}\n")

    @staticmethod
    def _parse_index_path(line: str) -> str | None:
        """Extract path from index line: - [Title](path) — summary"""
        start = line.find("](")
        end = line.find(")", start + 2) if start != -1 else -1
        if start != -1 and end != -1:
            return line[start + 2 : end]
        return None

    @staticmethod
    def _extract_title(content: str) -> str:
        """Extract title from first # heading."""
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "Untitled"
