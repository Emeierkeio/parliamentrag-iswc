/**
 * Evaluation API client for ParliamentRAG scientific assessment.
 */

import { config } from "@/config";
import type { EvaluationDashboardData, AutomatedMetrics } from "@/types/evaluation";
import { adminFetch } from "@/lib/admin-fetch";

const BASE_URL = `${config.api.baseUrl}/evaluation`;

/**
 * Get full dashboard data (automated + human metrics)
 */
export async function getDashboardData(): Promise<EvaluationDashboardData> {
  const response = await adminFetch(`${BASE_URL}/dashboard`);
  if (!response.ok) {
    throw new Error(`Failed to fetch dashboard data: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Get automated metrics for a specific chat
 */
export async function getChatMetrics(chatId: string): Promise<AutomatedMetrics> {
  const response = await adminFetch(`${BASE_URL}/metrics/${chatId}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch chat metrics: ${response.statusText}`);
  }
  return response.json();
}

/**
 * Download the CSV export (admin key required, so no plain link)
 */
export async function downloadExportCsv(): Promise<void> {
  const response = await adminFetch(`${BASE_URL}/export/csv`);
  if (!response.ok) {
    throw new Error(`Failed to export CSV: ${response.statusText}`);
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] || "evaluation.csv";
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
