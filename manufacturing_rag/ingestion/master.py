"""
Step 1 — load master data (spec 6.1, 6.6).  STATUS: IMPLEMENTED.

`machines.json` is THE entity master (machine <-> codename <-> line <-> program).
Loaded FIRST, it is the resolution key everything else depends on: a missing
alias here silently zeroes recall on that entity, so this step is deterministic
and verified.

Returns the seed graph (Entities + Edges, spec Section 4) and the alias->ID map
used by `resolve.py`. Supplier-master aliases are merged in by resolve.py later.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import Entity, Edge


def load_master(machines_json_path: str | Path):
    """Return (alias_map, entities, edges).

    alias_map: lowercased alias/name -> canonical_id (machine/line/program).
    """
    data = json.loads(Path(machines_json_path).read_text(encoding="utf-8"))
    alias_map: dict[str, str] = {}
    entities: dict[str, Entity] = {}
    edges: list[Edge] = []

    def ent(cid, etype, aliases=(), attrs=None):
        if cid not in entities:
            entities[cid] = Entity(canonical_id=cid, type=etype,
                                   aliases=[], attrs=attrs or {},
                                   source_links=["machines.json"])
        for a in (cid, *aliases):
            if a:
                alias_map[str(a).lower()] = cid
                if a != cid and a not in entities[cid].aliases:
                    entities[cid].aliases.append(a)

    for m in data.get("machines", []):
        mid = m["id"]
        line_id = m.get("line_codename") or m.get("line")
        prog = m.get("program")
        ent(mid, "machine", aliases=[m.get("codename")],
            attrs={"machine_type": m.get("type"), "line": line_id})
        if line_id:
            ent(line_id, "line", aliases=[m.get("line")], attrs={})
            edges.append(Edge(src=mid, rel="ON_LINE", dst=line_id,
                              source_doc_id="machines.json"))
        if prog:
            ent(prog, "program", attrs={})
            if line_id:
                edges.append(Edge(src=line_id, rel="RUNS_PROGRAM", dst=prog,
                                  source_doc_id="machines.json"))
    return alias_map, list(entities.values()), edges


if __name__ == "__main__":  # quick smoke test
    import sys
    from .. import REPO_ROOT
    p = sys.argv[1] if len(sys.argv) > 1 else str(REPO_ROOT / "raw" / "mes" / "machines.json")
    am, ents, eds = load_master(p)
    print(f"aliases={len(am)} entities={len(ents)} edges={len(eds)}")
    for k, v in sorted(am.items()):
        print(f"  {k:14s} -> {v}")
