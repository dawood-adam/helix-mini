"""Tests for Atlas — the LLM wiki."""

from __future__ import annotations

from pathlib import Path

from helix_mini.atlas import Atlas, Page, PageWrite, ingest_folder


class TestAtlasStructure:
    def test_creates_directories(self, tmp_path: Path):
        atlas = Atlas(tmp_path / "atlas")
        assert (tmp_path / "atlas" / "sources").is_dir()
        assert (tmp_path / "atlas" / "concepts").is_dir()
        assert (tmp_path / "atlas" / "entities").is_dir()
        assert (tmp_path / "atlas" / "projects").is_dir()
        assert (tmp_path / "atlas" / "index.md").exists()
        assert (tmp_path / "atlas" / "log.md").exists()

    def test_idempotent_init(self, tmp_path: Path):
        root = tmp_path / "atlas"
        atlas1 = Atlas(root)
        atlas1.write(
            [PageWrite("sources/test.md", "Test", "Content", "A test page")],
            "test write",
        )
        atlas2 = Atlas(root)
        assert "Test" in atlas2.read_all_summaries()


class TestAtlasReadWrite:
    def test_write_and_read(self, tmp_atlas: Atlas):
        tmp_atlas.write(
            [PageWrite("concepts/ml.md", "Machine Learning", "ML is...", "Overview of ML")],
            "test | write concept",
        )

        # Check file was created
        assert (tmp_atlas.root / "concepts" / "ml.md").exists()
        content = (tmp_atlas.root / "concepts" / "ml.md").read_text()
        assert "Machine Learning" in content

        # Check index was updated
        index = tmp_atlas.read_all_summaries()
        assert "Machine Learning" in index
        assert "concepts/ml.md" in index

        # Check log was updated
        log = (tmp_atlas.root / "log.md").read_text()
        assert "test | write concept" in log

    def test_read_by_query(self, tmp_atlas: Atlas):
        tmp_atlas.write(
            [
                PageWrite("concepts/cardiac.md", "Cardiac Modeling", "Heart sim...", "Cardiac sim methods"),
                PageWrite("concepts/neural.md", "Neural Networks", "Deep learning...", "Neural net overview"),
            ],
            "test write",
        )

        results = tmp_atlas.read("cardiac")
        assert len(results) == 1
        assert results[0].title == "Cardiac Modeling"

        results = tmp_atlas.read("neural")
        assert len(results) == 1
        assert results[0].title == "Neural Networks"

    def test_read_no_match(self, tmp_atlas: Atlas):
        results = tmp_atlas.read("nonexistent topic xyz")
        assert results == []

    def test_batch_write(self, tmp_atlas: Atlas):
        writes = [
            PageWrite("sources/a.md", "Source A", "Content A", "Summary A"),
            PageWrite("sources/b.md", "Source B", "Content B", "Summary B"),
            PageWrite("concepts/c.md", "Concept C", "Content C", "Summary C"),
        ]
        tmp_atlas.write(writes, "batch test")

        index = tmp_atlas.read_all_summaries()
        assert "Source A" in index
        assert "Source B" in index
        assert "Concept C" in index

    def test_update_existing_page(self, tmp_atlas: Atlas):
        tmp_atlas.write(
            [PageWrite("concepts/ml.md", "ML", "Version 1", "First version")],
            "v1",
        )
        tmp_atlas.write(
            [PageWrite("concepts/ml.md", "ML Updated", "Version 2", "Updated version")],
            "v2",
        )

        content = (tmp_atlas.root / "concepts" / "ml.md").read_text()
        assert "Version 2" in content
        assert "Version 1" not in content

        # Index should have updated entry, not duplicate
        index = tmp_atlas.read_all_summaries()
        assert index.count("concepts/ml.md") == 1


class TestAtlasPathTraversal:
    def test_write_blocks_absolute_path(self, tmp_atlas: Atlas):
        import pytest

        with pytest.raises(ValueError, match="Path traversal blocked"):
            tmp_atlas.write(
                [PageWrite("/etc/malicious.md", "Evil", "Content", "Hack")],
                "traversal attempt",
            )

    def test_write_blocks_relative_traversal(self, tmp_atlas: Atlas):
        import pytest

        with pytest.raises(ValueError, match="Path traversal blocked"):
            tmp_atlas.write(
                [PageWrite("../../.bashrc", "Evil", "Content", "Hack")],
                "traversal attempt",
            )

    def test_read_skips_traversal_entries(self, tmp_atlas: Atlas):
        # Manually poison index.md with a traversal path
        index_path = tmp_atlas.root / "index.md"
        index_path.write_text(
            "# Atlas Index\n"
            "- [Evil](../../etc/passwd) — system file\n"
        )
        results = tmp_atlas.read("evil")
        assert results == []

    def test_valid_paths_still_work(self, tmp_atlas: Atlas):
        tmp_atlas.write(
            [PageWrite("sources/legit.md", "Legit", "Good content", "A valid page")],
            "valid write",
        )
        assert (tmp_atlas.root / "sources" / "legit.md").exists()
        results = tmp_atlas.read("legit")
        assert len(results) == 1


class TestAtlasIngest:
    def test_ingest_folder(self, tmp_atlas: Atlas, sample_folder: Path, tmp_path: Path):
        raw_root = tmp_path / "raw"
        pages = ingest_folder(sample_folder, raw_root)

        assert len(pages) == 3  # paper1.md, paper2.txt, data.json
        titles = {p.title for p in pages}
        assert "paper1" in titles
        assert "paper2" in titles

        # Check raw copies
        assert (raw_root / "test-project" / "paper1.md").exists()

    def test_ingest_empty_folder(self, tmp_atlas: Atlas, tmp_path: Path):
        empty = tmp_path / "empty"
        empty.mkdir()
        raw_root = tmp_path / "raw"
        pages = ingest_folder(empty, raw_root)
        assert pages == []
