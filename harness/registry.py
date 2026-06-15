"""§3.4, §3.7 — Registry operations."""

from .models import FactDecl, FactId, Graph, Node, Registry, Reject


def seed_registry(bible: dict) -> Registry:
    """§3.4 — Load the bible's seed fact list into a Registry.

    bible["facts"] is a list of dicts with keys: id, kind, gloss, initial, invariant.
    """
    registry: Registry = {}
    for f in bible.get("facts", []):
        fid = f["id"]
        registry[fid] = FactDecl(
            id=fid,
            kind=f.get("kind", "event"),
            gloss=f.get("gloss", ""),
            initial=f.get("initial", False),
            invariant=f.get("invariant", False),
        )
    return registry


def _collect_fact_ids(node: Node) -> set[FactId]:
    """Collect all FactIds referenced by a node."""
    ids: set[FactId] = set()
    for eff in node.produces:
        ids.add(eff.fact)
    for req in node.requires:
        ids.add(req.fact)
    for req in node.entry_invariants:
        ids.add(req.fact)
    for choice in node.choices:
        for req in choice.label_requires:
            ids.add(req.fact)
        for eff in choice.state_delta:
            ids.add(eff.fact)
    return ids


def register_facts(
    registry: Registry,
    subgraph: dict[str, Node],
    new_decls: list[FactDecl] | None = None,
    auto_declare: bool = False,
) -> str | None:
    """§3.7 — Register any new facts from the subgraph.

    Returns None on success, or a rejection reason string.
    auto_declare=True: undeclared facts with conventional prefixes are
    heuristically registered instead of rejecting the whole candidate —
    rejecting an otherwise-valid excursion over a missing declaration wastes
    a full generation.
    """
    # Collect all fact IDs from the subgraph
    all_referenced: set[FactId] = set()
    for node in subgraph.values():
        all_referenced |= _collect_fact_ids(node)

    # Build a lookup of new declarations
    new_decl_map: dict[FactId, FactDecl] = {}
    if new_decls:
        for d in new_decls:
            new_decl_map[d.id] = d

    # Check each referenced fact
    for fid in all_referenced:
        if fid in registry:
            continue  # already registered

        if fid in new_decl_map:
            decl = new_decl_map[fid]
            # Check for gloss collision (possible rename of existing fact)
            for existing in registry.values():
                if existing.gloss and decl.gloss and existing.gloss == decl.gloss:
                    return (
                        f"Fact '{fid}' has the same gloss as existing '{existing.id}' "
                        f"(\"{decl.gloss}\"). Reuse the existing fact ID instead."
                    )
            registry[fid] = decl
        elif auto_declare and fid.startswith(("player.", "char.", "world.")):
            if fid.startswith("player."):
                kind = "disposition"
            elif fid.startswith("char."):
                kind = "disposition"
            else:
                kind = "knowledge"
            registry[fid] = FactDecl(
                id=fid, kind=kind, gloss=f"(auto-declared from subgraph)",
                initial=False, invariant=False,
            )
        else:
            return (
                f"Fact '{fid}' is referenced but not registered and no declaration provided. "
                f"Declare it in the subgraph's new_facts list."
            )

    return None  # success
