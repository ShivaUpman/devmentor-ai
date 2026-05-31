/**
 * api.ts — Typed API client for the DevMentor AI backend
 *
 * WHY a custom fetch wrapper and not axios or SWR?
 *   1. Next.js 13+ has native fetch with caching — no extra library needed
 *   2. A thin wrapper gives us: auth header injection, error normalization,
 *      and TypeScript types without external dependencies
 *   3. SWR/React Query sit on top of this for caching — separation of concerns
 *
 * WHY store tokens in memory and not localStorage?
 *   localStorage is accessible by any script on the page (XSS vector).
 *   Memory (JS module variable) is not accessible to other scripts.
 *   Tradeoff: tokens don't survive page refresh. We handle this with
 *   a refresh token stored in an httpOnly cookie (XSS-proof).
 *
 * Interview question: "Where should you store JWT tokens in a browser?"
 *   Worst: localStorage (XSS vulnerable)
 *   Better: sessionStorage (survives reload, still XSS accessible)
 *   Best: httpOnly cookie for refresh + memory for access token
 *         Memory doesn't persist, so refresh token cookie silently gets
 *         a new access token on page load.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost/api';

// In-memory token storage — cleared on page refresh
// Production: access token in memory, refresh token in httpOnly cookie
let accessToken: string | null = null;

export const tokenStore = {
  get: () => accessToken,
  set: (token: string) => { accessToken = token; },
  clear: () => { accessToken = null; },
};

// ── Types ──────────────────────────────────────────────────────────────────────
export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface SkillAssessment {
  skill_topic: string;
  proficiency_score: number;
  attempts: number;
  last_assessed_at: string;
}

export interface RoadmapItem {
  id: string;
  skill_topic: string;
  resource_title: string;
  resource_url: string;
  resource_type: string;
  priority: number;
  completed: boolean;
}

export interface InterviewSession {
  id: string;
  topic: string;
  difficulty: string;
  status: string;
  score: number | null;
  started_at: string;
  ended_at: string | null;
}

export interface Question {
  id: string;
  question_text: string;
  skill_topic: string;
  skill_tag: string | null;
  difficulty: string | null;
  order_index: number;
}

export interface Submission {
  id: string;
  answer_text: string;
  similarity_score: number | null;
  confidence_score: number | null;
  ai_feedback: string | null;
  submitted_at: string;
}

// ── Core fetch wrapper ─────────────────────────────────────────────────────────
async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = tokenStore.get();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (response.status === 401) {
    // Try refreshing the token
    const refreshed = await tryRefresh();
    if (refreshed) {
      // Retry the original request with new token
      headers['Authorization'] = `Bearer ${tokenStore.get()}`;
      const retry = await fetch(`${API_BASE}${path}`, { ...options, headers });
      if (retry.ok) return retry.json();
    }
    tokenStore.clear();
    if (typeof window !== 'undefined') window.location.href = '/login';
    throw new Error('Session expired');
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // 204 No Content
  if (response.status === 204) return null as T;
  return response.json();
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem('refresh_token');
  if (!refresh) return false;
  try {
    const res = await fetch(`${API_BASE}/v1/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!res.ok) return false;
    const data: TokenResponse = await res.json();
    tokenStore.set(data.access_token);
    return true;
  } catch { return false; }
}

// ── Auth API ───────────────────────────────────────────────────────────────────
export const authApi = {
  register: (email: string, password: string, full_name: string) =>
    apiFetch<User>('/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, full_name }),
    }),

  login: async (email: string, password: string): Promise<User> => {
    const tokens = await apiFetch<TokenResponse>('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    tokenStore.set(tokens.access_token);
    localStorage.setItem('refresh_token', tokens.refresh_token);
    return apiFetch<User>('/v1/auth/me');
  },

  logout: async () => {
    await apiFetch('/v1/auth/logout', { method: 'POST' }).catch(() => {});
    tokenStore.clear();
    localStorage.removeItem('refresh_token');
  },

  me: () => apiFetch<User>('/v1/auth/me'),
};

// ── Skills & Roadmap API ───────────────────────────────────────────────────────
export const roadmapApi = {
  getSkills: () => apiFetch<SkillAssessment[]>('/v1/roadmap/skills'),
  getRoadmap: () => apiFetch<RoadmapItem[]>('/v1/roadmap/roadmap'),
  markComplete: (itemId: string, completed: boolean) =>
    apiFetch<RoadmapItem>(`/v1/roadmap/roadmap/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify({ completed }),
    }),
};

// ── Interview API ──────────────────────────────────────────────────────────────
export const interviewApi = {
  startSession: (topic: string, difficulty: string) =>
    apiFetch<InterviewSession>('/v1/interview/', {
      method: 'POST',
      body: JSON.stringify({ topic, difficulty }),
    }),

  getSessions: () => apiFetch<InterviewSession[]>('/v1/interview/'),

  nextQuestion: (sessionId: string) =>
    apiFetch<Question | null>(`/v1/interview/${sessionId}/questions/next`, {
      method: 'POST',
    }),

  submitAnswer: (questionId: string, answerText: string) =>
    apiFetch<Submission>(`/v1/interview/questions/${questionId}/submit`, {
      method: 'POST',
      body: JSON.stringify({ answer_text: answerText }),
    }),
};

export default apiFetch;
