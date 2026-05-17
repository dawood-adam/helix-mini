# helix_mini.sandbox

Validates and sanitizes all LLM-generated output before it reaches the filesystem. Every `atlas_writes` array from an agent response passes through `sanitize_atlas_writes()` before `Atlas.write()` is called.

---

## `sanitize_atlas_writes`

```python
def sanitize_atlas_writes(
    raw_writes: list[dict],
    atlas_root: Path,
) -> list[PageWrite]
```

**Parameters:**
- `raw_writes` (`list[dict]`) — Raw write dicts from LLM output. Each must have `path`, `title`, `content`, and `summary` keys.
- `atlas_root` (`Path`) — Atlas root directory for path resolution.

**Returns:** `list[PageWrite]` — Validated writes ready for `Atlas.write()`. Invalid entries are silently skipped with a warning log.

**Behavior:**
1. Truncates the batch to `MAX_WRITES_PER_BATCH` (50).
2. Skips entries missing required fields.
3. Validates each entry's path, title, content, and summary.
4. Returns only entries that pass all checks.

**Example:**
```python
from helix_mini.sandbox import sanitize_atlas_writes

raw = [{"path": "sources/p.md", "title": "T", "content": "...", "summary": "s"}]
writes = sanitize_atlas_writes(raw, Path("/tmp/atlas"))
# writes = [PageWrite(path="sources/p.md", title="T", content="...", summary="s")]
```

---

## `validate_path`

```python
def validate_path(path: str, atlas_root: Path) -> Path
```

**Parameters:**
- `path` (`str`) — Relative path from LLM output.
- `atlas_root` (`Path`) — Atlas root for resolution.

**Returns:** Resolved `Path` within the atlas root.

**Raises:**
- `SandboxError` — If the path is absolute, contains `..`, doesn't start with an allowed subdirectory (`sources`, `concepts`, `entities`, `projects`), exceeds 255 characters, or resolves outside the atlas root.

---

## `validate_title`

```python
def validate_title(title: str) -> str
```

**Returns:** Cleaned title string. Control characters are stripped (all of `\x00`–`\x1f` and `\x7f` except tab `\x09`, newline `\x0a`, and carriage return `\x0d`, which are preserved). Truncated to 200 characters if too long. Also used internally to validate `summary` fields in `sanitize_atlas_writes()`.

**Raises:**
- `SandboxError` — If the title is empty after sanitization.

---

## `validate_content`

```python
def validate_content(content: str) -> str
```

**Returns:** Content string, truncated to 500 KB with a `"[... content truncated by sandbox ...]"` notice appended if oversized.

---

## `validate_ingest_source`

```python
def validate_ingest_source(file_path: Path, base_folder: Path) -> bool
```

**Parameters:**
- `file_path` (`Path`) — File to check.
- `base_folder` (`Path`) — The input folder boundary.

**Returns:** `True` if the file is safe to read. Returns `False` for symlinks pointing outside `base_folder` or unresolvable symlinks.

---

## `SandboxError`

```python
class SandboxError(Exception):
    """Raised when LLM output violates sandbox rules."""
```

---

## Constants

| Constant | Value | Purpose |
|----------|-------|---------|
| `ALLOWED_SUBDIRS` | `{"sources", "concepts", "entities", "projects"}` | Valid first-level directories in Atlas |
| `MAX_PAGE_CONTENT_BYTES` | `500_000` | 500 KB content limit per page |
| `MAX_PAGE_TITLE_LENGTH` | `200` | Title character limit |
| `MAX_WRITES_PER_BATCH` | `50` | Maximum writes per LLM response |
| `MAX_PATH_LENGTH` | `255` | Path character limit |
