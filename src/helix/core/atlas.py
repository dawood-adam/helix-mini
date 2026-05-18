"""Atlas store — a markdown wiki with keyword read/batch write/index.

Store only: imports nothing from sandbox, so ``helix.sandbox`` can import
``PageWrite`` from here without a cycle.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Page:
    path: str
    title: str
    content: str


@dataclass
class PageWrite:
    path: str
    title: str
    content: str
    summary: str


class Atlas:
    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._ensure_structure()

    def _ensure_structure(self) -> None:
        for d in ("sources", "concepts", "entities", "projects", "inbox"):
            (self.root / d).mkdir(parents=True, exist_ok=True)
        if not (self.root / "index.md").exists():
            (self.root / "index.md").write_text("# Atlas Index\n")
        if not (self.root / "log.md").exists():
            (self.root / "log.md").write_text("# Atlas Log\n")

    def read(self, query: str, limit: int = 20) -> list[Page]:
        index_text = (self.root / "index.md").read_text()
        keywords = query.lower().split()
        matches: list[Page] = []
        for line in index_text.splitlines():
            if not line.startswith("- ["):
                continue
            if any(kw in line.lower() for kw in keywords):
                path = self._parse_index_path(line)
                if not path:
                    continue
                try:
                    resolved = self._safe_resolve(path)
                except ValueError:
                    continue
                if resolved.exists():
                    content = resolved.read_text()
                    matches.append(
                        Page(path=path, title=self._extract_title(content), content=content)
                    )
                    if len(matches) >= limit:
                        break
        return matches

    def read_all_summaries(self) -> str:
        return (self.root / "index.md").read_text()

    def _safe_resolve(self, relative: str) -> Path:
        resolved = (self.root / relative).resolve()
        if not resolved.is_relative_to(self.root.resolve()):
            raise ValueError(f"Path traversal blocked: {relative}")
        return resolved

    def write(self, writes: list[PageWrite], log_entry: str) -> None:
        with self._lock:
            for w in writes:
                path = self._safe_resolve(w.path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(f"# {w.title}\n\n{w.content}")
            self._update_index(writes)
            self._append_log(log_entry)

    def _update_index(self, writes: list[PageWrite]) -> None:
        index_path = self.root / "index.md"
        lines = index_path.read_text().splitlines()
        existing: dict[str, int] = {}
        for i, line in enumerate(lines):
            p = self._parse_index_path(line)
            if p:
                existing[p] = i
        for w in writes:
            entry = f"- [{w.title}]({w.path}) — {w.summary}"
            if w.path in existing:
                lines[existing[w.path]] = entry
            else:
                lines.append(entry)
        index_path.write_text("\n".join(lines) + "\n")

    def _append_log(self, entry: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        with open(self.root / "log.md", "a") as f:
            f.write(f"\n## [{ts}] {entry}\n")

    @staticmethod
    def _parse_index_path(line: str) -> str | None:
        start = line.find("](")
        end = line.find(")", start + 2) if start != -1 else -1
        if start != -1 and end != -1:
            return line[start + 2 : end]
        return None

    @staticmethod
    def _extract_title(content: str) -> str:
        for line in content.splitlines():
            if line.startswith("# "):
                return line[2:].strip()
        return "Untitled"
