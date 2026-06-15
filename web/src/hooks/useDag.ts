import { useState, useCallback } from "react";
import { apiGet } from "@/lib/api";

interface DagData {
  nodes: {
    id: string;
    node_key: string;
    title: string;
    summary: string | null;
    scene_type: string;
    is_ending: boolean;
    is_hidden_ending: boolean;
    position_x: number;
    position_y: number;
    script_status: { has_script: boolean; version: number };
  }[];
  edges: {
    id: string;
    source_node_key: string;
    target_node_key: string;
    choice_label: string | null;
    choice_index: number;
  }[];
}

export function useDag(projectId: string) {
  const [dagData, setDagData] = useState<DagData | null>(null);
  const [loading, setLoading] = useState(false);

  const fetchDag = useCallback(async () => {
    try {
      setLoading(true);
      const data = await apiGet<DagData>(`get-dag?project_id=${projectId}`);
      setDagData(data);
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  return { dagData, loading, fetchDag };
}
