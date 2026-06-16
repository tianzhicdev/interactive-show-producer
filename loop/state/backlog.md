# Curated backlog (human-editable)

Seed work items for the loop, highest-value first. The loop reads this each
iteration alongside the last eval's deficiencies. Remove items as they land.

## Deferred from the manual review (real, scoped)
- B16: `_try_extract_from_end` in llm.py should keep scanning earlier `}` on a
  JSONDecodeError instead of returning None (salvages dirty responses → fewer retries).
- R1: purge stale naming — prompts/judge still say `thin_content`; rename to
  `skeleton` for consistency (no behavior change).
- R4: D10 ENDING-reachability is O(V·E) (fresh BFS per node) — replace with one
  reverse-BFS from all ENDING nodes. Memoize `estimate_minutes` in budget.py.

## Conformance sweeps (AGENTS.md)
- Audit harness/*.py for any remaining hardcoded story content or fallback prose.
- Verify every machine-consumed LLM call goes through a JSON schema at the boundary.
- Check no `content + content` duplication or padding loops anywhere.

## Notes
- Keep items SMALL and independently verifiable. One fix per iteration.
- If an item needs a protected-file change, it goes to needs_human.md, not here.
