import { z } from "zod";

// --- Request Schemas ---

const requiredValueSchema: z.ZodType<unknown> = z.any();

const predicateSchema = z.object({
  key: z.string(),
  cmp: z.enum(["eq", "ne", "gt", "gte", "lt", "lte"]),
  value: requiredValueSchema,
});

const stateEffectSchema = z.object({
  key: z.string(),
  op: z.enum(["set", "add"]),
  value: requiredValueSchema,
});

export const createProjectSchema = z.object({
  name: z.string().min(1).max(200),
  model_profile_id: z.enum(["default", "premium", "budget"]).optional(),
  steering_notes: z.string().optional(),
  target_duration_minutes: z.number().int().min(1).max(600).optional(),
  target_choice_count: z.number().int().min(1).max(100).optional(),
});

export const updateOutlineSchema = z.object({
  project_id: z.string().uuid(),
  world_settings: z.unknown().optional(),
  characters: z
    .array(
      z.object({
        name: z.string(),
        profile_data: z.unknown(),
      })
    )
    .optional(),
  dag_nodes: z
    .array(
      z.object({
        node_key: z.string(),
        title: z.string(),
        summary: z.string().optional(),
        scene_type: z.enum(["normal", "choice", "ending", "hidden_ending"]).optional(),
        is_ending: z.boolean().optional(),
        is_hidden_ending: z.boolean().optional(),
        position_x: z.number().optional(),
        position_y: z.number().optional(),
        requires: z.array(predicateSchema).nullable().optional(),
        invariants: z.array(predicateSchema).nullable().optional(),
        computed_states: z.record(z.array(z.any())).nullable().optional(),
      })
    )
    .optional(),
  dag_edges: z
    .array(
      z.object({
        source_node_key: z.string(),
        target_node_key: z.string(),
        choice_label: z.string().optional(),
        choice_index: z.number().optional(),
        effects: z.array(stateEffectSchema).nullable().optional(),
        resolution: z.array(z.string()).nullable().optional(),
      })
    )
    .optional(),
});

export const regenerateSceneSchema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
  steering_notes: z.string().optional(),
});

export const regenerateBranchSchema = z.object({
  project_id: z.string().uuid(),
  root_node_key: z.string(),
  steering_notes: z.string().optional(),
});

export const regenerateNodesSchema = z.object({
  project_id: z.string().uuid(),
  node_keys: z.array(z.string()).min(1),
  steering_notes: z.string().optional(),
});

export const projectIdSchema = z.object({
  project_id: z.string().uuid(),
});

export const sceneQuerySchema = z.object({
  project_id: z.string().uuid(),
  node_key: z.string(),
});
