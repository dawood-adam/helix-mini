"""Tests for the sandbox module."""

from pathlib import Path

import pytest

from helix_mini.sandbox import (
    ALLOWED_SUBDIRS,
    MAX_PAGE_CONTENT_BYTES,
    MAX_WRITES_PER_BATCH,
    SandboxError,
    sanitize_atlas_writes,
    validate_content,
    validate_ingest_source,
    validate_path,
    validate_title,
)


class TestValidatePath:
    def test_valid_sources_path(self, tmp_path: Path):
        atlas_root = tmp_path / "atlas"
        atlas_root.mkdir()
        (atlas_root / "sources").mkdir()
        result = validate_path("sources/paper.md", atlas_root)
        assert result.is_relative_to(atlas_root.resolve())

    def test_valid_all_subdirs(self, tmp_path: Path):
        atlas_root = tmp_path / "atlas"
        atlas_root.mkdir()
        for subdir in ALLOWED_SUBDIRS:
            (atlas_root / subdir).mkdir(exist_ok=True)
            validate_path(f"{subdir}/test.md", atlas_root)

    def test_rejects_absolute_path(self, tmp_path: Path):
        with pytest.raises(SandboxError, match="Absolute path"):
            validate_path("/etc/passwd", tmp_path)

    def test_rejects_traversal(self, tmp_path: Path):
        with pytest.raises(SandboxError, match="traversal"):
            validate_path("sources/../../etc/passwd", tmp_path)

    def test_rejects_unknown_subdir(self, tmp_path: Path):
        with pytest.raises(SandboxError, match="must start with"):
            validate_path("malicious/evil.md", tmp_path)

    def test_rejects_root_level_file(self, tmp_path: Path):
        with pytest.raises(SandboxError, match="must start with"):
            validate_path("evil.md", tmp_path)

    def test_rejects_very_long_path(self, tmp_path: Path):
        long_path = "sources/" + "a" * 300 + ".md"
        with pytest.raises(SandboxError, match="too long"):
            validate_path(long_path, tmp_path)


class TestValidateTitle:
    def test_normal_title(self):
        assert validate_title("My Research Paper") == "My Research Paper"

    def test_strips_control_chars(self):
        assert validate_title("Title\x00With\x07Control") == "TitleWithControl"

    def test_truncates_long_title(self):
        long_title = "A" * 300
        result = validate_title(long_title)
        assert len(result) == 200

    def test_rejects_empty(self):
        with pytest.raises(SandboxError, match="Empty"):
            validate_title("  \x00  ")


class TestValidateContent:
    def test_normal_content(self):
        content = "This is normal content."
        assert validate_content(content) == content

    def test_truncates_oversized(self):
        huge = "x" * (MAX_PAGE_CONTENT_BYTES + 1000)
        result = validate_content(huge)
        assert "truncated by sandbox" in result
        assert len(result) < len(huge)


class TestSanitizeAtlasWrites:
    def test_valid_write(self, tmp_path: Path):
        atlas_root = tmp_path / "atlas"
        atlas_root.mkdir()
        (atlas_root / "sources").mkdir()
        raw = [{"path": "sources/p.md", "title": "T", "content": "C", "summary": "S"}]
        result = sanitize_atlas_writes(raw, atlas_root)
        assert len(result) == 1
        assert result[0].path == "sources/p.md"

    def test_skips_invalid_path(self, tmp_path: Path):
        raw = [{"path": "/etc/evil", "title": "T", "content": "C", "summary": "S"}]
        result = sanitize_atlas_writes(raw, tmp_path)
        assert result == []

    def test_skips_missing_fields(self, tmp_path: Path):
        raw = [{"path": "sources/p.md", "title": "T"}]
        result = sanitize_atlas_writes(raw, tmp_path)
        assert result == []

    def test_batch_limit(self, tmp_path: Path):
        atlas_root = tmp_path / "atlas"
        atlas_root.mkdir()
        (atlas_root / "sources").mkdir()
        raw = [
            {"path": f"sources/p{i}.md", "title": "T", "content": "C", "summary": "S"}
            for i in range(MAX_WRITES_PER_BATCH + 10)
        ]
        result = sanitize_atlas_writes(raw, atlas_root)
        assert len(result) <= MAX_WRITES_PER_BATCH

    def test_skips_disallowed_subdir(self, tmp_path: Path):
        raw = [{"path": "hacked/evil.md", "title": "T", "content": "C", "summary": "S"}]
        result = sanitize_atlas_writes(raw, tmp_path)
        assert result == []


class TestValidateIngestSource:
    def test_regular_file_ok(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("content")
        assert validate_ingest_source(f, tmp_path) is True

    def test_symlink_inside_folder_ok(self, tmp_path: Path):
        target = tmp_path / "real.md"
        target.write_text("content")
        link = tmp_path / "link.md"
        link.symlink_to(target)
        assert validate_ingest_source(link, tmp_path) is True

    def test_symlink_outside_folder_blocked(self, tmp_path: Path):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".md") as tf:
            link = tmp_path / "evil.md"
            link.symlink_to(tf.name)
            assert validate_ingest_source(link, tmp_path) is False
