import type { AppProps } from 'next/app';
import { useRouter } from 'next/router';
import Link from 'next/link';
import { useAuth } from '../hooks/useAuth';
import '../styles/globals.css';

// Public routes that don't require auth
const PUBLIC_ROUTES = ['/', '/login', '/register'];

function NavBar() {
  const { user, logout, isAuthenticated } = useAuth();
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.push('/login');
  };

  if (!isAuthenticated) return null;

  return (
    <nav style={{
      borderBottom: '1px solid var(--border-subtle)',
      background: 'rgba(10,10,11,0.8)',
      backdropFilter: 'blur(12px)',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      padding: '0 var(--space-6)',
    }}>
      <div style={{
        maxWidth: 1100,
        margin: '0 auto',
        height: 56,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        {/* Logo */}
        <Link href="/dashboard" style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', textDecoration: 'none' }}>
          <div style={{
            width: 28, height: 28,
            background: 'var(--accent)',
            borderRadius: 6,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color: 'var(--text-inverse)' }}>DM</span>
          </div>
          <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: '0.95rem' }}>DevMentor</span>
        </Link>

        {/* Nav links */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-1)' }}>
          {[
            { href: '/dashboard', label: 'Dashboard' },
            { href: '/interview', label: 'Interview' },
            { href: '/roadmap', label: 'Roadmap' },
          ].map(link => (
            <Link key={link.href} href={link.href} style={{
              padding: 'var(--space-2) var(--space-3)',
              borderRadius: 'var(--radius-md)',
              fontSize: '0.875rem',
              fontWeight: 500,
              color: router.pathname === link.href ? 'var(--accent)' : 'var(--text-secondary)',
              background: router.pathname === link.href ? 'var(--accent-bg)' : 'transparent',
              transition: 'all var(--transition)',
              textDecoration: 'none',
            }}>
              {link.label}
            </Link>
          ))}
        </div>

        {/* User section */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {user?.email}
          </span>
          <button onClick={handleLogout} className="btn btn-ghost" style={{ padding: 'var(--space-2) var(--space-3)', fontSize: '0.8rem' }}>
            Logout
          </button>
        </div>
      </div>
    </nav>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  return (
    <>
      <NavBar />
      <Component {...pageProps} />
    </>
  );
}
