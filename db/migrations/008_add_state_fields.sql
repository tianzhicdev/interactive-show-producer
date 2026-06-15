-- Migration 008: Add state fields to dag_nodes and dag_edges
--
-- dag_nodes gets:
--   requires       — entry gate predicates (JSON array of {key, cmp, value})
--   invariants     — bottleneck canon predicates (JSON array of {key, cmp, value})
--   computed_states — per-variable possible values across all paths ({var_key: [val1, val2, ...]})
--
-- dag_edges gets:
--   effects        — state mutations (JSON array of {key, op, value})

ALTER TABLE dag_nodes ADD COLUMN requires jsonb;
ALTER TABLE dag_nodes ADD COLUMN invariants jsonb;
ALTER TABLE dag_nodes ADD COLUMN computed_states jsonb;

ALTER TABLE dag_edges ADD COLUMN effects jsonb;
