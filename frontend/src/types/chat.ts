/**
 * Tipi per il sistema di chat
 */
import type { CompassData } from "@/components/chat/CompassCard";

export type MessageRole = "user" | "assistant" | "system";

export type MessageStatus = "sending" | "streaming" | "complete" | "error";

export interface Citation {
  chunk_id: string;
  deputy_first_name: string;
  deputy_last_name: string;
  group: string;
  /** Componente del Gruppo Misto alla data del discorso (es. "+EUROPA - STATI UNITI D'EUROPA") */
  misto_component?: string;
  coalition: string;
  text?: string;
  quote_text?: string;
  full_text?: string;
  date: string;
  similarity: number;
  debate?: string;
  debate_id?: string;
  intervention_id?: string;
  /** Pagina ufficiale dell'intervento (Senato); assente per la Camera */
  url?: string | null;
  camera_profile_url?: string;
  photo?: string;
  translated_text?: string;
  translated_full_text?: string;
  is_translated?: boolean;
  [key: string]: any;
}

export interface Expert {
  id: string;
  first_name: string;
  last_name: string;
  group: string;
  photo?: string;
  camera_profile_url?: string;
  profession?: string;
  education?: string;
  committee?: string;
  committees?: string[];
  institutional_role?: string;
  coalition: string;
  authority_score: number;
  score_breakdown?: {
    speeches: number;
    acts: number;
    committee: number;
    profession: number;
    education: number;
    role: number;
  };
  relevant_speeches_count: number;
  acts_detail?: Array<{
    title: string;
    eurovoc: string;
    is_primary: boolean;
    similarity: number;
  }>;
}

export interface HQVariant {
  index: number;
  text: string;
  score: number;
  is_best: boolean;
  temperature: number;
}

export interface HQMetadata {
  judge_reason: string;
  variants: HQVariant[];
}

export interface SpeakerDetail {
  speaker_id: string;
  speaker_name: string;
  party: string;
  coalition: string;
  intervention_count: number;
  camera_profile_url?: string;
  photo?: string;
  profession?: string;
  education?: string;
  committee?: string;
  institutional_role?: string;
}

export interface InterventionDetail {
  speech_id: string;
  speaker_id?: string;
  speaker_name: string;
  party: string;
  coalition: string;
  date: string;
  debate_title: string;
  session_number: number;
  /** Pagina ufficiale dell'intervento (Senato); assente per la Camera */
  url?: string | null;
  photo?: string;
}

export interface SessionDetail {
  session_number: number;
  chamber?: string;
  /** Pagina della seduta su senato.it; assente per la Camera */
  url?: string | null;
  date: string;
  debate_title: string;
}

export interface TopicStatistics {
  intervention_count: number;
  speaker_count: number;
  first_date: string;
  last_date: string;
  speakers_detail: SpeakerDetail[];
  interventions_detail: InterventionDetail[];
  sessions_detail: SessionDetail[];
}

export interface GateInfo {
  title: string;
  body: string;
  suggestions_label: string;
  suggestions: string[];
}

/** Stadio della pipeline nel trace "dietro le quinte" */
export interface TraceStage {
  key: string;
  ms: number | null;
  /** Offset reale di inizio dallo start della pipeline (ms) */
  at?: number | null;
  info?: Record<string, string | number | null | undefined>;
  model?: string;
  children?: TraceStage[];
}

/** Anteprima di un messaggio inviato all'LLM */
export interface LlmMessagePreview {
  role: string;
  chars: number;
  preview: string;
}

/** Singola chiamata LLM registrata dal backend */
export interface LlmCall {
  endpoint: "chat" | "embeddings";
  model?: string | null;
  /** Fase taggata dal backend (vince sull'inferenza per offset temporale) */
  stage?: string;
  t_offset_ms: number;
  duration_ms: number;
  temperature?: number | null;
  messages?: LlmMessagePreview[];
  tokens?: { prompt?: number | null; completion?: number | null; total?: number | null };
  response_chars?: number;
  response_preview?: string;
  finish_reason?: string | null;
  inputs?: number;
  input_preview?: string;
  cost_usd?: number | null;
  error?: string;
}

/** Evidenza del pool retrieval con le componenti di score del merge */
export interface RetrievalSampleItem {
  id: string;
  speaker?: string | null;
  party?: string | null;
  coalition?: string | null;
  similarity?: number | null;
  authority?: number | null;
  citability?: number | null;
  date?: string | null;
}

/** Stato di una citazione nel CitationRegistry */
export interface CitationLedgerEntry {
  evidence_id: string;
  status: string;
  speaker?: string | null;
  party?: string | null;
  section_party?: string | null;
  coherence_score?: number | null;
  error?: string | null;
}

/** Report integrità citazioni della pipeline */
export interface CitationsReport {
  expected?: number | null;
  resolved?: number | null;
  failed?: number | null;
  orphaned?: number | null;
  success_rate?: number | null;
  coherence?: {
    all_coherent?: boolean;
    coherent_count?: number;
    incoherent_count?: number;
    average_score?: number;
  } | null;
  unsupported_claims?: string[];
  ledger?: CitationLedgerEntry[];
}

/** Trace della pipeline: durate, chiamate LLM e registro citazioni */
export interface TraceData {
  total_ms: number;
  rewritten_query?: string | null;
  stages: TraceStage[];
  llm?: {
    calls: number;
    chat_calls: number;
    embedding_calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
    cost_usd?: number;
  };
  llm_calls?: LlmCall[];
  citations_report?: CitationsReport;
  retrieval_sample?: RetrievalSampleItem[];
  party_coverage?: Record<string, number>;
  compass_meta?: { method?: string | null; variance?: number | null; stable?: boolean | null } | null;
  domain?: { in_domain?: boolean } | null;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  timestamp: Date;
  status: MessageStatus;
  // Metadati opzionali per le risposte dell'assistente
  citations?: Citation[];
  experts?: Expert[];
  commissioni?: Array<{ nome: string; score: number; matched_keywords: string[]; categories: string[] }>;
  compass?: CompassData;
  balanceMetrics?: BalanceMetrics;
  hqMetadata?: HQMetadata;
  topicStats?: TopicStatistics;
  trace?: TraceData;
  // Relevance gate (tema non trovato): sostituisce il contenuto markdown
  gate?: GateInfo;
  // Replay dall'archivio risposte: la stessa domanda era già stata
  // analizzata e il backend ha rimandato gli eventi salvati; il campo
  // spiega all'utente perché la risposta è arrivata all'istante.
  cached?: { generatedAt?: string | null };
  // History ID for sharing
  chatId?: string;
}

export interface BalanceMetrics {
  maggioranzaPercentage: number;
  opposizionePercentage: number;
  biasScore: number; // -1 = tutto opposizione, 0 = bilanciato, 1 = tutto maggioranza
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  createdAt: Date;
  updatedAt: Date;
}

// Progress tracking
export interface StepResult {
  step: number;
  label: string;
  result?: string;
  details?: any;
}

export interface ProcessingProgress {
  currentStep: number;
  totalSteps: number;
  stepLabel: string;
  stepDescription: string;
  isComplete: boolean;
  stepResults: StepResult[];
  isWaiting?: boolean;
  waitingMessage?: string;
  queuePosition?: number;   // position in queue (1 = next)
  aheadCount?: number;      // number of people ahead of this user (= position - 1)
  activeCount?: number;     // pipelines currently running
  elapsedSeconds?: number;  // seconds spent waiting so far
}
