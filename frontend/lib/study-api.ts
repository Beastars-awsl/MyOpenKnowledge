import { API_BASE_URL } from "@/lib/api";

export type StudyKind = "flashcard" | "choice" | "short_answer";
export type StudyMode = "daily" | "weak" | "mistakes";
export const kindLabels: Record<StudyKind, string> = { flashcard: "闪记卡", choice: "单选题", short_answer: "简答题" };
export const ratingLabels = ["忘记", "困难", "记得", "轻松"];
export interface ModelSettings { model: string; provider: string; apiKey: string; baseUrl: string | null }
export interface StudySource {
  mode: "document" | "text" | "topic";
  document_id: string | null;
  title: string;
  chunk_index: number | null;
  excerpt: string;
}
export interface ItemContent {
  kind: StudyKind;
  knowledge_point: string;
  prompt: string;
  answer: string;
  explanation: string;
  options: string[];
}
export interface ItemDraft extends ItemContent { source: StudySource }
export interface StudyItem extends ItemDraft {
  id: string; deck_id: string; archived: boolean; version: number;
  due: string; review_count: number; source_available: boolean;
}
export interface StudyDeck { id: string; title: string; archived: boolean; created_at: string }
export interface Feedback {
  summary: string; omissions: string[]; misconceptions: string[];
  suggested_rating: number; unavailable: boolean;
}
export interface StudyAttempt {
  id: string; item_id: string; position: number; item_version: number;
  question: Pick<ItemContent, "kind" | "knowledge_point" | "prompt" | "options"> & {
    answer?: string | null; explanation?: string | null; source?: StudySource | null;
  };
  answer: string | null; feedback: Feedback | null; objective_correct: boolean | null;
  rating: number | null; reviewed_at: string | null; next_due: string | null;
  source_available: boolean; unavailable: boolean; intervals: Record<string, string>;
}
export interface StudySession {
  id: string; mode: StudyMode; created_at: string; completed_at: string | null;
  recap: string | null; attempts: StudyAttempt[];
}
export interface WeakPoint { knowledge_point: string; samples: number; weak_count: number; ratio: number }
export interface DailyCount {
  date: string; reviewed: number; recalled: number; choice_count: number;
  choice_correct: number; flashcard_count: number; flashcard_recalled: number;
}
export interface StudyStats {
  due: number; new: number; reviewed_today: number; weak_points: WeakPoint[];
  trend: DailyCount[]; upcoming: { date: string; count: number }[];
  sessions: { id: string; mode: StudyMode; created_at: string; completed_at: string | null; total: number; confirmed: number }[];
}
export interface GenerateInput extends ModelSettings {
  mode: StudySource["mode"]; document_id: string | null; text: string; focus: string;
  kinds: StudyKind[]; count: number; start_chunk: number; chunk_count: number; variant_item_id: string | null;
}
export interface StudyDocument { id: string; title: string; status: string }

export async function studyRequest<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api/study${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "输入内容不符合要求，请检查长度、题目选项和必填项");
  }
  return data as T;
}
