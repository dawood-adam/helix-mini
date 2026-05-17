# helix_mini.atlas

Persistent markdown wiki with keyword search, file ingestion, and thread-safe writes.

---

## `Atlas`

**Module:** `helix_mini.atlas.store`

### Constructor

```python
Atlas(root: Path)
```

**Parameters:**
- `root` (`Path`) — Directory for the wiki. Created automatically along with subdirectories `sources/`, `concepts/`, `entities/`, `projects/`, plus `index.md` and `log.md`.

**Example:**
```python
from helix_mini.atlas import Atlas

atlas = Atlas(Path("~/.helix-mini/atlas").expanduser())
```

---

### `Atlas.read`

```python
def read(self, query: str, limit: int = 20) -> list[Page]
```

**Parameters:**
- `query` (`str`) — Space-separated keywords. Matches are case-insensitive against index entries.
- `limit` (`int`, default: `20`) — Maximum pages to return.

**Returns:** `list[Page]` — Matching pages with content loaded from disk.

**Behavior:** Reads `index.md`, splits query into keywords, finds lines where any keyword appears in the title or path, resolves each path via `_safe_resolve()` (blocking traversal attempts), reads the file, and returns `Page` objects. Returns an empty list if no matches.

**Example:**
```python
pages = atlas.read("cardiac simulation")
for p in pages:
    print(f"{p.title}: {p.content[:100]}")
```

---

### `Atlas.read_all_summaries`

```python
def read_all_summaries(self) -> str
```

**Returns:** `str` — Full contents of `index.md`.

---

### `Atlas.write`

```python
def write(self, writes: list[PageWrite], log_entry: str) -> None
```

**Parameters:**
- `writes` (`list[PageWrite]`) — Pages to create or update.
- `log_entry` (`str`) — Description appended to `log.md` with a UTC timestamp.

**Behavior:** Acquires a thread lock, then atomically: writes each page file (creating parent directories as needed), updates `index.md` entries (add or replace), and appends a timestamped entry to `log.md`. Paths are validated via `_safe_resolve()`.

**Raises:**
- `ValueError` — If any `PageWrite.path` resolves outside the atlas root.

**Example:**
```python
from helix_mini.atlas import Atlas, PageWrite

atlas = Atlas(Path("/tmp/atlas"))
atlas.write(
    [PageWrite(path="sources/paper.md", title="My Paper", content="...", summary="A paper")],
    log_entry="scout | my-project",
)
```

---

## `Page`

**Module:** `helix_mini.atlas.store`

```python
@dataclass
class Page:
    path: str      # relative to atlas root
    title: str
    content: str
```

Represents a wiki page read from disk. Returned by `Atlas.read()`.

---

## `PageWrite`

**Module:** `helix_mini.atlas.store`

```python
@dataclass
class PageWrite:
    path: str      # relative path (e.g., "sources/paper.md")
    title: str     # page heading
    content: str   # full markdown body
    summary: str   # one-line description for index.md
```

Represents a page to be written. Passed to `Atlas.write()` and produced by `sanitize_atlas_writes()`.

---

## `ingest_folder`

**Module:** `helix_mini.atlas.ingest`

```python
def ingest_folder(folder: Path, raw_root: Path) -> list[Page]
```

**Parameters:**
- `folder` (`Path`) — Input directory to read files from.
- `raw_root` (`Path`) — Destination for raw file copies (creates `raw_root/<folder.name>/`).

**Returns:** `list[Page]` — Pages for all readable files. Text files (`.md`, `.txt`, `.py`, `.json`, `.csv`, `.toml`, `.yaml`, `.yml`, `.rst`) are read directly. PDF files are extracted via pymupdf if installed. Content is truncated at 50,000 characters.

**Behavior:** Recursively walks the folder, validates each file with `validate_ingest_source()` (rejects external symlinks), copies to `raw_root`, reads content for supported formats. Files that fail to read are silently skipped.

**Example:**
```python
from helix_mini.atlas import ingest_folder

pages = ingest_folder(Path("./papers"), Path("/tmp/raw"))
print(f"Ingested {len(pages)} files")
```
