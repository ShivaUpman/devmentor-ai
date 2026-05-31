import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useState } from 'react';
import { useAuth } from '../hooks/useAuth';

export default function LoginPage() {
  const { login, loading } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ email: '', password: '' });
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await login(form.email, form.password);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <>
      <Head><title>Login — DevMentor AI</title></Head>
      <div className="page-sm" style={{ paddingTop: 'var(--space-16)' }}>
        <div style={{ textAlign: 'center', marginBottom: 'var(--space-8)' }}>
          <div style={{
            width: 40, height: 40, background: 'var(--accent)', borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto var(--space-4)',
          }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 14, color: '#000' }}>DM</span>
          </div>
          <h1 style={{ fontSize: '1.5rem', marginBottom: 'var(--space-2)' }}>Welcome back</h1>
          <p style={{ fontSize: '0.875rem' }}>Continue your interview prep</p>
        </div>

        <div className="card">
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-primary)', marginBottom: 'var(--space-2)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Email</label>
              <input className="input" type="email" required placeholder="you@example.com"
                value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-primary)', marginBottom: 'var(--space-2)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Password</label>
              <input className="input" type="password" required placeholder="••••••••"
                value={form.password} onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
            </div>

            {error && (
              <div style={{
                padding: 'var(--space-3)', borderRadius: 'var(--radius-md)',
                background: 'var(--error-bg)', border: '1px solid rgba(239,68,68,0.2)',
                color: 'var(--error)', fontSize: '0.875rem',
              }}>
                {error}
              </div>
            )}

            <button className="btn btn-primary w-full" type="submit" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign In →'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: 'var(--space-4)', fontSize: '0.875rem' }}>
          No account? <Link href="/register">Create one free</Link>
        </p>
      </div>
    </>
  );
}
