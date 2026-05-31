/**
 * Dashboard — CSR (user-specific, auth-required)
 * Shows: skill radar, recent sessions, quick stats
 */

import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { roadmapApi, interviewApi, SkillAssessment, InterviewSession } from '../utils/api';

const TOPIC_COLORS: Record<string, string> = {
  DSA: '#00E5CC',
  OS: '#8B5CF6',
  DBMS: '#F59E0B',
  CN: '#3B82F6',
  OOP: '#22C55E',
  'System Design': '#EF4444',
};

function SkillRadar({ skills }: { skills: SkillAssessment[] }) {
  if (!skills.length) return (
    <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--text-muted)' }}>
      <div style={{ fontSize: '2rem', marginBottom: 'var(--space-2)' }}>◎</div>
      <p style={{ fontSize: '0.875rem' }}>Complete an interview to see your skill map</p>
    </div>
  );

  const cx = 120, cy = 120, r = 90;
  const n = skills.length;
  const points = skills.map((s, i) => {
    const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
    const score = s.proficiency_score;
    return {
      x: cx + r * score * Math.cos(angle),
      y: cy + r * score * Math.sin(angle),
      labelX: cx + (r + 22) * Math.cos(angle),
      labelY: cy + (r + 22) * Math.sin(angle),
      topic: s.skill_topic,
      score,
      angle,
    };
  });

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ') + ' Z';

  // Grid rings at 25%, 50%, 75%, 100%
  const rings = [0.25, 0.5, 0.75, 1.0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 'var(--space-4)' }}>
      <svg viewBox="0 0 240 240" width="220" height="220" style={{ overflow: 'visible' }}>
        {/* Grid rings */}
        {rings.map(ring =>
          <polygon key={ring}
            points={skills.map((_, i) => {
              const angle = (i / n) * 2 * Math.PI - Math.PI / 2;
              return `${(cx + r * ring * Math.cos(angle)).toFixed(1)},${(cy + r * ring * Math.sin(angle)).toFixed(1)}`;
            }).join(' ')}
            fill="none"
            stroke="var(--border-subtle)"
            strokeWidth="1"
          />
        )}
        {/* Spokes */}
        {points.map(p => (
          <line key={p.topic} x1={cx} y1={cy} x2={cx + r * Math.cos(p.angle)} y2={cy + r * Math.sin(p.angle)}
            stroke="var(--border-subtle)" strokeWidth="1" />
        ))}
        {/* Skill polygon */}
        <path d={path} fill="rgba(0,229,204,0.12)" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" />
        {/* Score dots */}
        {points.map(p => (
          <circle key={p.topic} cx={p.x} cy={p.y} r="4"
            fill="var(--accent)" stroke="var(--bg-panel)" strokeWidth="2" />
        ))}
        {/* Labels */}
        {points.map(p => (
          <text key={p.topic}
            x={p.labelX} y={p.labelY}
            textAnchor={p.labelX < cx - 5 ? 'end' : p.labelX > cx + 5 ? 'start' : 'middle'}
            dominantBaseline="middle"
            fill={TOPIC_COLORS[p.topic] || 'var(--text-secondary)'}
            fontSize="9"
            fontFamily="var(--font-mono)"
            fontWeight="600"
            letterSpacing="0.05em"
          >
            {p.topic.toUpperCase().replace(' DESIGN', ' D.')}
          </text>
        ))}
      </svg>
    </div>
  );
}

