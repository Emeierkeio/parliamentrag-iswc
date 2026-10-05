import { config } from "@/config";
import { adminFetch } from "@/lib/admin-fetch";

// Config API — maps to GET/PUT /api/config
export interface SystemConfig {
  retrieval: {
    dense_top_k: number;
    dense_similarity_threshold: number;
    graph_lexical_min_match: number;
    graph_semantic_threshold: number;
    graph_chunk_similarity_threshold: number;
    graph_max_acts_per_query: number;
    merger_weights: Record<string, number>;
  };
  authority: {
    weights: Record<string, number>;
    time_decay_acts_half_life: number;
    time_decay_speeches_half_life: number;
    acts_relevance_threshold: number;
    interventions_relevance_threshold: number;
    max_component_contribution: number;
  };
  generation: {
    models: Record<string, string>;
    position_brief: {
      enabled: boolean;
      max_chunks: number;
      chars_per_chunk: number;
      context_chars: number;
    };
    no_evidence_message: string;
  };
  query_rewriting: {
    enabled: boolean;
    model: string;
    max_query_words: number;
  };
}

function mapRawToConfig(raw: any): SystemConfig {
  return {
    retrieval: {
      dense_top_k: raw.retrieval.dense_top_k,
      dense_similarity_threshold: raw.retrieval.dense_similarity_threshold,
      graph_lexical_min_match: raw.retrieval.graph_lexical_min_match,
      graph_semantic_threshold: raw.retrieval.graph_semantic_threshold,
      graph_chunk_similarity_threshold: raw.retrieval.graph_chunk_similarity_threshold ?? 0.65,
      graph_max_acts_per_query: raw.retrieval.graph_max_acts_per_query ?? 100,
      merger_weights: raw.retrieval.merger_weights,
    },
    authority: {
      weights: raw.authority.weights,
      time_decay_acts_half_life: raw.authority.time_decay_acts_half_life,
      time_decay_speeches_half_life: raw.authority.time_decay_speeches_half_life,
      acts_relevance_threshold: raw.authority.acts_relevance_threshold ?? 0.25,
      interventions_relevance_threshold: raw.authority.interventions_relevance_threshold ?? 0.25,
      max_component_contribution: raw.authority.max_component_contribution,
    },
    generation: {
      models: raw.generation.models,
      position_brief: raw.generation.position_brief,
      no_evidence_message: raw.generation.no_evidence_message,
    },
    query_rewriting: raw.query_rewriting ?? { enabled: true, model: "gpt-4o-mini", max_query_words: 5 },
  };
}

export async function getConfig(): Promise<SystemConfig> {
  const response = await fetch(`${config.api.baseUrl}/config`);
  if (!response.ok) {
    throw new Error(`Errore nel caricamento config: ${response.statusText}`);
  }
  return mapRawToConfig(await response.json());
}

export interface ConfigUpdate {
  retrieval?: Partial<SystemConfig["retrieval"]>;
  authority?: Partial<SystemConfig["authority"]>;
  generation?: Partial<SystemConfig["generation"]>;
  query_rewriting?: Partial<SystemConfig["query_rewriting"]>;
}

export async function reloadConfig(): Promise<SystemConfig> {
  const response = await adminFetch(`${config.api.baseUrl}/config/reload`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Errore nel reload config: ${response.statusText}`);
  }
  return mapRawToConfig(await response.json());
}

export async function updateConfig(update: ConfigUpdate): Promise<SystemConfig> {
  const response = await adminFetch(`${config.api.baseUrl}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(update),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Errore nel salvataggio: ${text}`);
  }
  return mapRawToConfig(await response.json());
}
