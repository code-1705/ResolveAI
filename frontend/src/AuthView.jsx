import React, { useState } from 'react';
import { supabase, isSupabaseConfigured } from './supabaseClient';

export default function AuthView({ onAuthSuccess, showToast }) {
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
        const res = await fetch('http://localhost:8000/api/auth/register', {
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
        const res = await fetch('http://localhost:8000/api/auth/login', {
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
      background: 'radial-gradient(circle at 50% 10%, #F8FAFC 0%, #EDF2F7 100%)',
      padding: '24px',
      fontFamily: 'var(--font-sans, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif)'
    }}>
      <div style={{
        width: '100%',
        maxWidth: '440px',
        background: '#FFFFFF',
        borderRadius: '20px',
        border: '1px solid var(--border-color, #E2E8F0)',
        boxShadow: '0 20px 40px -15px rgba(0, 0, 0, 0.08), 0 0 1px rgba(0, 0, 0, 0.1)',
        padding: '36px',
        position: 'relative'
      }}>
        
        {/* Logo & Header */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div style={{
            width: '48px',
            height: '48px',
            borderRadius: '12px',
            background: 'var(--primary, #3B82F6)',
            color: '#FFFFFF',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.4rem',
            marginBottom: '12px',
            boxShadow: '0 8px 16px rgba(59, 130, 246, 0.25)'
          }}>
            ⚡
          </div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: '700', color: 'var(--text-main, #0F172A)', margin: '0 0 6px 0' }}>
            Resolve.ai
          </h1>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-muted, #64748B)', margin: 0 }}>
            Autonomous Accounts Receivable & Collections Portal
          </p>
        </div>

        {/* Tab Switcher */}
        <div style={{
          display: 'flex',
          background: '#F1F5F9',
          padding: '4px',
          borderRadius: '10px',
          marginBottom: '24px'
        }}>
          <button
            type="button"
            onClick={() => { setMode('login'); setErrorMsg(null); }}
            style={{
              flex: 1,
              padding: '8px',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              fontSize: '0.85rem',
              transition: 'all 0.2s',
              background: mode === 'login' ? '#FFFFFF' : 'transparent',
              color: mode === 'login' ? '#0F172A' : '#64748B',
              boxShadow: mode === 'login' ? '0 2px 4px rgba(0,0,0,0.05)' : 'none'
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
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontWeight: '600',
              fontSize: '0.85rem',
              transition: 'all 0.2s',
              background: mode === 'signup' ? '#FFFFFF' : 'transparent',
              color: mode === 'signup' ? '#0F172A' : '#64748B',
              boxShadow: mode === 'signup' ? '0 2px 4px rgba(0,0,0,0.05)' : 'none'
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
            background: '#FEF2F2',
            border: '1px solid #FCA5A5',
            color: '#991B1B',
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
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: '#334155', marginBottom: '6px' }}>
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
                  border: '1px solid #CBD5E1',
                  fontSize: '0.9rem',
                  color: '#0F172A',
                  outline: 'none',
                  boxSizing: 'border-box'
                }}
                required
              />
            </div>
          )}

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: '#334155', marginBottom: '6px' }}>
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
                border: '1px solid #CBD5E1',
                fontSize: '0.9rem',
                color: '#0F172A',
                outline: 'none',
                boxSizing: 'border-box'
              }}
              required
            />
          </div>

          <div>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: '#334155', marginBottom: '6px' }}>
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
                border: '1px solid #CBD5E1',
                fontSize: '0.9rem',
                color: '#0F172A',
                outline: 'none',
                boxSizing: 'border-box'
              }}
              required
            />
          </div>

          {mode === 'signup' && (
            <div>
              <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: '600', color: '#334155', marginBottom: '6px' }}>
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
                  border: '1px solid #CBD5E1',
                  fontSize: '0.9rem',
                  color: '#0F172A',
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
              background: '#0F172A',
              color: '#FFFFFF',
              fontWeight: '600',
              fontSize: '0.9rem',
              cursor: 'pointer',
              marginTop: '8px',
              transition: 'all 0.2s',
              opacity: isLoading ? 0.7 : 1
            }}
          >
            {isLoading ? 'Processing...' : mode === 'login' ? 'Sign In to Merchant Portal' : 'Create Merchant Account'}
          </button>
        </form>



      </div>
    </div>
  );
}
