import { useState, useCallback } from "react";
import { apiGet, apiPost } from "@/lib/api";

interface Project {
  id: string;
  name: string;
  status: string;
  model_profile_id: string;
  steering_notes: string | null;
  created_at: string;
}

interface Outline {
  project: Project;
  story_summary: string | null;
  world_settings: unknown;
  characters: { id: string; name: string; profile_data: unknown }[];
  dag: {
    nodes: DagNode[];
    edges: DagEdge[];
  };
}

interface Predicate {
  key: string;
  cmp: string;
  value: unknown;
}

interface StateEffect {
  key: string;
  op: string;
  value: unknown;
}

interface DagNode {
  id: string;
  node_key: string;
  title: string;
  summary: string | null;
  scene_type: string;
  is_ending: boolean;
  is_hidden_ending: boolean;
  episode_number: number | null;
  episode_title: string | null;
  position_x: number;
  position_y: number;
  script_status?: { has_script: boolean; version: number };
  requires: Predicate[] | null;
  invariants: Predicate[] | null;
  computed_states: Record<string, unknown[]> | null;
}

interface DagEdge {
  id: string;
  source_node_key: string;
  target_node_key: string;
  choice_label: string | null;
  choice_index: number;
  effects: StateEffect[] | null;
  resolution: string[] | null;
}

export function useProject(projectId: string) {
  const [outline, setOutline] = useState<Outline | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchOutline = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiGet<Outline>(`get-outline?project_id=${projectId}`);
      setOutline(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  const startPipeline = useCallback(async () => {
    await apiPost("start-pipeline", { project_id: projectId });
  }, [projectId]);

  const startPhase1 = useCallback(async () => {
    await apiPost("start-phase1", { project_id: projectId });
  }, [projectId]);

  const approvePhase1 = useCallback(async () => {
    await apiPost("approve-phase1", { project_id: projectId });
  }, [projectId]);

  const startScriptGen = useCallback(async () => {
    await apiPost("start-script-gen", { project_id: projectId });
  }, [projectId]);

  const exportDeliverables = useCallback(async () => {
    return apiPost<{ status: string; job_id: string }>("export-deliverables", { project_id: projectId });
  }, [projectId]);

  return {
    outline,
    loading,
    error,
    fetchOutline,
    startPipeline,
    startPhase1,
    approvePhase1,
    startScriptGen,
    exportDeliverables,
  };
}

export type { Project, Outline, DagNode, DagEdge };
