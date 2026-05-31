/**
 * Roadmap page — CSR (personalized, auth-required, Redis-cached on backend)
 */

import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useEffect, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { useApi } from '../hooks/useApi';
import { roadmapApi, RoadmapItem } from '../utils/api';

const TYPE_ICONS: Record<string, string> = {
  article: '◈',
  video: '▶',
  course: '◎',
  book: '⊞',
  practice: '⊕',
};

const TOPIC_COLORS: Record<string, string> = {
  DSA: '#00E5CC', OS: '#8B5CF6', DBMS: '#F59E0B',
  CN: '#3B82F6', OOP: '#22C55E', 'System Design': '#EF4444',
};

function RoadmapCard({ item, onToggle }: { item: RoadmapItem; onToggle: (id: string, completed: boolean) => void }) {
  const [toggling, setToggling] = useState(false);

  const handleToggle = async () => {
    setToggling(true);
    await onToggle(item.id, !item.completed);
    setToggling(false);
  };

  return (
    <div className="card" style={{
      display: 'flex',
      gap: 'var(--space-4)',
      opacity: item.completed ? 0.6 : 1,
      transition: 'opacity var(--transition)',
      borderColor: item.completed ? 'var(--success)' : undefined,
    }}>
      {/* Priority indicator */}
      <div style={{
        minWidth: 36, height: 36,
        background: item.completed ? 'var(--success-bg)' : 'var(--accent-bg)',
        border: `1px solid ${item.completed ? 'rgba(34,197,94,0.3)' : 'rgba(0,229,204,0.2)'}`,
        borderRadius: 'var(--radius-md)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.9rem',
        color: item.completed ? 'var(--success)' : 'var(--accent)',
        flexShrink: 0,
      }}>
        {item.completed ? '✓' : item.priority}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-1)', flexWrap: 'wrap' }}>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.65rem',
            color: TOPIC_COLORS[item.skill_topic] ?? 'var(--accent)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
          }}>
            {item.skill_topic}
          </span>
          <span style={{
            fontFamily: 'var(--font-mono)', fontSize: '0.65rem',
            color: 'var(--text-muted)',
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>
            {TYPE_ICONS[item.resource_type]} {item.resource_type}
          </span>
        </div>

        <a href={item.resource_url} target="_blank" rel="noopener noreferrer" style={{
          display: 'block',
          fontWeight: 500,
          color: 'var(--text-primary)',
          fontSize: '0.95rem',
          marginBottom: 'var(--space-1)',
          textDecoration: item.completed ? 'line-through' : 'none',
        }}>
          {item.resource_title} ↗
        </a>
      </div>

      {/* Complete button */}
      <button onClick={handleToggle} disabled={toggling} style={{
        minWidth: 80,
        padding: 'var(--space-1) var(--space-3)',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid ${item.completed ? 'var(--border-default)' : 'rgba(0,229,204,0.3)'}`,
        background: item.completed ? 'var(--bg-elevated)' : 'var(--accent-bg)',
        color: item.completed ? 'var(--text-muted)' : 'var(--accent)',
        cursor: 'pointer',
        fontFamily: 'var(--font-mono)',
        fontSize: '0.7rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.06em',
        alignSelf: 'center',
        transition: 'all var(--transition)',
        flexShrink: 0,
      }}>
        {toggling ? '…' : item.completed ? 'Undo' : 'Done'}
      </button>
    </div>
  );
}

export default function RoadmapPage() {
  const { isAuthenticated, loading: authLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !isAuthenticated) router.push('/login');
  }, [authLoading, isAuthenticated, router]);

  const { data: items, loading, refetch } = useApi<RoadmapItem[]>(
    isAuthenticated ? roadmapApi.getRoadmap : null,
    [isAuthenticated]
  );

  const handleToggle = async (id: string, completed: boolean) => {
    await roadmapApi.markComplete(id, completed);
    refetch();
  };

  const completed = items?.filter(i => i.completed).length ?? 0;
  const total = items?.length ?? 0;
  const progress = total > 0 ? (completed / total) * 100 : 0;

  if (authLoading || !isAuthenticated) return null;

  return (
    <>
      <Head><title>Learning Roadmap — DevMentor AI</title></Head>
      <div className="page" style={{ maxWidth: 780 }}>

        {/* Header */}
        <div className="fade-up" style={{ marginBottom: 'var(--space-8)' }}>
          <span className="mono" style={{ color: 'var(--accent)', display: 'block', marginBottom: 'var(--space-2)' }}>learning roadmap</span>
          <h1 style={{ fontSize: '2rem', marginBottom: 'var(--space-2)' }}>Your personalized study plan</h1>
          <p style={{ fontSize: '0.875rem' }}>
            Generated by Groq LLM from your skill gaps. Ordered by urgency.
          </p>
        </div>

        {/* Progress */}
        {total > 0 && (
          <div className="card fade-up fade-up-delay-1" style={{ marginBottom: 'var(--space-6)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-3)' }}>
              <span style={{ fontSize: '0.875rem', fontWeight: 500, color: 'var(--text-primary)' }}>Overall Progress</span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent)' }}>
                {completed} / {total}
              </span>
            </div>
            <div className="score-bar">
              <div className="score-bar-fill" style={{ width: `${progress}%`, background: 'var(--accent)' }} />
            </div>
            {progress === 100 && (
              <p style={{ marginTop: 'var(--space-3)', fontSize: '0.875rem', color: 'var(--success)', fontFamily: 'var(--font-mono)' }}>
                🎉 Roadmap complete! Ready for your next session.
              </p>
            )}
          </div>
        )}

        {/* Resource list */}
        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            {[1, 2, 3, 4].map(i => (
              <div key={i} className="skeleton" style={{ height: 100 }} />
            ))}
          </div>
        ) : !items?.length ? (
          <div className="card fade-up" style={{ textAlign: 'center', padding: 'var(--space-12)' }}>
            <div style={{ fontSize: '2rem', marginBottom: 'var(--space-4)' }}>◎</div>
            <h3 style={{ marginBottom: 'var(--space-2)' }}>No roadmap yet</h3>
            <p style={{ fontSize: '0.875rem', marginBottom: 'var(--space-6)' }}>
              Complete another interview session to assess more skills. Roadmap resources appear when an assessed topic needs improvement.
            </p>
            <Link href="/interview" className="btn btn-primary">Start Interview →</Link>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            {items.map((item, i) => (
              <div key={item.id} className="fade-up" style={{ animationDelay: `${i * 0.06}s` }}>
                <RoadmapCard item={item} onToggle={handleToggle} />
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
