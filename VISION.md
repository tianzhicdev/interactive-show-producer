# Vision

## Environment

- Operate this project as a production-only system for now.
- Avoid maintaining separate development deployment targets until the product needs that complexity.
- Production configuration, queues, storage, model selection, and deployment scripts should be the default path.

## Model Selection

- Respect the user's selected model profile throughout the pipeline.
- Do not silently downgrade or swap models for individual stages unless the user explicitly changes the project profile or a visible product setting.
- If a selected model is slow or fails, surface the failure and allow a deliberate retry or profile change rather than changing models implicitly.

## Story Bible First

- The raw story should be transformed into a detailed story bible before later generation stages rely on it.
- Chunking should preserve plot fidelity; the bible should be detailed enough that downstream generation does not miss important characters, motivations, relationships, turning points, or world rules.
- Characters, world settings, DAG structure, and scene scripts should be generated from the story bible as the primary source of truth.
- Scene scripts attached to DAG nodes should be recreations from the story bible plus the node context, not direct summaries of isolated raw chunks.

## Chunking

- Chunking is business logic, not just a technical split.
- Chunks should eventually include controlled overlap with neighboring chunks so boundary events, character entrances, and cause-effect transitions are not lost.
- The system should track chunk order, chunk completeness, and final bible coverage so users can trust that the entire source story was processed.

## Pipeline

- The current product should run continuously from upload through story bible, world settings, characters, DAG, and scene scripts.
- Separate phases can be reintroduced later as a product control, but the default flow should not require users to manually approve Phase 1 before Phase 2 starts.
- Progress reporting should show granular stage status so users can see exactly which step is queued, running, retrying, complete, or failed.