function ScoreBar({ score, topic }: { score: number; topic: string }) {
  const color = TOPIC_COLORS[topic] || 'var(--accent)';
  const pct = Math.round(score * 100);
  const grade = pct >= 85 ? 'Excellent' : pct >= 70 ? 'Good' : pct >= 50 ? 'Fair' : 'Needs Work';
  return (
    <div style={{ marginBottom: 'var(--space-3)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 'var(--space-1)', alignItems: 'center' }}>
        <span style={{ fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{topic}</span>
        <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{grade}</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem', color }}>{pct}%</span>
        </div>
      </div>
      <div className="score-bar">
        <div className="score-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const { user, isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.push('/login');
  }, [authLoading, isAuthenticated, router]);

  const { data: skills, loading: skillsLoading } = useApi<SkillAssessment[]>(
    isAuthenticated ? roadmapApi.getSkills : null,
    [isAuthenticated]
  );
  const { data: sessions, loading: sessionsLoading } = useApi<InterviewSession[]>(
    isAuthenticated ? interviewApi.getSessions : null,
    [isAuthenticated]
  );

  if (authLoading || !isAuthenticated) return (
    <div style={{ minHeight: '80vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ width: 32, height: 32, border: '2px solid var(--border-subtle)', borderTopColor: 'var(--accent)', borderRadius: '50%', animation: 'spin 0.8s linear infinite' }} />
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );

  const completedSessions = sessions?.filter(s => s.status === 'completed') ?? [];
  const avgScore = completedSessions.length
    ? Math.round(completedSessions.reduce((a, s) => a + (s.score ?? 0), 0) / completedSessions.length)
    : 0;

  return (
    <>
      <Head><title>Dashboard — DevMentor AI</title></Head>
      <div className="page">
        {/* Header */}
        <div style={{ marginBottom: 'var(--space-8)' }} className="fade-up">
          <span className="mono" style={{ color: 'var(--accent)', marginBottom: 'var(--space-2)', display: 'block' }}>dashboard</span>
          <h1 style={{ fontSize: '2rem', marginBottom: 'var(--space-1)' }}>
            Welcome back, {user?.full_name.split(' ')[0]}.
          </h1>
          <p>Here's where you stand today.</p>
        </div>

        {/* Stats row */}
        <div className="grid-3 fade-up fade-up-delay-1" style={{ marginBottom: 'var(--space-6)' }}>
          {[
            { label: 'Sessions', value: sessions?.length ?? '—', mono: true },
            { label: 'Avg Score', value: avgScore ? `${avgScore}%` : '—', mono: true },
            { label: 'Weak Topics', value: skills?.filter(s => s.proficiency_score < 0.6).length ?? '—', mono: true },
          ].map(stat => (
            <div key={stat.label} className="card" style={{ textAlign: 'center' }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: '2rem', fontWeight: 700, color: 'var(--text-primary)', lineHeight: 1 }}>
                {stat.value}
              </div>
              <div style={{ marginTop: 'var(--space-2)', fontSize: '0.8rem', fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {stat.label}
              </div>
            </div>
          ))}
        </div>

        {/* Main content */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1.6fr', gap: 'var(--space-6)' }}>

          {/* Skill Radar */}
          <div className="card fade-up fade-up-delay-2">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-4)' }}>
              <h3 style={{ fontSize: '0.95rem' }}>Skill Map</h3>
              <span className="badge badge-accent">Live</span>
            </div>
            {skillsLoading
              ? <div className="skeleton" style={{ height: 220 }} />
              : <SkillRadar skills={skills ?? []} />
            }
          </div>

          {/* Skill breakdown + action */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>

            <div className="card fade-up fade-up-delay-2">
              <h3 style={{ fontSize: '0.95rem', marginBottom: 'var(--space-4)' }}>Proficiency Breakdown</h3>
              {skillsLoading
                ? [1,2,3].map(i => <div key={i} className="skeleton" style={{ height: 36, marginBottom: 'var(--space-3)' }} />)
                : skills?.length
                  ? skills.sort((a,b) => a.proficiency_score - b.proficiency_score).map(s => (
                    <ScoreBar key={s.skill_topic} score={s.proficiency_score} topic={s.skill_topic} />
                  ))
                  : <p style={{ fontSize: '0.875rem', color: 'var(--text-muted)' }}>Complete your first interview to see scores.</p>
              }
            </div>

            <div className="card fade-up fade-up-delay-3" style={{
              background: 'linear-gradient(135deg, rgba(0,229,204,0.06) 0%, var(--bg-panel) 60%)',
              border: '1px solid rgba(0,229,204,0.15)',
            }}>
              <h3 style={{ fontSize: '0.95rem', marginBottom: 'var(--space-2)' }}>Ready to practice?</h3>
              <p style={{ fontSize: '0.875rem', marginBottom: 'var(--space-4)' }}>
                Start an interview session to update your skill scores and get AI coaching.
              </p>
              <Link href="/interview" className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }}>
                Start Interview Session →
              </Link>
            </div>
          </div>
        </div>

        {/* Recent sessions */}
        {(sessions?.length ?? 0) > 0 && (
          <div className="card fade-up" style={{ marginTop: 'var(--space-6)' }}>
            <h3 style={{ fontSize: '0.95rem', marginBottom: 'var(--space-4)' }}>Recent Sessions</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {sessions?.slice(0, 5).map(s => (
                <div key={s.id} style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: 'var(--space-3) var(--space-4)',
                  background: 'var(--bg-elevated)', borderRadius: 'var(--radius-md)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: TOPIC_COLORS[s.topic] ?? 'var(--accent)' }}>{s.topic}</span>
                    <span className="badge" style={{ background: 'var(--bg-overlay)', color: 'var(--text-muted)', fontSize: '0.65rem' }}>{s.difficulty}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                    {s.score !== null && (
                      <span style={{
                        fontFamily: 'var(--font-mono)', fontWeight: 600, fontSize: '0.875rem',
                        color: s.score >= 85 ? 'var(--success)' : s.score >= 70 ? '#84CC16' : s.score >= 50 ? 'var(--warning)' : 'var(--error)',
                      }}>
                        {s.score}%
                      </span>
                    )}
                    <span className={`badge badge-${s.status === 'completed' ? 'success' : s.status === 'active' ? 'accent' : ''}`}>
                      {s.status}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
