import React, { useState } from 'react';
import { supabase, isSupabaseConfigured } from './supabaseClient';

const API_BASE = import.meta.env.VITE_API_BASE_URL || (window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin);

export default function AuthView({ onAuthSuccess, showToast, onBackToLanding }) {
  const [mode, setMode] = useState('login'); // 'login' | 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [businessName, setBusinessName] = useState('');
  const [phone, setPhone] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setErrorMsg(null);
    setIsLoading(true);

    try {
      if (mode === 'signup') {
        if (!businessName.trim()) {
          throw new Error('Please enter your Business / Company Name');
        }

        // 1. Direct Backend Registration (Immediately writes to PostgreSQL merchants table)
        const res = await fetch(`${API_BASE}/api/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            business_name: businessName.trim(),
            email: email.trim(),
            password: password,
            phone: phone.trim() || null
          })
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Registration failed');
        }

        const data = await res.json();
        if (data.session) {
          showToast?.(`Welcome ${businessName}! Merchant account created in database.`, 'success');
          onAuthSuccess(data.session);
        }
      } else {
        // 1. Direct Backend Login (Ensures merchant in PostgreSQL)
        const res = await fetch(`${API_BASE}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: email.trim(),
            password: password
          })
        });

        if (!res.ok) {
          const errData = await res.json();
          throw new Error(errData.detail || 'Login failed');
        }

        const data = await res.json();
        if (data.session) {
          const name = data.session.user?.user_metadata?.business_name || email.split('@')[0];
          showToast?.(`Welcome back, ${name}!`, 'success');
          onAuthSuccess(data.session);
        }
      }
    } catch (err) {
      console.error('Auth error:', err);
      setErrorMsg(err.message || 'Authentication failed. Please check credentials.');
      showToast?.(err.message || 'Authentication error', 'error');
    } finally {
      setIsLoading(false);
    }
  };



  return (
    <div style={{
      minHeight: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      backgroundColor: 'var(--bg-dark, #f2f0e9)',
      padding: '24px',
      fontFamily: "'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif"
    }}>
      <div style={{
        width: '100%',
        maxWidth: '440px',
        backgroundColor: 'var(--bg-card, #ffffff)',
        borderRadius: '16px',
        border: '1px solid var(--border-color, #e6e4dc)',
        boxShadow: '0 8px 30px rgba(0, 0, 0, 0.04)',
        padding: '36px',
        position: 'relative'
      }}>
        
        {onBackToLanding && (
          <button
            type="button"
            onClick={onBackToLanding}
            style={{
              position: 'absolute',
              top: '20px',
              left: '20px',
              background: 'none',
              border: 'none',
              color: 'var(--text-muted, #666560)',
              fontSize: '0.85rem',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              transition: 'color 0.2s'
            }}
            onMouseOver={(e) => e.currentTarget.style.color = 'var(--text-main, #24221f)'}
            onMouseOut={(e) => e.currentTarget.style.color = 'var(--text-muted, #666560)'}
          >
            ← Home
          </button>
        )}

        {/* Logo & Header */}
        <div style={{ textAlign: 'center', marginBottom: '28px', marginTop: onBackToLanding ? '14px' : '0' }}>
          <div style={{
            width: '44px',
            height: '44px',
            borderRadius: '10px',
            backgroundColor: 'var(--primary, #da7756)',
            color: '#FFFFFF',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.3rem',
            marginBottom: '12px',
            boxShadow: '0 4px 12px rgba(218, 119, 86, 0.25)'
          }}>
            ⚡
          </div>
          <h1 style={{ fontSize: '1.45rem', fontWeight: '800', color: 'var(--text-main, #24221f)', margin: '0 0 6px 0', letterSpacing: '-0.02em' }}>
            Resolve.ai
          </h1>
          <p style={{ fontSize: '0.82rem', color: 'var(--text-muted, #666560)', margin: 0 }}>
            Autonomous Accounts Receivable & Collections Portal
          </p>
        </div>

        {/* Tab Switcher */}
        <div style={{
          display: 'flex',
          backgroundColor: 'var(--bg-dark, #f2f0e9)',
          padding: '4px',
          borderRadius: '10px',
          border: '1px solid var(--border-color, #e6e4dc)',
          marginBottom: '24px'
        }}>
          <button
            type="button"
            onClick={() => { setMode('login'); setErrorMsg(null); }}
            style={{
              flex: 1,
              padding: '8px',
              border: mode === 'login' ? '1px solid var(--border-color, #e6e4dc)' : 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              fontSize: '0.85rem',
              transition: 'all 0.2s',
              backgroundColor: mode === 'login' ? '#FFFFFF' : 'transparent',
              color: mode === 'login' ? 'var(--text-main, #24221f)' : 'var(--text-muted, #666560)',
              boxShadow: mode === 'login' ? '0 1px 3px rgba(0,0,0,0.04)' : 'none'
            }}
          >
            Sign In
          </button>
          <button
            type="button"
            onClick={() => { setMode('signup'); setErrorMsg(null); }}
            style={{
              flex: 1,
              padding: '8px',
              border: mode === 'signup' ? '1px solid var(--border-color, #e6e4dc)' : 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              fontSize: '0.85rem',
              transition: 'all 0.2s',
              backgroundColor: mode === 'signup' ? '#FFFFFF' : 'transparent',
              color: mode === 'signup' ? 'var(--text-main, #24221f)' : 'var(--text-muted, #666560)',
              boxShadow: mode === 'signup' ? '0 1px 3px rgba(0,0,0,0.04)' : 'none'
            }}
          >
            Create Account
          </button>
        </div>

        {/* Error Alert */}
        {errorMsg && (
          <div style={{
            padding: '10px 14px',
            borderRadius: '8px',
            backgroundColor: 'var(--danger-bg, #faeaea)',
            border: '1px solid var(--danger, #c44336)',
            color: 'var(--danger, #c44336)',
            fontSize: '0.82rem',
            marginBottom: '18px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px'
          }}>
            <span>⚠️</span> {errorMsg}
          </div>
        )}

        {/* Auth Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {mode === 'signup' && (
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: 'var(--text-main, #24221f)', marginBottom: '6px' }}>
                Business / Company Name *
              </label>
              <input
                type="text"
                placeholder="e.g. Apex Logistics Pvt Ltd"
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid var(--border-color, #e6e4dc)',
                  backgroundColor: '#FFFFFF',
                  fontSize: '0.9rem',
                  color: 'var(--text-main, #24221f)',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
                required
              />
            </div>
          )}

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: 'var(--text-main, #24221f)', marginBottom: '6px' }}>
              Work Email *
            </label>
            <input
              type="email"
              placeholder="merchant@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                border: '1px solid var(--border-color, #e6e4dc)',
                backgroundColor: '#FFFFFF',
                fontSize: '0.9rem',
                color: 'var(--text-main, #24221f)',
                outline: 'none',
                boxSizing: 'border-box'
              }}
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: 'var(--text-main, #24221f)', marginBottom: '6px' }}>
              Password *
            </label>
            <input
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              style={{
                width: '100%',
                padding: '10px 14px',
                borderRadius: '8px',
                border: '1px solid var(--border-color, #e6e4dc)',
                backgroundColor: '#FFFFFF',
                fontSize: '0.9rem',
                color: 'var(--text-main, #24221f)',
                outline: 'none',
                boxSizing: 'border-box'
              }}
              required
            />
          </div>

          {mode === 'signup' && (
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: 'var(--text-main, #24221f)', marginBottom: '6px' }}>
                Contact Phone (Optional)
              </label>
              <input
                type="tel"
                placeholder="+91 98765 43210"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  borderRadius: '8px',
                  border: '1px solid var(--border-color, #e6e4dc)',
                  backgroundColor: '#FFFFFF',
                  fontSize: '0.9rem',
                  color: 'var(--text-main, #24221f)',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={isLoading}
            style={{
              width: '100%',
              padding: '12px',
              borderRadius: '8px',
              border: 'none',
              backgroundColor: 'var(--primary, #da7756)',
              color: '#FFFFFF',
              fontWeight: '600',
              fontSize: '0.92rem',
              cursor: 'pointer',
              marginTop: '6px',
              boxShadow: '0 2px 8px rgba(218, 119, 86, 0.25)',
              transition: 'background 0.2s',
              opacity: isLoading ? 0.7 : 1
            }}
            onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--primary-hover, #c46445)'}
            onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'var(--primary, #da7756)'}
          >
            {isLoading ? 'Processing...' : mode === 'login' ? 'Sign In to Merchant Portal' : 'Create Merchant Account'}
          </button>
        </form>
      </div>
    </div>
  );
}
