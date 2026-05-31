/**
 * interview.tsx — Interview Room (wired to real API)
 *
 * Three phases:
 *   SETUP    → Choose topic + difficulty → start session via API
 *   SESSION  → One question at a time → submit answers → real ML scores
 *   RESULTS  → Session review with all scores and feedback
 *
 * State machine: SETUP → SESSION → RESULTS
 * All data persisted to DB — user can leave and resume.
 */

import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import apiFetch from '../utils/api';

const TOPICS = ['DSA', 'OS', 'DBMS', 'CN', 'OOP', 'System Design'];
const DIFFICULTIES = ['easy', 'medium', 'hard'];

const TOPIC_COLORS: Record<string, string> = {
  DSA: '#00E5CC', OS: '#8B5CF6', DBMS: '#F59E0B',
  CN: '#3B82F6', OOP: '#22C55E', 'System Design': '#EF4444',
};

const TOPIC_DESCRIPTIONS: Record<string, string> = {
  DSA: 'Algorithms, data structures, complexity analysis',
  OS: 'Processes, memory, concurrency, scheduling',
  DBMS: 'Transactions, indexing, normalization, SQL',
  CN: 'TCP/IP, HTTP, DNS, protocols',
  OOP: 'Design patterns, SOLID, inheritance, composition',
  'System Design': 'Scalability, distributed systems, CAP theorem',
};

interface Session {
  id: string;
  topic: string;
  difficulty: string;
  status: string;
  score: number | null;
}

interface Question {
  id: string;
  question_text: string;
  skill_topic: string;
  skill_tag: string | null;
  difficulty: string | null;
  order_index: number;
}

interface SubmissionResult {
  id: string;
  answer_text: string;
  similarity_score: number | null;
  confidence_score: number | null;
  ai_feedback: string | null;
}

interface AnswerRecord {
  question: Question;
  submission: SubmissionResult;
}

type Phase = 'setup' | 'session' | 'results';

const scoreColor = (score: number | null) => {
  if (score === null) return 'var(--text-muted)';
  if (score >= 85) return 'var(--success)';
  if (score >= 70) return '#84CC16';
  if (score >= 50) return 'var(--warning)';
  return 'var(--error)';
};

const gradeLabel = (score: number | null) => {
  if (score === null) return 'Pending';
  if (score >= 85) return 'Excellent';
  if (score >= 70) return 'Good';
  if (score >= 50) return 'Fair';
  return 'Needs Work';
};

