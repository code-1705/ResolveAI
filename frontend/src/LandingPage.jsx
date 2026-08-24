import React, { useState } from 'react';

export default function LandingPage({ onSignIn }) {
  // --- State for Interactive ROI Calculator ---
  const [monthlyVolume, setMonthlyVolume] = useState(500000); // ₹5 Lakhs default
  const [avgDSO, setAvgDSO] = useState(45); // 45 days default

  // ROI calculations
  const recoveryRate = 0.76;
  const recoveredAmount = Math.round(monthlyVolume * recoveryRate);
  const agencyCost20Pct = Math.round(recoveredAmount * 0.20);
  const resolveAiCost3Pct = Math.round(recoveredAmount * 0.03);
  const netSavingsMonthly = agencyCost20Pct - resolveAiCost3Pct;
  const dsoReductionDays = Math.round(avgDSO * 0.60);

  // --- State for Interactive Guardrails Playground ---
  const [playgroundMinPct, setPlaygroundMinPct] = useState(30);
  const [playgroundMaxExt, setPlaygroundMaxExt] = useState(14);
  const [selectedPreset, setSelectedPreset] = useState('lowball');
  const [customProposalAmount, setCustomProposalAmount] = useState(15000);
  const [customProposalDays, setCustomProposalDays] = useState(7);

  const sampleInvoiceTotal = 50000;
  const minRequiredAmount = Math.round(sampleInvoiceTotal * (playgroundMinPct / 100));

  let isApproved = false;
  let responseSummary = '';

  if (customProposalAmount >= minRequiredAmount && customProposalDays <= playgroundMaxExt) {
    isApproved = true;
    responseSummary = `Proposal Approved! Razorpay link generated for ₹${customProposalAmount.toLocaleString('en-IN')} with ${customProposalDays}-day extension.`;
  } else if (customProposalAmount < minRequiredAmount) {
    isApproved = false;
    responseSummary = `Offer Rejected (Below ${playgroundMinPct}% floor). Politely counter-offering down-payment of ₹${minRequiredAmount.toLocaleString('en-IN')} within policy.`;
  } else {
    isApproved = false;
    responseSummary = `Extension Rejected (Exceeds ${playgroundMaxExt}-day policy limit). Counter-offering max ${playgroundMaxExt} days extension.`;
  }

  const handlePresetClick = (preset) => {
    setSelectedPreset(preset);
    if (preset === 'lowball') {
      setCustomProposalAmount(5000);
      setCustomProposalDays(7);
    } else if (preset === 'valid') {
      setCustomProposalAmount(25000);
      setCustomProposalDays(7);
    } else if (preset === 'extension') {
      setCustomProposalAmount(30000);
      setCustomProposalDays(45);
    }
  };

  // --- State for Interactive FAQ Accordion ---
  const [openFaqIndex, setOpenFaqIndex] = useState(null);
  const toggleFaq = (index) => {
    setOpenFaqIndex(openFaqIndex === index ? null : index);
  };

  const faqs = [
    {
      q: "How does Resolve.ai connect to Razorpay?",
      a: "Resolve.ai integrates natively with Razorpay API and Razorpay Route. It generates dynamic, idempotent payment links supporting UPI, Cards, NetBanking, and settles 97% directly to your verified bank account in real-time."
    },
    {
      q: "Does the AI ever hallucinate or offer unauthorized discounts?",
      a: "Never. Resolve.ai uses a hardcoded, deterministic Guardrail Engine that validates every LLM response. If a customer requests terms outside your configured floor policy, the system hard-blocks the proposal and triggers a compliant counter-offer."
    },
    {
      q: "What messaging channels does Resolve.ai support?",
      a: "Resolve.ai is built for Meta WhatsApp Cloud API and interactive web simulators. It sends automated PDF invoice statements, interactive bill selection buttons, and payment receipts."
    },
    {
      q: "How does the 3% platform fee work?",
      a: "We only earn when you recover revenue. There are no monthly subscription fees. When an invoice is paid, Razorpay Route splits 97% directly to your bank account and 3% to Resolve.ai automatically."
    },
    {
      q: "Can I upload custom invoice PDFs or scans?",
      a: "Yes! Resolve.ai includes Gemini Flash Document OCR that automatically extracts customer names, phone numbers, amounts, and due dates from your uploaded PDF or image files in seconds."
    }
  ];

  return (
    <div style={{
      minHeight: '100vh',
      backgroundColor: 'var(--bg-dark, #f2f0e9)',
      color: 'var(--text-main, #24221f)',
      fontFamily: "'Plus Jakarta Sans', 'Inter', -apple-system, sans-serif"
    }}>
      {/* --- 1. Clean Minimalist Header --- */}
      <header style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        backdropFilter: 'blur(12px)',
        backgroundColor: 'rgba(242, 240, 233, 0.9)',
        borderBottom: '1px solid var(--border-color, #e6e4dc)',
        padding: '0 36px',
        height: '68px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        {/* Logo */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '34px',
            height: '34px',
            borderRadius: '8px',
            backgroundColor: 'var(--primary, #da7756)',
            color: '#FFFFFF',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1.1rem',
            fontWeight: 'bold'
          }}>
            ⚡
          </div>
          <div>
            <div style={{ fontSize: '1.2rem', fontWeight: '800', letterSpacing: '-0.02em', color: 'var(--text-main, #24221f)' }}>
              Resolve.ai
            </div>
            <div style={{ fontSize: '0.62rem', color: 'var(--text-muted, #666560)', fontWeight: '600', letterSpacing: '0.04em', textTransform: 'uppercase' }}>
              Autonomous Collections
            </div>
          </div>
        </div>

        {/* Navigation Links */}
        <nav style={{ display: 'flex', alignItems: 'center', gap: '28px' }}>
          <a href="#how-it-works" style={{ color: 'var(--text-muted, #666560)', textDecoration: 'none', fontSize: '0.88rem', fontWeight: '500' }}>How It Works</a>
          <a href="#guardrails" style={{ color: 'var(--text-muted, #666560)', textDecoration: 'none', fontSize: '0.88rem', fontWeight: '500' }}>Guardrails</a>
          <a href="#calculator" style={{ color: 'var(--text-muted, #666560)', textDecoration: 'none', fontSize: '0.88rem', fontWeight: '500' }}>ROI Calculator</a>
          <a href="#comparison" style={{ color: 'var(--text-muted, #666560)', textDecoration: 'none', fontSize: '0.88rem', fontWeight: '500' }}>Why Us</a>
          <a href="#faq" style={{ color: 'var(--text-muted, #666560)', textDecoration: 'none', fontSize: '0.88rem', fontWeight: '500' }}>FAQ</a>
        </nav>

        {/* Header Action: Only Sign In Button */}
        <div>
          <button
            onClick={onSignIn}
            style={{
              padding: '9px 24px',
              borderRadius: '8px',
              backgroundColor: 'var(--primary, #da7756)',
              border: 'none',
              color: '#FFFFFF',
              fontSize: '0.9rem',
              fontWeight: '600',
              cursor: 'pointer',
              boxShadow: '0 2px 8px rgba(218, 119, 86, 0.25)',
              transition: 'background 0.2s'
            }}
            onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--primary-hover, #c46445)'}
            onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'var(--primary, #da7756)'}
          >
            Sign In
          </button>
        </div>
      </header>

      {/* --- 2. Clean Minimalist Hero Section --- */}
      <section style={{
        padding: '70px 24px 60px',
        maxWidth: '1080px',
        margin: '0 auto',
        textAlign: 'center'
      }}>
        {/* Subtle Pill Tag */}
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 14px',
          borderRadius: '20px',
          backgroundColor: 'var(--bg-card, #ffffff)',
          border: '1px solid var(--border-color, #e6e4dc)',
          color: 'var(--text-muted, #666560)',
          fontSize: '0.8rem',
          fontWeight: '600',
          marginBottom: '20px'
        }}>
          <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: 'var(--success, #378b59)', display: 'inline-block' }} />
          Powered by Razorpay & Meta WhatsApp Cloud
        </div>

        {/* Main Headline */}
        <h1 style={{
          fontSize: 'clamp(2.3rem, 4.5vw, 3.6rem)',
          fontWeight: '800',
          lineHeight: '1.18',
          letterSpacing: '-0.03em',
          color: 'var(--text-main, #24221f)',
          margin: '0 auto 20px',
          maxWidth: '880px'
        }}>
          Transform Overdue Invoices into Recovered Cash on Autopilot
        </h1>

        {/* Subtitle */}
        <p style={{
          fontSize: '1.1rem',
          color: 'var(--text-muted, #666560)',
          maxWidth: '680px',
          margin: '0 auto 32px',
          lineHeight: '1.6'
        }}>
          Resolve.ai bridges human WhatsApp negotiation with deterministic Razorpay payment links.
          Recover up to <strong>78% of overdue TPV</strong> without burning client relationships or paying 20% collection agency cuts.
        </p>

        {/* Primary Action Button: Sign In */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '14px', marginBottom: '48px' }}>
          <button
            onClick={onSignIn}
            style={{
              padding: '13px 36px',
              borderRadius: '8px',
              backgroundColor: 'var(--primary, #da7756)',
              color: '#FFFFFF',
              border: 'none',
              fontSize: '1rem',
              fontWeight: '600',
              cursor: 'pointer',
              boxShadow: '0 4px 14px rgba(218, 119, 86, 0.3)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}
            onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--primary-hover, #c46445)'}
            onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'var(--primary, #da7756)'}
          >
            <span>Sign In to Workspace</span>
            <span>→</span>
          </button>

          <a
            href="#calculator"
            style={{
              padding: '13px 26px',
              borderRadius: '8px',
              backgroundColor: 'var(--bg-card, #ffffff)',
              color: 'var(--text-main, #24221f)',
              border: '1px solid var(--border-color, #e6e4dc)',
              fontSize: '0.95rem',
              fontWeight: '600',
              textDecoration: 'none'
            }}
          >
            Calculate ROI
          </a>
        </div>

        {/* 4 Minimalist Metric Cards */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px',
          maxWidth: '960px',
          margin: '0 auto'
        }}>
          <div style={{ padding: '20px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.6rem', fontWeight: '800', color: 'var(--success, #378b59)' }}>76.4%</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>Avg. Recovery Rate</div>
          </div>
          <div style={{ padding: '20px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.6rem', fontWeight: '800', color: 'var(--primary, #da7756)' }}>&lt; 3 Mins</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>Resolution Time</div>
          </div>
          <div style={{ padding: '20px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.6rem', fontWeight: '800', color: 'var(--text-main, #24221f)' }}>0% Hallucination</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>Guardrail Policy Engine</div>
          </div>
          <div style={{ padding: '20px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)', textAlign: 'center' }}>
            <div style={{ fontSize: '1.6rem', fontWeight: '800', color: 'var(--text-main, #24221f)' }}>97% Direct Wire</div>
            <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>Razorpay Route Payout</div>
          </div>
        </div>
      </section>

      {/* --- 3. Live Interactive Simulation Card --- */}
      <section style={{
        maxWidth: '1000px',
        margin: '0 auto 80px',
        padding: '0 24px'
      }}>
        <div style={{
          borderRadius: '16px',
          border: '1px solid var(--border-color, #e6e4dc)',
          backgroundColor: 'var(--bg-card, #ffffff)',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.04)',
          overflow: 'hidden'
        }}>
          {/* Header Bar */}
          <div style={{
            padding: '14px 20px',
            backgroundColor: 'var(--bg-dark, #f2f0e9)',
            borderBottom: '1px solid var(--border-color, #e6e4dc)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#c44336' }} />
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#d97706' }} />
              <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: '#378b59' }} />
              <span style={{ marginLeft: '8px', fontSize: '0.82rem', color: 'var(--text-muted, #666560)', fontWeight: '600' }}>
                Live WhatsApp & Razorpay Engine Simulation
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '7px', height: '7px', borderRadius: '50%', backgroundColor: 'var(--success, #378b59)' }} />
              <span style={{ fontSize: '0.75rem', color: 'var(--success, #378b59)', fontWeight: '600' }}>Webhooks Active</span>
            </div>
          </div>

          {/* Dual Panel */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
            {/* Left: WhatsApp View */}
            <div style={{ padding: '24px', backgroundColor: '#EFEAE2', borderRight: '1px solid var(--border-color, #e6e4dc)' }}>
              <div style={{
                backgroundColor: '#005D4B',
                color: '#FFF',
                padding: '8px 12px',
                borderRadius: '6px',
                fontSize: '0.8rem',
                fontWeight: '600',
                marginBottom: '14px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between'
              }}>
                <span>💬 WhatsApp • Apex Logistics</span>
                <span style={{ fontSize: '0.72rem', opacity: 0.85 }}>Due ₹50,000</span>
              </div>

              {/* Message 1: Outbound reminder */}
              <div style={{
                backgroundColor: '#FFFFFF',
                padding: '10px 12px',
                borderRadius: '0 10px 10px 10px',
                fontSize: '0.8rem',
                lineHeight: '1.4',
                marginBottom: '10px',
                maxWidth: '90%',
                boxShadow: '0 1px 2px rgba(0,0,0,0.08)'
              }}>
                <div>Hi Apex Logistics! Your Invoice <strong>inv_001</strong> for ₹50,000 is overdue. Attached is your official PDF bill statement.</div>
                <div style={{
                  marginTop: '6px',
                  padding: '6px 8px',
                  backgroundColor: '#F8FAFC',
                  borderRadius: '4px',
                  border: '1px solid #E2E8F0',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between'
                }}>
                  <span style={{ fontSize: '0.75rem', color: '#1E293B' }}>📄 inv_001_bill.pdf</span>
                  <span style={{ fontSize: '0.7rem', color: 'var(--primary, #da7756)', fontWeight: '600' }}>[Open PDF]</span>
                </div>
              </div>

              {/* Message 2: Buyer proposal */}
              <div style={{
                backgroundColor: '#D9FDD3',
                padding: '8px 12px',
                borderRadius: '10px 0 10px 10px',
                fontSize: '0.8rem',
                marginBottom: '10px',
                marginLeft: 'auto',
                maxWidth: '85%',
                boxShadow: '0 1px 2px rgba(0,0,0,0.08)'
              }}>
                Can we pay ₹20,000 (40%) today and the balance in 10 days?
              </div>

              {/* Message 3: Agent approval & Razorpay button */}
              <div style={{
                backgroundColor: '#FFFFFF',
                padding: '10px 12px',
                borderRadius: '0 10px 10px 10px',
                fontSize: '0.8rem',
                lineHeight: '1.4',
                maxWidth: '90%',
                boxShadow: '0 1px 2px rgba(0,0,0,0.08)'
              }}>
                <div>We can approve ₹20,000 today with a 10-day extension. Here is your payment link:</div>
                <div style={{
                  marginTop: '8px',
                  padding: '7px 10px',
                  backgroundColor: '#0066FF',
                  color: '#FFF',
                  borderRadius: '6px',
                  textAlign: 'center',
                  fontWeight: '600',
                  fontSize: '0.78rem'
                }}>
                  💳 Pay ₹20,000 via Razorpay (UPI/Card)
                </div>
              </div>
            </div>

            {/* Right: Guardrail Inspector */}
            <div style={{ padding: '24px', backgroundColor: 'var(--bg-card, #ffffff)', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
              <div>
                <div style={{ fontSize: '0.78rem', fontWeight: '700', color: 'var(--text-muted, #666560)', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '14px' }}>
                  🛡️ Guardrail Engine Verification
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ padding: '10px 12px', backgroundColor: 'var(--bg-dark, #f2f0e9)', borderRadius: '8px', border: '1px solid var(--border-color, #e6e4dc)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted, #666560)' }}>1. Buyer Proposal</div>
                    <div style={{ fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main, #24221f)' }}>₹20,000 (40.0%) • 10 Days Extension</div>
                  </div>

                  <div style={{ padding: '10px 12px', backgroundColor: 'var(--success-bg, #eaf3ed)', borderRadius: '8px', border: '1px solid var(--success, #378b59)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.72rem', color: 'var(--success, #378b59)', fontWeight: '700' }}>2. Policy Check</span>
                      <span style={{ fontSize: '0.68rem', padding: '2px 6px', borderRadius: '4px', backgroundColor: 'var(--success, #378b59)', color: '#FFF', fontWeight: '700' }}>PASS</span>
                    </div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-main, #24221f)', marginTop: '3px' }}>
                      Proposed 40% ≥ 30% Min Floor & 10 Days ≤ 14 Days Max Extension.
                    </div>
                  </div>

                  <div style={{ padding: '10px 12px', backgroundColor: 'var(--bg-dark, #f2f0e9)', borderRadius: '8px', border: '1px solid var(--border-color, #e6e4dc)' }}>
                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted, #666560)' }}>3. Settlement Split</div>
                    <div style={{ fontSize: '0.78rem', fontWeight: '600', color: 'var(--text-main, #24221f)', marginTop: '2px' }}>
                      97% (₹19,400) Bank Payout • 3% Platform Fee
                    </div>
                  </div>
                </div>
              </div>

              <button
                onClick={onSignIn}
                style={{
                  marginTop: '18px',
                  padding: '10px',
                  borderRadius: '6px',
                  backgroundColor: 'var(--primary, #da7756)',
                  color: '#FFF',
                  border: 'none',
                  fontSize: '0.85rem',
                  fontWeight: '600',
                  cursor: 'pointer'
                }}
              >
                Sign In to Test Live Simulator →
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* --- 4. Interactive ROI Calculator --- */}
      <section id="calculator" style={{
        padding: '70px 24px',
        maxWidth: '1000px',
        margin: '0 auto'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Interactive Financial Model
          </div>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: 0 }}>
            Calculate Your Recovered Cash & Agency Savings
          </h2>
          <p style={{ fontSize: '0.98rem', color: 'var(--text-muted, #666560)', maxWidth: '580px', margin: '8px auto 0' }}>
            See how much revenue Resolve.ai recovers for your business compared to traditional collection agencies.
          </p>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '24px',
          backgroundColor: 'var(--bg-card, #ffffff)',
          padding: '32px',
          borderRadius: '16px',
          border: '1px solid var(--border-color, #e6e4dc)',
          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.03)'
        }}>
          {/* Sliders */}
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: '700', marginBottom: '20px' }}>
              ⚙️ Your Business Metrics
            </h3>

            <div style={{ marginBottom: '22px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted, #666560)', fontWeight: '500' }}>Monthly Overdue Invoices</span>
                <span style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--primary, #da7756)' }}>₹{monthlyVolume.toLocaleString('en-IN')}</span>
              </div>
              <input
                type="range"
                min="50000"
                max="5000000"
                step="50000"
                value={monthlyVolume}
                onChange={(e) => setMonthlyVolume(Number(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--primary, #da7756)', cursor: 'pointer' }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>
                <span>₹50,000</span>
                <span>₹25,00,000</span>
                <span>₹50,00,000</span>
              </div>
            </div>

            <div style={{ marginBottom: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted, #666560)', fontWeight: '500' }}>Current Days Sales Outstanding (DSO)</span>
                <span style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--text-main, #24221f)' }}>{avgDSO} Days</span>
              </div>
              <input
                type="range"
                min="15"
                max="90"
                step="1"
                value={avgDSO}
                onChange={(e) => setAvgDSO(Number(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--text-main, #24221f)', cursor: 'pointer' }}
              />
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.7rem', color: 'var(--text-muted, #666560)', marginTop: '2px' }}>
                <span>15 Days</span>
                <span>45 Days</span>
                <span>90 Days</span>
              </div>
            </div>

            <div style={{ padding: '12px 14px', borderRadius: '8px', backgroundColor: 'var(--bg-dark, #f2f0e9)', border: '1px solid var(--border-color, #e6e4dc)' }}>
              <div style={{ fontSize: '0.8rem', color: 'var(--text-muted, #666560)' }}>
                💡 Resolve.ai delivers an average <strong>76% recovery rate</strong> within 14 days without high collection agency fees.
              </div>
            </div>
          </div>

          {/* Results */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{
              padding: '20px',
              borderRadius: '12px',
              backgroundColor: 'var(--success-bg, #eaf3ed)',
              border: '1px solid var(--success, #378b59)'
            }}>
              <div style={{ fontSize: '0.78rem', color: 'var(--success, #378b59)', fontWeight: '700', textTransform: 'uppercase' }}>
                Estimated Recovered Cash
              </div>
              <div style={{ fontSize: '2rem', fontWeight: '800', color: 'var(--success, #378b59)', margin: '4px 0 2px' }}>
                ₹{recoveredAmount.toLocaleString('en-IN')}
                <span style={{ fontSize: '0.9rem', fontWeight: '500' }}> / mo</span>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted, #666560)' }}>
                Accelerated cash flow <strong>{dsoReductionDays} days faster</strong>.
              </div>
            </div>

            <div style={{
              padding: '20px',
              borderRadius: '12px',
              backgroundColor: 'var(--bg-dark, #f2f0e9)',
              border: '1px solid var(--border-color, #e6e4dc)'
            }}>
              <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase' }}>
                Net Monthly Savings vs Collection Agency
              </div>
              <div style={{ fontSize: '1.8rem', fontWeight: '800', color: 'var(--primary, #da7756)', margin: '4px 0 2px' }}>
                ₹{netSavingsMonthly.toLocaleString('en-IN')}
                <span style={{ fontSize: '0.9rem', fontWeight: '500' }}> saved</span>
              </div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted, #666560)' }}>
                Agency fee: ₹{agencyCost20Pct.toLocaleString('en-IN')} (20%) vs Resolve.ai: ₹{resolveAiCost3Pct.toLocaleString('en-IN')} (3%).
              </div>
            </div>

            <button
              onClick={onSignIn}
              style={{
                marginTop: 'auto',
                padding: '12px',
                borderRadius: '8px',
                backgroundColor: 'var(--primary, #da7756)',
                color: '#FFF',
                border: 'none',
                fontWeight: '600',
                fontSize: '0.92rem',
                cursor: 'pointer'
              }}
            >
              Sign In to Recover Revenue →
            </button>
          </div>
        </div>
      </section>

      {/* --- 5. Interactive Guardrails Sandbox --- */}
      <section id="guardrails" style={{
        padding: '70px 24px',
        maxWidth: '1000px',
        margin: '0 auto'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Deterministic Policy Rules
          </div>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: 0 }}>
            Interactive Guardrail Sandbox
          </h2>
          <p style={{ fontSize: '0.98rem', color: 'var(--text-muted, #666560)', maxWidth: '580px', margin: '8px auto 0' }}>
            Adjust your floor policy sliders and test how the AI validates buyer proposals in real time.
          </p>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: '24px',
          backgroundColor: 'var(--bg-card, #ffffff)',
          padding: '32px',
          borderRadius: '16px',
          border: '1px solid var(--border-color, #e6e4dc)',
          boxShadow: '0 4px 16px rgba(0, 0, 0, 0.03)'
        }}>
          {/* Controls */}
          <div>
            <h3 style={{ fontSize: '1.1rem', fontWeight: '700', marginBottom: '18px' }}>
              🛡️ Set Floor Policies
            </h3>

            <div style={{ marginBottom: '20px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted, #666560)' }}>Min Down-Payment Floor</span>
                <span style={{ fontSize: '0.9rem', fontWeight: '700', color: 'var(--primary, #da7756)' }}>{playgroundMinPct}% (₹{minRequiredAmount.toLocaleString('en-IN')})</span>
              </div>
              <input
                type="range"
                min="10"
                max="80"
                step="5"
                value={playgroundMinPct}
                onChange={(e) => setPlaygroundMinPct(Number(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--primary, #da7756)', cursor: 'pointer' }}
              />
            </div>

            <div style={{ marginBottom: '22px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-muted, #666560)' }}>Max Allowed Extension</span>
                <span style={{ fontSize: '0.9rem', fontWeight: '700', color: 'var(--text-main, #24221f)' }}>{playgroundMaxExt} Days</span>
              </div>
              <input
                type="range"
                min="3"
                max="60"
                step="1"
                value={playgroundMaxExt}
                onChange={(e) => setPlaygroundMaxExt(Number(e.target.value))}
                style={{ width: '100%', accentColor: 'var(--text-main, #24221f)', cursor: 'pointer' }}
              />
            </div>

            <div>
              <div style={{ fontSize: '0.78rem', color: 'var(--text-muted, #666560)', fontWeight: '600', textTransform: 'uppercase', marginBottom: '8px' }}>
                Simulate Buyer Proposal:
              </div>
              <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                <button
                  onClick={() => handlePresetClick('lowball')}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '6px',
                    backgroundColor: selectedPreset === 'lowball' ? 'var(--danger-bg, #faeaea)' : 'var(--bg-dark, #f2f0e9)',
                    color: selectedPreset === 'lowball' ? 'var(--danger, #c44336)' : 'var(--text-main, #24221f)',
                    border: selectedPreset === 'lowball' ? '1px solid var(--danger, #c44336)' : '1px solid var(--border-color, #e6e4dc)',
                    fontSize: '0.78rem',
                    fontWeight: '600',
                    cursor: 'pointer'
                  }}
                >
                  Lowball 10% (₹5k)
                </button>
                <button
                  onClick={() => handlePresetClick('valid')}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '6px',
                    backgroundColor: selectedPreset === 'valid' ? 'var(--success-bg, #eaf3ed)' : 'var(--bg-dark, #f2f0e9)',
                    color: selectedPreset === 'valid' ? 'var(--success, #378b59)' : 'var(--text-main, #24221f)',
                    border: selectedPreset === 'valid' ? '1px solid var(--success, #378b59)' : '1px solid var(--border-color, #e6e4dc)',
                    fontSize: '0.78rem',
                    fontWeight: '600',
                    cursor: 'pointer'
                  }}
                >
                  Offer 50% (₹25k)
                </button>
                <button
                  onClick={() => handlePresetClick('extension')}
                  style={{
                    padding: '6px 10px',
                    borderRadius: '6px',
                    backgroundColor: selectedPreset === 'extension' ? 'var(--warning-bg, #fdf3e6)' : 'var(--bg-dark, #f2f0e9)',
                    color: selectedPreset === 'extension' ? 'var(--warning, #d97706)' : 'var(--text-main, #24221f)',
                    border: selectedPreset === 'extension' ? '1px solid var(--warning, #d97706)' : '1px solid var(--border-color, #e6e4dc)',
                    fontSize: '0.78rem',
                    fontWeight: '600',
                    cursor: 'pointer'
                  }}
                >
                  45 Days (Over Limit)
                </button>
              </div>
            </div>
          </div>

          {/* Decision */}
          <div style={{
            padding: '20px',
            borderRadius: '12px',
            backgroundColor: isApproved ? 'var(--success-bg, #eaf3ed)' : 'var(--bg-dark, #f2f0e9)',
            border: isApproved ? '1px solid var(--success, #378b59)' : '1px solid var(--border-color, #e6e4dc)',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'space-between'
          }}>
            <div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                <span style={{ fontSize: '0.8rem', fontWeight: '700', color: 'var(--text-muted, #666560)' }}>AI ENGINE DECISION</span>
                <span style={{
                  padding: '3px 8px',
                  borderRadius: '12px',
                  fontSize: '0.72rem',
                  fontWeight: '700',
                  backgroundColor: isApproved ? 'var(--success, #378b59)' : 'var(--danger, #c44336)',
                  color: '#FFF'
                }}>
                  {isApproved ? '✓ APPROVED & LINK SENT' : '✕ REJECTED & COUNTER-OFFER'}
                </span>
              </div>

              <div style={{ fontSize: '0.88rem', color: 'var(--text-main, #24221f)', lineHeight: '1.5', marginBottom: '12px' }}>
                {responseSummary}
              </div>

              <div style={{ padding: '10px', borderRadius: '6px', backgroundColor: 'var(--bg-card, #ffffff)', fontSize: '0.75rem', color: 'var(--text-muted, #666560)', border: '1px solid var(--border-color, #e6e4dc)' }}>
                <div>• Invoice Amount: ₹50,000</div>
                <div>• Proposed: ₹{customProposalAmount.toLocaleString('en-IN')}</div>
                <div>• Required Floor: ₹{minRequiredAmount.toLocaleString('en-IN')} ({playgroundMinPct}%)</div>
                <div>• Max Extension: {playgroundMaxExt} Days</div>
              </div>
            </div>

            <div style={{ marginTop: '14px', fontSize: '0.75rem', color: 'var(--text-muted, #666560)' }}>
              🔒 Hardcoded checks guarantee the AI never hallucinates unauthorized terms.
            </div>
          </div>
        </div>
      </section>

      {/* --- 6. How It Works (4 Clean Steps) --- */}
      <section id="how-it-works" style={{
        padding: '70px 24px',
        maxWidth: '1000px',
        margin: '0 auto'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '48px' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Autonomous Lifecycle
          </div>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: 0 }}>
            How Resolve.ai Works in 4 Steps
          </h2>
        </div>

        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '18px'
        }}>
          <div style={{ padding: '24px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '10px' }}>📄</div>
            <div style={{ fontSize: '0.72rem', fontWeight: '700', color: 'var(--primary, #da7756)', textTransform: 'uppercase', marginBottom: '4px' }}>Step 01</div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '6px' }}>Upload & OCR</h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted, #666560)', lineHeight: '1.5', margin: 0 }}>
              Upload invoice PDFs or images. Gemini Flash extracts buyer info, due dates, and amounts in integer paise.
            </p>
          </div>

          <div style={{ padding: '24px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '10px' }}>⏰</div>
            <div style={{ fontSize: '0.72rem', fontWeight: '700', color: 'var(--primary, #da7756)', textTransform: 'uppercase', marginBottom: '4px' }}>Step 02</div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '6px' }}>Due-Date WhatsApp</h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted, #666560)', lineHeight: '1.5', margin: 0 }}>
              On due date, the scheduler automatically dispatches polite WhatsApp reminders with official PDF bill statements.
            </p>
          </div>

          <div style={{ padding: '24px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '10px' }}>💬</div>
            <div style={{ fontSize: '0.72rem', fontWeight: '700', color: 'var(--primary, #da7756)', textTransform: 'uppercase', marginBottom: '4px' }}>Step 03</div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '6px' }}>AI Negotiation</h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted, #666560)', lineHeight: '1.5', margin: 0 }}>
              If buyers request installments or extensions, the agent negotiates agreements bounded strictly by your floor rules.
            </p>
          </div>

          <div style={{ padding: '24px', borderRadius: '12px', backgroundColor: 'var(--bg-card, #ffffff)', border: '1px solid var(--border-color, #e6e4dc)' }}>
            <div style={{ fontSize: '1.5rem', marginBottom: '10px' }}>💳</div>
            <div style={{ fontSize: '0.72rem', fontWeight: '700', color: 'var(--primary, #da7756)', textTransform: 'uppercase', marginBottom: '4px' }}>Step 04</div>
            <h3 style={{ fontSize: '1.05rem', fontWeight: '700', marginBottom: '6px' }}>Razorpay 97% Wire</h3>
            <p style={{ fontSize: '0.82rem', color: 'var(--text-muted, #666560)', lineHeight: '1.5', margin: 0 }}>
              Upon buyer payment, webhooks reconcile balances and Razorpay Route wires 97% directly to your bank account.
            </p>
          </div>
        </div>
      </section>

      {/* --- 7. Minimalist Comparison Table --- */}
      <section id="comparison" style={{
        padding: '70px 24px',
        maxWidth: '1000px',
        margin: '0 auto'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Why Resolve.ai
          </div>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: 0 }}>
            Resolve.ai vs Traditional Debt Collection
          </h2>
        </div>

        <div style={{
          overflowX: 'auto',
          borderRadius: '12px',
          border: '1px solid var(--border-color, #e6e4dc)',
          backgroundColor: 'var(--bg-card, #ffffff)'
        }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.88rem' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-color, #e6e4dc)', backgroundColor: 'var(--bg-dark, #f2f0e9)' }}>
                <th style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)', fontWeight: '600' }}>Feature</th>
                <th style={{ padding: '14px 18px', color: 'var(--primary, #da7756)', fontWeight: '700' }}>⚡ Resolve.ai</th>
                <th style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)', fontWeight: '600' }}>Collection Agencies</th>
                <th style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)', fontWeight: '600' }}>Manual In-House Chasing</th>
              </tr>
            </thead>
            <tbody>
              <tr style={{ borderBottom: '1px solid var(--border-color, #e6e4dc)' }}>
                <td style={{ padding: '14px 18px', fontWeight: '600' }}>Cost / Success Fee</td>
                <td style={{ padding: '14px 18px', color: 'var(--success, #378b59)', fontWeight: '700' }}>Only 3% on recovery</td>
                <td style={{ padding: '14px 18px', color: 'var(--danger, #c44336)' }}>20% - 35% of recovered TPV</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>40+ wasted staff hours/mo</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-color, #e6e4dc)' }}>
                <td style={{ padding: '14px 18px', fontWeight: '600' }}>Tone & Relationship</td>
                <td style={{ padding: '14px 18px', color: 'var(--success, #378b59)', fontWeight: '700' }}>Empathetic & collaborative</td>
                <td style={{ padding: '14px 18px', color: 'var(--danger, #c44336)' }}>Aggressive harassment</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>Awkward follow-ups</td>
              </tr>
              <tr style={{ borderBottom: '1px solid var(--border-color, #e6e4dc)' }}>
                <td style={{ padding: '14px 18px', fontWeight: '600' }}>Resolution Speed</td>
                <td style={{ padding: '14px 18px', color: 'var(--success, #378b59)', fontWeight: '700' }}>Instant WhatsApp &lt; 3 mins</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>30 to 90 days delay</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>Weeks of unread emails</td>
              </tr>
              <tr>
                <td style={{ padding: '14px 18px', fontWeight: '600' }}>Payment Mode</td>
                <td style={{ padding: '14px 18px', color: 'var(--success, #378b59)', fontWeight: '700' }}>1-Click Razorpay UPI / Cards</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>Manual NEFT wire</td>
                <td style={{ padding: '14px 18px', color: 'var(--text-muted, #666560)' }}>Manual reminders</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      {/* --- 8. FAQ Accordion --- */}
      <section id="faq" style={{
        padding: '70px 24px',
        maxWidth: '800px',
        margin: '0 auto'
      }}>
        <div style={{ textAlign: 'center', marginBottom: '40px' }}>
          <div style={{ fontSize: '0.78rem', color: 'var(--primary, #da7756)', fontWeight: '700', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '6px' }}>
            Common Questions
          </div>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: 0 }}>
            Frequently Asked Questions
          </h2>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {faqs.map((faq, idx) => {
            const isOpen = openFaqIndex === idx;
            return (
              <div
                key={idx}
                style={{
                  borderRadius: '10px',
                  backgroundColor: 'var(--bg-card, #ffffff)',
                  border: '1px solid var(--border-color, #e6e4dc)',
                  overflow: 'hidden'
                }}
              >
                <button
                  onClick={() => toggleFaq(idx)}
                  style={{
                    width: '100%',
                    padding: '16px 20px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    backgroundColor: 'transparent',
                    border: 'none',
                    color: 'var(--text-main, #24221f)',
                    fontSize: '0.95rem',
                    fontWeight: '600',
                    textAlign: 'left',
                    cursor: 'pointer'
                  }}
                >
                  <span>{faq.q}</span>
                  <span style={{ fontSize: '1.1rem', color: 'var(--primary, #da7756)', transform: isOpen ? 'rotate(45deg)' : 'none', transition: 'transform 0.2s' }}>
                    +
                  </span>
                </button>
                {isOpen && (
                  <div style={{ padding: '0 20px 16px', color: 'var(--text-muted, #666560)', fontSize: '0.85rem', lineHeight: '1.6' }}>
                    {faq.a}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* --- 9. Clean Minimalist Bottom CTA --- */}
      <section style={{
        padding: '70px 24px 80px',
        maxWidth: '860px',
        margin: '0 auto',
        textAlign: 'center'
      }}>
        <div style={{
          padding: '48px 32px',
          borderRadius: '16px',
          backgroundColor: 'var(--bg-card, #ffffff)',
          border: '1px solid var(--border-color, #e6e4dc)',
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.03)'
        }}>
          <h2 style={{ fontSize: '2.2rem', fontWeight: '800', letterSpacing: '-0.02em', margin: '0 0 12px', color: 'var(--text-main, #24221f)' }}>
            Ready to Automate Your Collections?
          </h2>
          <p style={{ fontSize: '1rem', color: 'var(--text-muted, #666560)', maxWidth: '500px', margin: '0 auto 28px' }}>
            Recover overdue invoices seamlessly with AI-powered negotiation and instant Razorpay settlements.
          </p>

          <button
            onClick={onSignIn}
            style={{
              padding: '13px 36px',
              borderRadius: '8px',
              backgroundColor: 'var(--primary, #da7756)',
              color: '#FFF',
              border: 'none',
              fontWeight: '600',
              fontSize: '1rem',
              cursor: 'pointer',
              boxShadow: '0 4px 14px rgba(218, 119, 86, 0.25)'
            }}
            onMouseOver={(e) => e.currentTarget.style.backgroundColor = 'var(--primary-hover, #c46445)'}
            onMouseOut={(e) => e.currentTarget.style.backgroundColor = 'var(--primary, #da7756)'}
          >
            Sign In to Workspace →
          </button>
        </div>
      </section>

      {/* --- 10. Minimalist Footer --- */}
      <footer style={{
        borderTop: '1px solid var(--border-color, #e6e4dc)',
        padding: '28px 36px',
        backgroundColor: 'var(--bg-dark, #f2f0e9)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '14px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontWeight: '700', color: 'var(--text-main, #24221f)' }}>Resolve.ai</span>
          <span style={{ color: 'var(--text-muted, #666560)', fontSize: '0.8rem' }}>© 2026 ResolveAI • Built for Razorpay & WhatsApp Cloud</span>
        </div>
        <div style={{ display: 'flex', gap: '18px', fontSize: '0.82rem', color: 'var(--text-muted, #666560)' }}>
          <a href="#how-it-works" style={{ color: 'inherit', textDecoration: 'none' }}>How It Works</a>
          <a href="#guardrails" style={{ color: 'inherit', textDecoration: 'none' }}>Guardrails</a>
          <a href="#calculator" style={{ color: 'inherit', textDecoration: 'none' }}>ROI Calculator</a>
          <button onClick={onSignIn} style={{ background: 'none', border: 'none', color: 'var(--primary, #da7756)', cursor: 'pointer', fontWeight: '600' }}>Sign In</button>
        </div>
      </footer>
    </div>
  );
}
