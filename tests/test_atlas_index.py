"""3c: SQLite edge index — k-hop traversal over the frontmatter link graph."""

from __future__ import annotations

from helix.core.atlas import Atlas, PageWrite
from helix.core.atlas_index import build, neighbors


def _graph(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([
        PageWrite("concepts/a.md", "A", "x", "s",
                  links={"related_to": ["atlas:concepts:b"],
                         "contradicts": ["doi:10.1/x"]}),
        PageWrite("concepts/b.md", "B", "x", "s",
                  links={"cites": ["atlas:concepts:c"]}),
        PageWrite("concepts/c.md", "C", "x", "s"),
    ], "seed")
    return tmp_path / "atlas"


def test_build_has_nodes_and_edges(tmp_path):
    con = build(_graph(tmp_path))
    assert con.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
    kinds = {r[0] for r in con.execute("SELECT kind FROM edges")}
    assert kinds == {"related_to", "contradicts", "cites"}
    con.close()


def test_one_hop_by_id_and_by_path(tmp_path):
    root = _graph(tmp_path)
    by_id = neighbors(root, "atlas:concepts:a", 1)
    ids = {n["id"]: n for n in by_id}
    assert set(ids) == {"atlas:concepts:b", "doi:10.1/x"}
    assert ids["atlas:concepts:b"]["title"] == "B"
    assert ids["doi:10.1/x"]["title"] == "(no page)"   # edge target, no file
    # path resolves to the same start node
    assert {n["id"] for n in neighbors(root, "concepts/a.md", 1)} == set(ids)


def test_two_hop_and_undirected(tmp_path):
    root = _graph(tmp_path)
    two = {n["id"]: n["hops"] for n in neighbors(root, "atlas:concepts:a", 2)}
    assert two["atlas:concepts:c"] == 2          # a→b→c
    # undirected: c reaches b backward (b cites c)
    assert {n["id"] for n in neighbors(root, "atlas:concepts:c", 1)} == {
        "atlas:concepts:b"}


def test_isolated_page_has_no_neighbours(tmp_path):
    a = Atlas(tmp_path / "atlas")
    a.write([PageWrite("concepts/lone.md", "Lone", "x", "s")], "seed")
    assert neighbors(tmp_path / "atlas", "atlas:concepts:lone", 2) == []
