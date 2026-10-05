/**
 * TypeScript interfaces for the Parliamentary Timeline feature.
 * These mirror the backend Pydantic models in backend/app/models/timeline.py
 */

export interface DebateSummary {
  id: string;
  title: string;
  speech_count: number;
}

export interface TimelineSession {
  id: string;
  date: string;           // ISO date "2026-04-07"
  chamber: string;        // "camera" | "senato"
  number: number;
  recap: string | null;
  debate_count: number;
  vote_count: number;
  speech_count: number;
  debates: DebateSummary[];
}

export interface TimelineResponse {
  sessions: TimelineSession[];
  next_cursor: string | null;
  has_more: boolean;
}

export interface PhaseInfo {
  id: string;
  title: string;
  phase_type: string | null;
  speech_count: number;
}

export interface VoteInfo {
  id: string;
  number: number;
  subject: string | null;
  description: string | null;
  final_vote: boolean;
  outcome: string | null;
  in_favor: number | null;
  against: number | null;
  abstained: number | null;
}

export interface TopicVote extends VoteInfo {
  date: string | null;
  session_number: number | null;
  act_title: string | null;
  relation?: "act" | "title" | "session";
}

export interface VoteParticipant {
  id: string;
  first_name: string;
  last_name: string;
  party: string | null;
  outcome: string; // "favor" | "against" | "abstain" | "absent"
  seat?: number | null;
}

export interface VotePartyBreakdown {
  party: string;
  favor: number;
  against: number;
  abstain: number;
  absent: number;
}

export interface VoteActRef {
  title: string | null;
  url: string | null;
  text_url: string | null;
}

export interface VoteActTextResponse {
  paragraphs: string[];
  source_url: string;
}

export interface VoteDetailResponse {
  id: string;
  number: number;
  subject: string | null;
  description: string | null;
  acts: VoteActRef[];
  session_annex_url: string | null;
  secret_vote: boolean;
  outcome: string | null;
  vote_type: string | null;
  in_favor: number | null;
  against: number | null;
  abstained: number | null;
  present: number | null;
  voters: number | null;
  majority: number | null;
  on_mission: number | null;
  breakdown: VotePartyBreakdown[];
  participants: VoteParticipant[];
}

export interface ActInfo {
  id: string;
  title: string | null;
  type: string | null;
}

export interface SpeakerInfo {
  id: string;
  first_name: string;
  last_name: string;
  party: string | null;
  speaking_role: string | null;
  is_government_member: boolean;
  speech_count: number;
  phases: string[];
}

export interface InterventionInfo {
  speech_id: string;
  speaker_id: string;
  first_name: string;
  last_name: string;
  party: string | null;
  speaking_role: string | null;
  is_government_member: boolean;
  phase_title: string | null;
}

export interface DebateDetailResponse {
  id: string;
  title: string;
  recap: string | null;
  phases: PhaseInfo[];
  speakers: SpeakerInfo[];
  interventions: InterventionInfo[];
  votes: VoteInfo[];
  acts: ActInfo[];
}

export interface SpeechText {
  id: string;
  text: string;
  phase_title: string | null;
}

export interface SpeakerSummaryResponse {
  summary: string | null;
  speech_count: number;
  phases: string[];
  speeches: SpeechText[];
}

export interface TimelineFilters {
  chamber: string;    // "both" | "camera" | "senato"
  search: string;
  fromDate: string;   // ISO date or empty
  toDate: string;     // ISO date or empty
}
