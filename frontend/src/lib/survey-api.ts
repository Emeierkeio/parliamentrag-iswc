/**
 * Survey API client for ParliamentRAG evaluation system.
 */

import { config } from "@/config";
import type {
  SurveyResponse,
  SurveyResponseCreate,
  SurveyListResponse,
  
  PendingChatsResponse,
  SurveyStats,
  SimpleRatingResponse,
  SimpleRatingCreate,
} from "@/types/survey";
import { adminFetch } from "@/lib/admin-fetch";

const BASE_URL = `${config.api.baseUrl}/surveys`;

/**
 * Create a new survey response
 */
export async function createSurvey(survey: SurveyResponseCreate): Promise<SurveyResponse> {
  const response = await fetch(BASE_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(survey),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to create survey: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Update an existing survey
 */
export async function updateSurvey(
  chatId: string,
  survey: SurveyResponseCreate
): Promise<SurveyResponse> {
  const response = await fetch(`${BASE_URL}/${chatId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(survey),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to update survey: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get survey for a specific chat
 */
export async function getSurveyByChat(chatId: string): Promise<SurveyResponse | null> {
  const response = await fetch(`${BASE_URL}/${chatId}`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Failed to fetch survey: ${response.statusText}`);
  }
  return response.json();
}

/**
 * List all surveys with optional statistics
 */
export async function listSurveys(
  options: {
    includeStats?: boolean;
    limit?: number;
    offset?: number;
  } = {}
): Promise<SurveyListResponse> {
  const params = new URLSearchParams();
  if (options.includeStats !== undefined) {
    params.set("include_stats", String(options.includeStats));
  }
  if (options.limit !== undefined) {
    params.set("limit", String(options.limit));
  }
  if (options.offset !== undefined) {
    params.set("offset", String(options.offset));
  }

  const url = params.toString() ? `${BASE_URL}?${params}` : BASE_URL;
  const response = await adminFetch(url);

  if (!response.ok) {
    throw new Error(`Failed to list surveys: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Delete a survey
 */
export async function deleteSurvey(chatId: string): Promise<void> {
  const response = await adminFetch(`${BASE_URL}/${chatId}`, {
    method: "DELETE",
  });

  if (!response.ok) {
    throw new Error(`Failed to delete survey: ${response.statusText}`);
  }
}

/**
 * Get survey statistics summary
 */
export async function getSurveyStats(): Promise<SurveyStats> {
  const response = await adminFetch(`${BASE_URL}/stats/summary`);
  if (!response.ok) {
    throw new Error(`Failed to fetch survey stats: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get list of evaluated chat IDs, optionally filtered by evaluator
 */
export async function getEvaluatedChatIds(evaluatorId?: string): Promise<{ chat_ids: string[] }> {
  const params = evaluatorId ? `?evaluator_id=${encodeURIComponent(evaluatorId)}` : "";
  const response = await adminFetch(`${BASE_URL}/chats/evaluated${params}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch evaluated chat IDs: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get evaluation_set chats pending evaluation for this evaluator
 */
export async function getPendingChats(evaluatorId?: string): Promise<PendingChatsResponse> {
  const params = evaluatorId ? `?evaluator_id=${encodeURIComponent(evaluatorId)}` : "";
  const response = await adminFetch(`${BASE_URL}/chats/pending${params}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch pending chats: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Create a new simple Likert-scale rating
 */
export async function createSimpleRating(
  rating: SimpleRatingCreate
): Promise<SimpleRatingResponse> {
  const response = await fetch(`${BASE_URL}/simple`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(rating),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || `Failed to create simple rating: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get the evaluation set topics available for A/B testing
 */
export async function getEvaluationSetTopics(): Promise<{ topics: string[] }> {
  const response = await fetch(`${BASE_URL}/evaluation-set`);
  if (!response.ok) {
    throw new Error(`Failed to fetch evaluation set: ${response.statusText}`);
  }
  return response.json();
}