export default function InterviewPage() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();

  const [phase, setPhase] = useState<Phase>('setup');
  const [topic, setTopic] = useState('DSA');
  const [difficulty, setDifficulty] = useState('medium');

  // Session state
  const [session, setSession] = useState<Session | null>(null);
  const [questions, setQuestions] = useState<Question[]>([]);
  const [questionIdx, setQuestionIdx] = useState(0);
  const [currentAnswer, setCurrentAnswer] = useState('');
  const [answers, setAnswers] = useState<AnswerRecord[]>([]);

  // UI state
  const [submitting, setSubmitting] = useState(false);
  const [starting, setStarting] = useState(false);
  const [latestSubmission, setLatestSubmission] = useState<SubmissionResult | null>(null);
  const [error, setError] = useState('');
  const [completingSession, setCompletingSession] = useState(false);

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.push('/login');
  }, [authLoading, isAuthenticated, router]);

  const currentQuestion = questions[questionIdx];

  const requestNextQuestion = async (sessionId: string) =>
    apiFetch<Question | null>(`/v1/interview/${sessionId}/questions/next`, {
      method: 'POST',
    });

  const handleStart = async () => {
    setError('');
    setStarting(true);
    try {
      // 1. Create session
      const sess = await apiFetch<Session>('/v1/interview/', {
        method: 'POST',
        body: JSON.stringify({ topic, difficulty }),
      });
      setSession(sess);

      // 2. Request the first adaptive question
      const question = await requestNextQuestion(sess.id);
      if (!question) throw new Error('No unused questions remain for this topic');
      setQuestions([question]);

      // 3. Transition to session phase
      setQuestionIdx(0);
      setCurrentAnswer('');
      setAnswers([]);
      setLatestSubmission(null);
      setPhase('session');
    } catch (err: any) {
      setError(err.message || 'Failed to start session');
    } finally {
      setStarting(false);
    }
  };

  const handleSubmitAnswer = async () => {
    if (!currentAnswer.trim() || submitting || !session || !currentQuestion) return;
    setSubmitting(true);
    setError('');

    try {
      const submission = await apiFetch<SubmissionResult>(
        `/v1/interview/questions/${currentQuestion.id}/submit`,
        {
          method: 'POST',
          body: JSON.stringify({ answer_text: currentAnswer }),
        }
      );
      setLatestSubmission(submission);
      setAnswers(prev => [...prev, { question: currentQuestion, submission }]);
    } catch (err: any) {
      setError(err.message || 'Failed to submit answer');
    } finally {
      setSubmitting(false);
    }
  };

  const finishSession = async () => {
    if (!session) return;
    setCompletingSession(true);
    try {
      await apiFetch(`/v1/interview/${session.id}/complete`, { method: 'POST' });
    } catch {
      // Even if completion fails, keep the learner's local review available.
    } finally {
      setCompletingSession(false);
    }
    setPhase('results');
  };

  const handleNext = async () => {
    if (!session) return;
    setCompletingSession(true);
    try {
      const question = await requestNextQuestion(session.id);
      if (!question) {
        await finishSession();
        return;
      }
      setQuestions(prev => [...prev, question]);
      setQuestionIdx(i => i + 1);
      setCurrentAnswer('');
      setLatestSubmission(null);
    } catch (err: any) {
      setError(err.message || 'Failed to load the next question');
    } finally {
      setCompletingSession(false);
    }
  };

  const handleAbandon = async () => {
    if (!session) return;
    try {
      await apiFetch(`/v1/interview/${session.id}/abandon`, { method: 'POST' });
    } catch {}
    setPhase('setup');
    setSession(null);
    setQuestions([]);
  };

  const parseFeedback = (raw: string | null): Record<string, string> => {
    if (!raw) return {};
    try {
      return typeof raw === 'string' ? JSON.parse(raw) : raw;
    } catch {
      return { assessment: raw };
    }
  };

  const avgScore = answers.length > 0
    ? Math.round(
        answers.reduce((acc, a) => acc + (a.submission.similarity_score ?? 0) * 100, 0)
        / answers.length
      )
    : null;

  if (authLoading || !isAuthenticated) return null;

  // ── SETUP ────────────────────────────────────────────────────────────────────
  if (phase === 'setup') return (
    <>
      <Head><title>Interview Room — DevMentor AI</title></Head>
      <div className="page-sm" style={{ paddingTop: 'var(--space-12)' }}>
        <div className="fade-up" style={{ marginBottom: 'var(--space-8)' }}>
          <span className="mono" style={{ color: 'var(--accent)', display: 'block', marginBottom: 'var(--space-2)' }}>interview room</span>
          <h1 style={{ fontSize: '1.75rem', marginBottom: 'var(--space-2)' }}>Configure your session</h1>
          <p style={{ fontSize: '0.875rem' }}>Adaptive questions · AI-scored answers · rule-based coaching path</p>
        </div>

        <div className="card fade-up fade-up-delay-1">
          {/* Topic selector */}
          <div style={{ marginBottom: 'var(--space-6)' }}>
            <div className="mono" style={{ color: 'var(--text-primary)', marginBottom: 'var(--space-3)' }}>Topic</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 'var(--space-2)' }}>
              {TOPICS.map(t => (
                <button key={t} onClick={() => setTopic(t)} style={{
                  padding: 'var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: `1px solid ${t === topic ? TOPIC_COLORS[t] : 'var(--border-default)'}`,
                  background: t === topic ? `${TOPIC_COLORS[t]}14` : 'var(--bg-elevated)',
                  color: t === topic ? TOPIC_COLORS[t] : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.75rem',
                  fontWeight: t === topic ? 600 : 400,
                  transition: 'all var(--transition)',
                  textAlign: 'left',
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>{t}</div>
                  <div style={{ fontSize: '0.65rem', opacity: 0.7 }}>{TOPIC_DESCRIPTIONS[t]}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Difficulty selector */}
          <div style={{ marginBottom: 'var(--space-6)' }}>
            <div className="mono" style={{ color: 'var(--text-primary)', marginBottom: 'var(--space-3)' }}>Difficulty</div>
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              {DIFFICULTIES.map(d => (
                <button key={d} onClick={() => setDifficulty(d)} style={{
                  flex: 1,
                  padding: 'var(--space-3)',
                  borderRadius: 'var(--radius-md)',
                  border: `1px solid ${d === difficulty ? 'var(--accent)' : 'var(--border-default)'}`,
                  background: d === difficulty ? 'var(--accent-bg)' : 'var(--bg-elevated)',
                  color: d === difficulty ? 'var(--accent)' : 'var(--text-secondary)',
                  cursor: 'pointer',
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.8rem',
                  fontWeight: d === difficulty ? 600 : 400,
                  transition: 'all var(--transition)',
                  textTransform: 'capitalize',
                }}>
                  {d}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'var(--error-bg)', color: 'var(--error)', fontSize: '0.875rem', marginBottom: 'var(--space-4)' }}>
              {error}
            </div>
          )}

          <button
            className="btn btn-primary w-full"
            onClick={handleStart}
            disabled={starting}
            style={{ justifyContent: 'center' }}
          >
            {starting ? 'Starting…' : `Start ${topic} Session →`}
          </button>
        </div>
      </div>
    </>
  );

  // ── SESSION ───────────────────────────────────────────────────────────────────
  if (phase === 'session') return (
    <>
      <Head><title>Interview — {topic} — DevMentor AI</title></Head>
      <div className="page" style={{ maxWidth: 760 }}>
        {/* Progress */}
        <div style={{ marginBottom: 'var(--space-6)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
              <span className="mono" style={{ color: TOPIC_COLORS[topic] }}>{topic}</span>
              <span className="badge" style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{currentQuestion?.difficulty ?? difficulty}</span>
              {currentQuestion?.skill_tag && (
                <span className="badge" style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{currentQuestion.skill_tag}</span>
              )}
            </div>
            <span className="mono" style={{ color: 'var(--accent)' }}>
              adaptive question {questionIdx + 1}
            </span>
          </div>
        </div>

        {/* Question */}
        <div className="card fade-up" style={{ marginBottom: 'var(--space-4)' }}>
          <div style={{ display: 'flex', gap: 'var(--space-3)', alignItems: 'flex-start', marginBottom: 'var(--space-4)' }}>
            <div style={{
              minWidth: 32, height: 32,
              background: 'var(--accent-bg)', border: '1px solid rgba(0,229,204,0.2)',
              borderRadius: 'var(--radius-sm)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--accent)',
              flexShrink: 0,
            }}>
              Q{questionIdx + 1}
            </div>
            <p style={{ color: 'var(--text-primary)', fontWeight: 500, lineHeight: 1.6, fontSize: '1rem' }}>
              {currentQuestion?.question_text}
            </p>
          </div>

          <textarea
            className="input"
            placeholder="Think out loud — explain your reasoning, not just the answer. A good answer is 3-5 sentences."
            value={currentAnswer}
            onChange={e => setCurrentAnswer(e.target.value)}
            disabled={!!latestSubmission}
            style={{ minHeight: 150 }}
          />

          <div style={{ marginTop: 'var(--space-3)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <button
              onClick={handleAbandon}
              style={{
                padding: 'var(--space-2) var(--space-3)',
                background: 'transparent', border: '1px solid var(--border-default)',
                borderRadius: 'var(--radius-md)', color: 'var(--text-muted)',
                cursor: 'pointer', fontSize: '0.8rem',
              }}
            >
              Abandon session
            </button>

            {!latestSubmission && (
              <button
                className="btn btn-primary"
                onClick={handleSubmitAnswer}
                disabled={!currentAnswer.trim() || submitting}
                style={{ minWidth: 140 }}
              >
                {submitting ? (
                  <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    <span style={{ width: 14, height: 14, border: '2px solid rgba(0,0,0,0.3)', borderTopColor: '#000', borderRadius: '50%', display: 'inline-block', animation: 'spin 0.8s linear infinite' }} />
                    Scoring…
                  </span>
                ) : 'Submit Answer →'}
              </button>
            )}
          </div>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>

        {/* Feedback */}
        {latestSubmission && (() => {
          const score = latestSubmission.similarity_score !== null
            ? Math.round(latestSubmission.similarity_score * 100)
            : null;
          const fb = parseFeedback(latestSubmission.ai_feedback);
          return (
            <div className="card fade-up" style={{
              marginBottom: 'var(--space-4)',
              borderColor: score !== null && score >= 70 ? 'rgba(34,197,94,0.25)' : 'rgba(245,158,11,0.25)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
                <h3 style={{ fontSize: '0.95rem' }}>AI Feedback</h3>
                <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                  {score !== null && (
                    <>
                      <span className={`badge badge-${score >= 85 ? 'success' : score >= 50 ? 'warning' : 'error'}`}>
                        {gradeLabel(score)}
                      </span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1.3rem', color: scoreColor(score) }}>
                        {score}%
                      </span>
                    </>
                  )}
                  {score === null && (
                    <span className="badge" style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
                      Scoring pending
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                {[
                  { label: 'Assessment', value: fb.assessment },
                  { label: 'Strengths', value: fb.strengths },
                  { label: 'Improve', value: fb.improvements },
                  { label: 'Follow-up', value: fb.hint },
                ].filter(f => f.value).map(f => (
                  <div key={f.label} style={{
                    padding: 'var(--space-3)',
                    background: 'var(--bg-elevated)',
                    borderRadius: 'var(--radius-md)',
                    borderLeft: '2px solid var(--border-strong)',
                  }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', display: 'block', marginBottom: 4 }}>{f.label}</span>
                    <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>{f.value}</span>
                  </div>
                ))}
              </div>

              <button
                className="btn btn-primary"
                onClick={handleNext}
                disabled={completingSession}
                style={{ marginTop: 'var(--space-4)', width: '100%', justifyContent: 'center' }}
              >
                {completingSession ? 'Loading…' : 'Next Adaptive Question →'}
              </button>
              <button
                className="btn btn-ghost"
                onClick={finishSession}
                disabled={completingSession}
                style={{ marginTop: 'var(--space-2)', width: '100%', justifyContent: 'center' }}
              >
                Finish Session
              </button>
            </div>
          );
        })()}

        {error && (
          <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'var(--error-bg)', color: 'var(--error)', fontSize: '0.875rem' }}>
            {error}
          </div>
        )}
      </div>
    </>
  );

  // ── RESULTS ───────────────────────────────────────────────────────────────────
  return (
    <>
      <Head><title>Results — {topic} — DevMentor AI</title></Head>
      <div className="page" style={{ maxWidth: 760 }}>
        <div className="fade-up" style={{ textAlign: 'center', marginBottom: 'var(--space-8)' }}>
          <span className="mono" style={{ color: 'var(--accent)', display: 'block', marginBottom: 'var(--space-3)' }}>session complete</span>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 'clamp(3rem, 8vw, 5rem)',
            fontWeight: 700,
            color: scoreColor(avgScore),
            lineHeight: 1,
          }}>
            {avgScore !== null ? `${avgScore}%` : '—'}
          </div>
          <div className="badge" style={{
            margin: 'var(--space-3) auto 0',
            background: avgScore !== null && avgScore >= 70 ? 'var(--success-bg)' : 'var(--warning-bg)',
            color: avgScore !== null && avgScore >= 70 ? 'var(--success)' : 'var(--warning)',
          }}>
            {gradeLabel(avgScore)}
          </div>
          <p style={{ marginTop: 'var(--space-3)', fontSize: '0.875rem' }}>
            {topic} · {difficulty} · {answers.length} question{answers.length !== 1 ? 's' : ''}
          </p>
        </div>

        {/* Answer review */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)', marginBottom: 'var(--space-6)' }}>
          {answers.map((a, i) => {
            const score = a.submission.similarity_score !== null
              ? Math.round(a.submission.similarity_score * 100) : null;
            const fb = parseFeedback(a.submission.ai_feedback);
            return (
              <div key={i} className="card fade-up" style={{ animationDelay: `${i * 0.08}s` }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 'var(--space-3)' }}>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center', flexWrap: 'wrap' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>Q{i + 1}</span>
                    <p style={{ fontWeight: 500, color: 'var(--text-primary)', fontSize: '0.9rem', lineHeight: 1.5 }}>
                      {a.question.question_text}
                    </p>
                  </div>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: '1.1rem',
                    color: scoreColor(score), flexShrink: 0, marginLeft: 'var(--space-3)',
                  }}>
                    {score !== null ? `${score}%` : '—'}
                  </span>
                </div>

                {/* User's answer */}
                <div style={{
                  padding: 'var(--space-3)', background: 'var(--bg-elevated)',
                  borderRadius: 'var(--radius-md)', marginBottom: 'var(--space-3)',
                  borderLeft: '2px solid var(--border-subtle)',
                }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', display: 'block', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Your answer</span>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>{a.submission.answer_text}</p>
                </div>

                {fb.assessment && (
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                    {fb.assessment}
                  </p>
                )}
                {fb.improvements && (
                  <p style={{ fontSize: '0.82rem', color: 'var(--warning)', marginTop: 'var(--space-1)' }}>
                    ↗ {fb.improvements}
                  </p>
                )}
              </div>
            );
          })}
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-4)' }}>
          <button
            className="btn btn-primary"
            onClick={() => {
              setPhase('setup');
              setSession(null);
              setAnswers([]);
              setQuestions([]);
            }}
            style={{ flex: 1, justifyContent: 'center' }}
          >
            New Session →
          </button>
          <Link href="/roadmap" className="btn btn-ghost" style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            View Roadmap
          </Link>
        </div>
      </div>
    </>
  );
}
