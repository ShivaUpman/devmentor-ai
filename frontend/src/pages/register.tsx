import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import { useState } from 'react';
import { useAuth } from '../hooks/useAuth';

export default function RegisterPage() {
  const { register, loading } = useAuth();
  const router = useRouter();
  const [form, setForm] = useState({ email: '', password: '', full_name: '' });
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (form.password.length < 8) { setError('Password must be at least 8 characters'); return; }
    if (new TextEncoder().encode(form.password).length > 72) { setError('Password must be 72 bytes or less'); return; }
    if (!/[A-Z]/.test(form.password)) { setError('Password must contain an uppercase letter'); return; }
    if (!/[0-9]/.test(form.password)) { setError('Password must contain a number'); return; }
    try {
      await register(form.email, form.password, form.full_name);
      router.push('/dashboard');
    } catch (err: any) {
      setError(err.message);
    }
  };

  const field = (key: keyof typeof form, label: string, type: string, placeholder: string) => (
    <div>
      <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 500, color: 'var(--text-primary)', marginBottom: 'var(--space-2)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</label>
      <input className="input" type={type} required placeholder={placeholder}
        value={form[key]} onChange={e => setForm(f => ({ ...f, [key]: e.target.value }))} />
    </div>
  );

  return (
    <>
      <Head><title>Create Account — DevMentor AI</title></Head>
      <div className="page-sm" style={{ paddingTop: 'var(--space-16)' }}>
        <div style={{ textAlign: 'center', marginBottom: 'var(--space-8)' }}>
          <div style={{
            width: 40, height: 40, background: 'var(--accent)', borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto var(--space-4)',
          }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 14, color: '#000' }}>DM</span>
          </div>
          <h1 style={{ fontSize: '1.5rem', marginBottom: 'var(--space-2)' }}>Create your account</h1>
          <p style={{ fontSize: '0.875rem' }}>Free — no credit card required</p>
        </div>

        <div className="card">
          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
            {field('full_name', 'Full Name', 'text', 'Ada Lovelace')}
            {field('email', 'Email', 'email', 'ada@example.com')}
            {field('password', 'Password', 'password', '8+ chars, uppercase, number')}

            {error && (
              <div style={{ padding: 'var(--space-3)', borderRadius: 'var(--radius-md)', background: 'var(--error-bg)', border: '1px solid rgba(239,68,68,0.2)', color: 'var(--error)', fontSize: '0.875rem' }}>
                {error}
              </div>
            )}

            <button className="btn btn-primary w-full" type="submit" disabled={loading}>
              {loading ? 'Creating account…' : 'Create Account →'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', marginTop: 'var(--space-4)', fontSize: '0.875rem' }}>
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </div>
    </>
  );
}
