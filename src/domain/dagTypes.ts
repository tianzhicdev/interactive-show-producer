/** DAG node as produced by the LLM skeleton generator */
export interface DagNodeSkeleton {
  node_key: string; // e.g. "EP01-C1", "EP02-C3"
  title: string;
  summary: string;
  scene_type: "normal" | "choice" | "ending" | "hidden_ending"; // "normal" deprecated, prefer "choice"
  is_ending: boolean;
  is_hidden_ending: boolean;
  episode_number?: number;
  episode_title?: string;
}

/** DAG edge as produced by the LLM skeleton generator */
export interface DagEdgeSkeleton {
  source_node_key: string;
  target_node_key: string;
  choice_label?: string;
  choice_index: number;
}

/** Full DAG skeleton from LLM */
export interface DagSkeleton {
  nodes: DagNodeSkeleton[];
  edges: DagEdgeSkeleton[];
}

/** Character profile as stored in characters.profile_data */
export interface CharacterProfile {
  personality: string;
  appearance: string;
  abilities: string;
  goals: string;
  relationships: string;
  backstory?: string;
}

/** World settings stored in world_settings.setting_data */
export interface WorldSettings {
  era: string;
  location: string;
  rules: string;
  tone: string;
  themes: string[];
  power_system?: string;
  factions?: string;
}

/** Scene script formatting markers for interactive drama */
export const INTERACTIVE_DRAMA_MARKERS = {
  DIALOGUE: "：",
  ACTION: "▲",
  INNER_MONOLOGUE: "os",
  SUBTITLE: "字幕",
  INTERACTION: "【互动】",
  CHOICE_START: "【选项开始】",
  CHOICE_END: "【选项结束】",
  CHOICE_OPTION: "选项",
} as const;
