/**
 * Landing page — SSG (static, no auth needed, SEO matters)
 * Aesthetic: Terminal Precision — hero with typewriter effect, feature grid
 */

import Head from 'next/head';
import Link from 'next/link';
import { useEffect, useState } from 'react';

const TYPEWRITER_PHRASES = [
  'ace your next interview.',
  'close your skill gaps.',
  'build in public.',
  'think like a senior engineer.',
];

function TypewriterHero() {
  const [phraseIdx, setPhraseIdx] = useState(0);
  const [text, setText] = useState('');
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const target = TYPEWRITER_PHRASES[phraseIdx];
    const speed = deleting ? 40 : 80;

    const timeout = setTimeout(() => {
      if (!deleting && text === target) {
        setTimeout(() => setDeleting(true), 1800);
        return;
      }
      if (deleting && text === '') {
        setDeleting(false);
        setPhraseIdx(i => (i + 1) % TYPEWRITER_PHRASES.length);
        return;
      }
      setText(prev => deleting ? prev.slice(0, -1) : target.slice(0, prev.length + 1));
    }, speed);

    return () => clearTimeout(timeout);
  }, [text, deleting, phraseIdx]);

  return (
    <span style={{ color: 'var(--accent)' }}>
      {text}
      <span style={{
        display: 'inline-block',
        width: 2,
        height: '0.9em',
        background: 'var(--accent)',
        marginLeft: 2,
        verticalAlign: 'middle',
        animation: 'blink 1s step-end infinite',
      }} />
      <style>{`@keyframes blink { 50% { opacity: 0; } }`}</style>
    </span>
  );
}

const FEATURES = [
  {
    icon: '⟨⟩',
    title: 'AI-Scored Answers',
    body: 'Sentence-transformer embeddings compute semantic similarity — not keyword matching. Understand how close your answer is to mastery.',
  },
  {
    icon: '◈',
    title: 'Skill Gap Detection',
    body: 'Six technical domains. After each session, your proficiency map updates. See exactly where you stand, not just how you felt.',
  },
  {
    icon: '→',
    title: 'Personalized Roadmap',
    body: 'Groq LLM analyzes your weak spots and generates an ordered study plan — prerequisite-aware, time-estimated, resource-curated.',
  },
  {
    icon: '⊕',
    title: 'LLM Coaching',
    body: 'Llama 3.3-70B provides grounded feedback: what you got right, what to improve, and a follow-up question to deepen understanding.',
  },
  {
    icon: '◎',
    title: 'Code Review',
    body: 'Upload code for automated review against best practices for performance, security, and maintainability.',
  },
  {
    icon: '▸',
    title: 'Progress Analytics',
    body: 'Track proficiency over time. See which topics improved. Know when you\'re ready — not just when it feels like you might be.',
  },
];

export default function LandingPage() {
  return (
    <>
      <Head>
        <title>DevMentor AI — Interview Coaching Platform</title>
        <meta name="description" content="AI-powered technical interview coaching with semantic scoring, skill gap detection, and personalized roadmaps." />
      </Head>

      {/* Top bar */}
      <nav style={{
        borderBottom: '1px solid var(--border-subtle)',
        padding: '0 var(--space-6)',
      }}>
        <div style={{
          maxWidth: 1100, margin: '0 auto',
          height: 56,
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <div style={{
              width: 28, height: 28, background: 'var(--accent)',
              borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color: '#000' }}>DM</span>
            </div>
            <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>DevMentor AI</span>
          </div>
          <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
            <Link href="/login" className="btn btn-ghost" style={{ padding: 'var(--space-2) var(--space-4)', fontSize: '0.875rem' }}>Login</Link>
            <Link href="/register" className="btn btn-primary" style={{ padding: 'var(--space-2) var(--space-4)', fontSize: '0.875rem' }}>Get Started</Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section style={{
        minHeight: '82vh',
        display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        padding: 'var(--space-16) var(--space-6)',
        position: 'relative',
        overflow: 'hidden',
      }}>
        {/* Background grid */}
        <div style={{
          position: 'absolute', inset: 0,
          backgroundImage: `
            linear-gradient(var(--border-subtle) 1px, transparent 1px),
            linear-gradient(90deg, var(--border-subtle) 1px, transparent 1px)
          `,
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse 70% 60% at 50% 40%, black, transparent)',
          pointerEvents: 'none',
        }} />

        {/* Glow */}
        <div style={{
          position: 'absolute',
          width: 400, height: 400,
          borderRadius: '50%',
          background: 'radial-gradient(circle, rgba(0,229,204,0.08) 0%, transparent 70%)',
          top: '20%', left: '50%', transform: 'translateX(-50%)',
          pointerEvents: 'none',
        }} />

        <div style={{ position: 'relative', textAlign: 'center', maxWidth: 720 }}>
          <div className="badge badge-accent fade-up" style={{ marginBottom: 'var(--space-6)' }}>
            Powered by Llama 3.3 70B + Sentence Transformers
          </div>

          <h1 className="fade-up fade-up-delay-1" style={{
            fontSize: 'clamp(2rem, 5vw, 3.5rem)',
            fontWeight: 700,
            lineHeight: 1.1,
            letterSpacing: '-0.03em',
            color: 'var(--text-primary)',
            marginBottom: 'var(--space-4)',
          }}>
            The engineer you want to be starts with knowing exactly where you're weak.
          </h1>

          <p className="fade-up fade-up-delay-2" style={{
            fontSize: '1.125rem',
            color: 'var(--text-secondary)',
            marginBottom: 'var(--space-8)',
            lineHeight: 1.7,
          }}>
            Practice interviews. Get semantically-scored feedback. Build a personalized roadmap.{' '}
            <TypewriterHero />
          </p>

          <div className="fade-up fade-up-delay-3" style={{ display: 'flex', gap: 'var(--space-4)', justifyContent: 'center', flexWrap: 'wrap' }}>
            <Link href="/register" className="btn btn-primary" style={{ padding: 'var(--space-4) var(--space-8)', fontSize: '1rem' }}>
              Start Practicing Free →
            </Link>
            <Link href="/login" className="btn btn-ghost" style={{ padding: 'var(--space-4) var(--space-8)', fontSize: '1rem' }}>
              Login
            </Link>
          </div>
        </div>
      </section>

      {/* Tech stack strip */}
      <div style={{
        borderTop: '1px solid var(--border-subtle)',
        borderBottom: '1px solid var(--border-subtle)',
        padding: 'var(--space-4) var(--space-6)',
        overflow: 'hidden',
      }}>
        <div style={{
          display: 'flex', gap: 'var(--space-8)',
          justifyContent: 'center', flexWrap: 'wrap',
        }}>
          {['FastAPI', 'Next.js', 'PostgreSQL', 'Redis', 'Docker', 'Groq LLM', 'Sentence Transformers', 'TF-IDF + Logistic Regression'].map(tech => (
            <span key={tech} style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              color: 'var(--text-muted)',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
            }}>
              {tech}
            </span>
          ))}
        </div>
      </div>

      {/* Features grid */}
      <section style={{ padding: 'var(--space-16) var(--space-6)' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <div style={{ textAlign: 'center', marginBottom: 'var(--space-12)' }}>
            <span className="mono" style={{ color: 'var(--accent)', marginBottom: 'var(--space-3)', display: 'block' }}>capabilities</span>
            <h2 style={{ fontSize: '2rem', marginBottom: 'var(--space-4)' }}>Built for engineers, by engineers.</h2>
            <p style={{ maxWidth: 560, margin: '0 auto' }}>Every feature maps to a real interview skill gap. No fluff, no gamification — just signal.</p>
          </div>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: 'var(--space-4)',
          }}>
            {FEATURES.map((f, i) => (
              <div key={f.title} className="card" style={{ animationDelay: `${i * 0.05}s` }}>
                <div style={{
                  width: 36, height: 36,
                  background: 'var(--accent-bg)',
                  border: '1px solid rgba(0,229,204,0.2)',
                  borderRadius: 'var(--radius-md)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--accent)',
                  fontSize: '1.1rem',
                  marginBottom: 'var(--space-4)',
                }}>
                  {f.icon}
                </div>
                <h3 style={{ marginBottom: 'var(--space-2)', fontSize: '1rem' }}>{f.title}</h3>
                <p style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section style={{
        padding: 'var(--space-16) var(--space-6)',
        textAlign: 'center',
        borderTop: '1px solid var(--border-subtle)',
      }}>
        <h2 style={{ marginBottom: 'var(--space-4)' }}>Ready to find out where you actually stand?</h2>
        <p style={{ marginBottom: 'var(--space-8)', maxWidth: 480, margin: '0 auto var(--space-8)' }}>
          Free to use. No credit card. Start with one interview session.
        </p>
        <Link href="/register" className="btn btn-primary" style={{ padding: 'var(--space-4) var(--space-8)', fontSize: '1rem' }}>
          Create Free Account →
        </Link>
      </section>

      <footer style={{
        borderTop: '1px solid var(--border-subtle)',
        padding: 'var(--space-6)',
        textAlign: 'center',
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          DevMentor AI — Portfolio Project — Built with FastAPI · Next.js · PostgreSQL · Redis · Groq · Docker
        </span>
      </footer>
    </>
  );
}
