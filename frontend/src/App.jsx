import React, { useState, useEffect, useRef } from 'react';
import './index.css';

const API_BASE = 'http://localhost:8000';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' | 'guardrails' | 'simulator'
  
  // Data states
  const [invoices, setInvoices] = useState([]);
  const [guardrails, setGuardrails] = useState({
    min_partial_payment_pct: 30,
    max_extension_days: 14,
    max_split_installments: 3,
    auto_discount_waiver_pct: 5,
    tone: 'professional_empathetic'
  });
  const [analytics, setAnalytics] = useState({
    total_overdue_tpv_inr: 0,
    recovered_tpv_inr: 0,
    remaining_overdue_tpv_inr: 0,
    recovery_rate_pct: 0,
    active_negotiations_count: 0
  });

  // Simulator states
  const [selectedInvoiceId, setSelectedInvoiceId] = useState('inv_SME_001');
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [agentTrace, setAgentTrace] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);

  // Create Bill Modal States
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [newBillData, setNewBillData] = useState({
    customer_name: '',
    customer_phone: '',
    original_amount_inr: '',
    due_date: new Date().toISOString().split('T')[0]
  });

  const chatScrollRef = useRef(null);

  // Fetch initial data
  const fetchData = async () => {
    try {
      const [invRes, guardRes, anaRes] = await Promise.all([
        fetch(`${API_BASE}/api/invoices`),
        fetch(`${API_BASE}/api/guardrails`),
        fetch(`${API_BASE}/api/analytics`)
      ]);
      if (invRes.ok) setInvoices(await invRes.json());
      if (guardRes.ok) setGuardrails(await guardRes.json());
      if (anaRes.ok) setAnalytics(await anaRes.json());
    } catch (err) {
      console.error('API Fetch error:', err);
    }
  };

  useEffect(() => {
    fetchData();

    // Setup Real-time SSE Stream
    const eventSource = new EventSource(`${API_BASE}/api/events`);
    
    eventSource.onopen = () => setSseConnected(true);

    eventSource.onmessage = (e) => {
      try {
        const payload = JSON.parse(e.data);
        if (payload.type === 'connected') {
          setSseConnected(true);
        } else if (payload.type === 'payment_reconciled') {
          fetchData();
          if (selectedInvoice) {
            fetchChatHistory(selectedInvoice);
          }
        } else if (payload.type === 'guardrails_updated') {
          setGuardrails(payload.data);
        } else if (payload.type === 'chat_message_processed') {
          if (payload.data.trace) {
            setAgentTrace(payload.data.trace);
          }
          fetchData();
        }
      } catch (err) {
        console.error('SSE Error parsing:', err);
      }
    };

    eventSource.onerror = () => {
      setSseConnected(false);
    };

    return () => {
      eventSource.close();
    };
  }, []);

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTop = chatScrollRef.current.scrollHeight;
    }
  }, [chatMessages]);

  const selectedInvoice = invoices.find(i => i.invoice_id === selectedInvoiceId) || invoices[0];

  // Fetch chat history for selected invoice
  const fetchChatHistory = async (inv) => {
    if (!inv) return;
    try {
      const res = await fetch(`${API_BASE}/api/chat/history?invoice_id=${inv.invoice_id}&customer_phone=${encodeURIComponent(inv.customer_phone)}`);
      if (res.ok) {
        const data = await res.json();
        setChatMessages(data.messages || []);
      }
    } catch (err) {
      console.error('Error fetching chat history:', err);
    }
  };

  useEffect(() => {
    if (selectedInvoice) {
      fetchChatHistory(selectedInvoice);
    }
  }, [selectedInvoiceId, invoices.length]);

  // Send message to simulator
  const handleSendMessage = async (customText = null) => {
    const textToSend = customText || inputMessage;
    if (!textToSend.trim() || !selectedInvoice || isSending) return;

    const currentInv = selectedInvoice;
    const session_id = `${currentInv.customer_phone}_${currentInv.invoice_id}`;

    // Add user message locally
    const newMsg = { sender: 'user', text: textToSend, timestamp: new Date().toLocaleTimeString() };
    setChatMessages(prev => [...prev, newMsg]);
    if (!customText) setInputMessage('');
    setIsSending(true);

    try {
      const res = await fetch(`${API_BASE}/api/chat/message`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id,
          invoice_id: currentInv.invoice_id,
          customer_phone: currentInv.customer_phone,
          message: textToSend
        })
      });

      if (res.ok) {
        const data = await res.json();
        setChatMessages(prev => [
          ...prev,
          { sender: 'agent', text: data.response_text, timestamp: new Date().toLocaleTimeString(), trace: data.trace }
        ]);
        if (data.trace) {
          setAgentTrace(data.trace);
        }
      }
    } catch (err) {
      console.error('Chat error:', err);
    } finally {
      setIsSending(false);
    }
  };

  // Create bill submission handler
  const handleCreateBill = async (e) => {
    e.preventDefault();
    if (!newBillData.customer_name || !newBillData.customer_phone || !newBillData.original_amount_inr) {
      alert('Please fill out all fields.');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/invoices`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_name: newBillData.customer_name,
          customer_phone: newBillData.customer_phone,
          original_amount_inr: parseFloat(newBillData.original_amount_inr),
          due_date: newBillData.due_date
        })
      });

      if (res.ok) {
        const createdInv = await res.json();
        setIsCreateModalOpen(false);
        setNewBillData({
          customer_name: '',
          customer_phone: '',
          original_amount_inr: '',
          due_date: new Date().toISOString().split('T')[0]
        });
        fetchData();
        alert(`Bill '${createdInv.invoice_id}' created successfully for ${createdInv.customer_name}!`);
      }
    } catch (err) {
      alert('Failed to create bill: ' + err.message);
    }
  };

  // Razorpay Standard Web Checkout Modal Handler
  const handleRazorpayCheckout = async (inv) => {
    if (!inv || inv.remaining_amount_paise < 100) {
      alert("Invoice remaining amount must be at least ₹1.00 (100 paise).");
      return;
    }

    try {
      // 1. Call Backend POST /api/create-order
      const orderRes = await fetch(`${API_BASE}/api/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount_in_paise: inv.remaining_amount_paise,
          invoice_id: inv.invoice_id,
          receipt: `rcpt_${inv.invoice_id}_${Date.now()}`
        })
      });

      if (!orderRes.ok) {
        const errData = await orderRes.json();
        throw new Error(errData.detail || "Failed to create checkout order.");
      }

      const orderData = await orderRes.json();
      const razorpayKey = import.meta.env.VITE_RAZORPAY_KEY_ID || 'rzp_test_TSnypXFHb8t7Sc';

      // 2. Open Razorpay Checkout Modal
      const options = {
        key: razorpayKey,
        amount: orderData.amount,
        currency: orderData.currency || 'INR',
        name: 'Resolve.ai SME Collections',
        description: `Payment for Invoice ${inv.invoice_id}`,
        image: 'https://razorpay.com/favicon.ico',
        order_id: orderData.order_id,
        handler: async (response) => {
          // 3. On Payment Success -> Send signatures to Backend POST /api/verify-payment
          try {
            const verifyRes = await fetch(`${API_BASE}/api/verify-payment`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                razorpay_order_id: response.razorpay_order_id,
                razorpay_payment_id: response.razorpay_payment_id,
                razorpay_signature: response.razorpay_signature,
                invoice_id: inv.invoice_id
              })
            });

            if (verifyRes.ok) {
              alert(`🎉 Payment Verified Successfully!\nPayment ID: ${response.razorpay_payment_id}`);
              fetchData();
              fetchChatHistory(inv);
            } else {
              const verifyErr = await verifyRes.json();
              alert(`⚠️ Payment Verification Failed: ${verifyErr.detail || "Signature Mismatch"}`);
            }
          } catch (verifyError) {
            alert(`⚠️ Error verifying payment: ${verifyError.message}`);
          }
        },
        prefill: {
          name: inv.customer_name,
          contact: inv.customer_phone,
          email: 'customer@example.com'
        },
        theme: {
          color: '#3B82F6'
        },
        modal: {
          ondismiss: () => {
            console.log("User cancelled Razorpay checkout modal.");
          }
        }
      };

      if (window.Razorpay) {
        const rzp = new window.Razorpay(options);
        rzp.on('payment.failed', (resp) => {
          alert(`❌ Payment Failed: ${resp.error.description || "Transaction failed"}`);
        });
        rzp.open();
      } else {
        alert("Razorpay SDK not loaded. Please refresh the page.");
      }

    } catch (err) {
      alert(`Checkout Error: ${err.message}`);
    }
  };

  // Guardrail save handler
  const handleSaveGuardrails = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/guardrails`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(guardrails)
      });
      if (res.ok) {
        const updated = await res.json();
        setGuardrails(updated);
        alert('Merchant Guardrail Policy updated successfully!');
      }
    } catch (err) {
      alert('Failed to update guardrails: ' + err.message);
    }
  };

  const getStatusBadge = (status) => {
    switch (status) {
      case 'PAID':
        return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success)' }}>PAID</span>;
      case 'PARTIALLY_PAID':
        return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: 'var(--primary)', border: '1px solid var(--primary)' }}>PARTIALLY PAID</span>;
      case 'NEGOTIATING':
        return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--warning-bg)', color: 'var(--warning)', border: '1px solid var(--warning)' }}>NEGOTIATING</span>;
      default:
        return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger)' }}>UNPAID</span>;
    }
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      
      {/* Top Navbar */}
      <header style={{ height: '70px', borderBottom: '1px solid var(--border-color)', background: 'rgba(9, 13, 22, 0.85)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', position: 'sticky', top: 0, zIndex: 100 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{ width: '40px', height: '40px', borderRadius: '10px', background: 'linear-gradient(135deg, #0066FF 0%, #6366F1 100%)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '800', fontSize: '1.2rem', color: '#FFF' }}>
            R
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="brand-font" style={{ fontSize: '1.3rem', fontWeight: '700', color: '#FFF' }}>Resolve.ai</span>
              <span style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '12px', background: 'rgba(0, 102, 255, 0.2)', color: '#60A5FA', border: '1px solid rgba(0, 102, 255, 0.4)', fontWeight: '600' }}>
                Razorpay SME Agent
              </span>
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Autonomous Guardrail-Constrained Collections</p>
          </div>
        </div>

        {/* Tab Buttons */}
        <div style={{ display: 'flex', gap: '8px', background: 'rgba(17, 24, 39, 0.6)', padding: '4px', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
          <button
            onClick={() => setActiveTab('dashboard')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'dashboard' ? 'var(--primary)' : 'transparent', color: activeTab === 'dashboard' ? '#FFF' : 'var(--text-muted)' }}
          >
            📊 Invoices & Analytics
          </button>
          <button
            onClick={() => setActiveTab('guardrails')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'guardrails' ? 'var(--primary)' : 'transparent', color: activeTab === 'guardrails' ? '#FFF' : 'var(--text-muted)' }}
          >
            🛡️ Guardrail Policies
          </button>
          <button
            onClick={() => setActiveTab('simulator')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'simulator' ? 'var(--primary)' : 'transparent', color: activeTab === 'simulator' ? '#FFF' : 'var(--text-muted)' }}
          >
            💬 WhatsApp Simulator & AI Trace
          </button>
        </div>

        {/* SSE Connection Status Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.8rem', color: sseConnected ? 'var(--success)' : 'var(--text-dim)' }}>
          <div className="live-indicator" style={{ backgroundColor: sseConnected ? 'var(--success)' : 'var(--text-dim)' }}></div>
          <span>{sseConnected ? 'Real-Time SSE Connected' : 'Disconnected'}</span>
        </div>
      </header>

      {/* Main Content Body */}
      <main style={{ flex: 1, padding: '32px', maxWidth: '1400px', margin: '0 auto', width: '100%' }}>
        
        {/* TAB 1: INVOICES & ANALYTICS DASHBOARD */}
        {activeTab === 'dashboard' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            
            {/* Analytics Overview Cards */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px' }}>
              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Total Overdue TPV</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: '#FFF' }}>₹{analytics.total_overdue_tpv_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Across 3 SME Invoices</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Recovered TPV</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--success)' }}>₹{analytics.recovered_tpv_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--success)', marginTop: '6px' }}>Verified via Razorpay Webhooks</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Recovery Rate</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: '#60A5FA' }}>{analytics.recovery_rate_pct}%</h3>
                <div style={{ height: '6px', background: 'rgba(255,255,255,0.1)', borderRadius: '3px', marginTop: '12px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${analytics.recovery_rate_pct}%`, background: 'linear-gradient(90deg, #3B82F6, #10B981)', borderRadius: '3px' }}></div>
                </div>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Active Negotiations</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--warning)' }}>{analytics.active_negotiations_count}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Automated AI Sessions</p>
              </div>
            </div>

            {/* Master Invoices Table */}
            <div className="glass-panel" style={{ padding: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                  <h2 style={{ fontSize: '1.2rem', fontWeight: '700', color: '#FFF' }}>Master Overdue Invoices</h2>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>Real-time balance tracking with integer paise accuracy</p>
                </div>
                <button
                  onClick={() => setIsCreateModalOpen(true)}
                  style={{
                    padding: '10px 18px',
                    borderRadius: '10px',
                    background: 'linear-gradient(135deg, #0066FF 0%, #6366F1 100%)',
                    color: '#FFF',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: '700',
                    fontSize: '0.88rem',
                    boxShadow: '0 4px 12px rgba(0, 102, 255, 0.3)'
                  }}
                >
                  + Add New Bill / Invoice
                </button>
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                    <th style={{ padding: '12px 16px' }}>INVOICE ID</th>
                    <th style={{ padding: '12px 16px' }}>CUSTOMER / SME</th>
                    <th style={{ padding: '12px 16px' }}>PHONE</th>
                    <th style={{ padding: '12px 16px' }}>ORIGINAL AMOUNT</th>
                    <th style={{ padding: '12px 16px' }}>REMAINING BALANCE</th>
                    <th style={{ padding: '12px 16px' }}>STATUS</th>
                    <th style={{ padding: '12px 16px', textAlign: 'right' }}>ACTION</th>
                  </tr>
                </thead>
                <tbody>
                  {invoices.map((inv) => (
                    <tr key={inv.invoice_id} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding: '16px', fontFamily: 'monospace', fontWeight: '600', color: '#60A5FA' }}>{inv.invoice_id}</td>
                      <td style={{ padding: '16px', fontWeight: '600', color: '#FFF' }}>{inv.customer_name}</td>
                      <td style={{ padding: '16px', color: 'var(--text-muted)' }}>{inv.customer_phone}</td>
                      <td style={{ padding: '16px', color: '#FFF' }}>₹{inv.original_amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                      <td style={{ padding: '16px', fontWeight: '700', color: inv.remaining_amount_inr === 0 ? 'var(--success)' : '#F9FAFB' }}>
                        ₹{inv.remaining_amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                      </td>
                      <td style={{ padding: '16px' }}>{getStatusBadge(inv.status)}</td>
                      <td style={{ padding: '16px', textAlign: 'right', display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                        {inv.remaining_amount_inr > 0 && (
                          <button
                            onClick={() => handleRazorpayCheckout(inv)}
                            style={{
                              padding: '6px 14px',
                              borderRadius: '8px',
                              border: '1px solid rgba(16, 185, 129, 0.4)',
                              background: 'rgba(16, 185, 129, 0.15)',
                              color: 'var(--success)',
                              cursor: 'pointer',
                              fontSize: '0.8rem',
                              fontWeight: '600'
                            }}
                          >
                            Pay via Razorpay 💳
                          </button>
                        )}
                        <button
                          onClick={() => {
                            setSelectedInvoiceId(inv.invoice_id);
                            setActiveTab('simulator');
                          }}
                          style={{ padding: '6px 14px', borderRadius: '8px', border: '1px solid var(--border-glow)', background: 'rgba(59, 130, 246, 0.15)', color: '#60A5FA', cursor: 'pointer', fontSize: '0.8rem', fontWeight: '600' }}
                        >
                          Negotiate 💬
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

          </div>
        )}

        {/* TAB 2: MERCHANT GUARDRAIL POLICIES */}
        {activeTab === 'guardrails' && (
          <div style={{ maxWidth: '800px', margin: '0 auto' }}>
            <div className="glass-panel" style={{ padding: '32px' }}>
              <div style={{ marginBottom: '28px' }}>
                <h2 style={{ fontSize: '1.4rem', fontWeight: '700', color: '#FFF' }}>Merchant Guardrail Policies</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Set rigid mathematical boundaries that the LLM agent cannot override.
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                
                {/* Min Partial Payment Pct */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <label style={{ fontSize: '0.9rem', fontWeight: '600', color: '#FFF' }}>Minimum Initial Partial Payment (%)</label>
                    <span style={{ fontSize: '0.9rem', fontWeight: '700', color: 'var(--primary)' }}>{guardrails.min_partial_payment_pct}%</span>
                  </div>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    step="5"
                    value={guardrails.min_partial_payment_pct}
                    onChange={(e) => setGuardrails({ ...guardrails, min_partial_payment_pct: parseFloat(e.target.value) })}
                    style={{ width: '100%', accentColor: 'var(--primary)' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '4px' }}>Proposals requesting lower initial payments will be automatically rejected with counter-offers.</p>
                </div>

                {/* Max Extension Days */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <label style={{ fontSize: '0.9rem', fontWeight: '600', color: '#FFF' }}>Maximum Allowed Due Date Extension (Days)</label>
                    <span style={{ fontSize: '0.9rem', fontWeight: '700', color: 'var(--indigo)' }}>{guardrails.max_extension_days} Days</span>
                  </div>
                  <input
                    type="range"
                    min="1"
                    max="180"
                    step="1"
                    value={guardrails.max_extension_days}
                    onChange={(e) => setGuardrails({ ...guardrails, max_extension_days: parseInt(e.target.value) })}
                    style={{ width: '100%', accentColor: 'var(--indigo)' }}
                  />
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '4px' }}>Hard-capped at 180 days by Razorpay platform limit.</p>
                </div>

                {/* Negotiation Tone */}
                <div>
                  <label style={{ fontSize: '0.9rem', fontWeight: '600', color: '#FFF', display: 'block', marginBottom: '8px' }}>Negotiation Persona & Tone</label>
                  <select
                    value={guardrails.tone}
                    onChange={(e) => setGuardrails({ ...guardrails, tone: e.target.value })}
                    style={{ width: '100%', padding: '12px', borderRadius: '8px', background: 'rgba(17, 24, 39, 0.9)', border: '1px solid var(--border-color)', color: '#FFF', fontSize: '0.9rem' }}
                  >
                    <option value="professional_empathetic">Professional & Empathetic (Recommended)</option>
                    <option value="firm_compliance">Firm & Compliance Oriented</option>
                    <option value="flexible_sme_partner">Flexible SME Growth Partner</option>
                  </select>
                </div>

                {/* Save Button */}
                <button
                  onClick={handleSaveGuardrails}
                  style={{ marginTop: '12px', padding: '14px', borderRadius: '10px', background: 'linear-gradient(135deg, #3B82F6 0%, #6366F1 100%)', color: '#FFF', border: 'none', cursor: 'pointer', fontWeight: '700', fontSize: '0.95rem' }}
                >
                  Save Guardrail Policy
                </button>

              </div>
            </div>
          </div>
        )}

        {/* TAB 3: WHATSAPP SIMULATOR & AGENT TRACE */}
        {activeTab === 'simulator' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', minHeight: '650px' }}>
            
            {/* Left: WhatsApp Interface Simulator */}
            <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
              
              {/* WhatsApp Header */}
              <div style={{ padding: '16px 20px', background: '#075E54', color: '#FFF', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ width: '38px', height: '38px', borderRadius: '50%', background: '#128C7E', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '1.1rem' }}>
                    💬
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1rem', fontWeight: '600' }}>WhatsApp Simulator</h3>
                    <p style={{ fontSize: '0.75rem', opacity: 0.8 }}>Resolving {selectedInvoice?.customer_name}</p>
                  </div>
                </div>

                {/* Customer Invoice Switcher */}
                <select
                  value={selectedInvoiceId}
                  onChange={(e) => setSelectedInvoiceId(e.target.value)}
                  style={{ padding: '6px 12px', borderRadius: '6px', border: 'none', background: 'rgba(255,255,255,0.2)', color: '#FFF', fontSize: '0.8rem', fontWeight: '600' }}
                >
                  {invoices.map(i => (
                    <option key={i.invoice_id} value={i.invoice_id} style={{ color: '#000' }}>
                      {i.customer_name} (₹{i.remaining_amount_inr})
                    </option>
                  ))}
                </select>
              </div>

              {/* Chat Bubble Area */}
              <div ref={chatScrollRef} style={{ flex: 1, padding: '20px', background: '#0B141A', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                
                {/* Invoice Context Banner */}
                <div style={{ background: '#182229', padding: '12px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.06)', fontSize: '0.8rem', color: '#8696A0', textAlign: 'center' }}>
                  📌 Active Invoice: <strong style={{ color: '#FFF' }}>{selectedInvoice?.invoice_id}</strong> | Outstanding Balance: <strong style={{ color: '#00A884' }}>₹{selectedInvoice?.remaining_amount_inr?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong>
                </div>

                {chatMessages.length === 0 && (
                  <div style={{ textAlign: 'center', color: '#8696A0', fontSize: '0.85rem', margin: 'auto 0' }}>
                    Type a message below or click a proposal preset to simulate a negotiation session on WhatsApp!
                  </div>
                )}

                {chatMessages.map((msg, index) => (
                  <div
                    key={index}
                    style={{
                      maxWidth: '80%',
                      alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                      background: msg.sender === 'user' ? '#005C4B' : '#202C33',
                      color: '#E9EDEF',
                      padding: '10px 14px',
                      borderRadius: '10px',
                      fontSize: '0.88rem',
                      lineHeight: '1.4',
                      boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
                      whiteSpace: 'pre-line'
                    }}
                  >
                    {msg.text}

                    {/* Interactive Payment Button inside Chat Bubble when payment link is generated */}
                    {msg.sender === 'agent' && (msg.text.includes('https://rzp.io/') || msg.text.includes('payment link')) && selectedInvoice && selectedInvoice.remaining_amount_inr > 0 && (
                      <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid rgba(255,255,255,0.1)' }}>
                        <button
                          onClick={() => handleRazorpayCheckout(selectedInvoice)}
                          style={{
                            width: '100%',
                            padding: '8px 14px',
                            borderRadius: '6px',
                            background: 'linear-gradient(135deg, #10B981 0%, #059669 100%)',
                            color: '#FFF',
                            border: 'none',
                            fontWeight: '700',
                            fontSize: '0.82rem',
                            cursor: 'pointer',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            gap: '6px',
                            boxShadow: '0 2px 8px rgba(16, 185, 129, 0.4)'
                          }}
                        >
                          💳 Pay Now via Razorpay (Test Mode)
                        </button>
                      </div>
                    )}

                    <div style={{ fontSize: '0.65rem', color: '#8696A0', textAlign: 'right', marginTop: '4px' }}>
                      {msg.timestamp}
                    </div>
                  </div>
                ))}

              </div>

              {/* Quick Preset Proposal Action Buttons */}
              <div style={{ padding: '10px 16px', background: '#111B21', borderTop: '1px solid rgba(255,255,255,0.06)', display: 'flex', gap: '8px', overflowX: 'auto' }}>
                <button
                  onClick={() => handleSendMessage("Can I pay 40% today and the rest next week?")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: '#202C33', border: '1px solid rgba(255,255,255,0.1)', color: '#00A884', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  ⚡ Propose 40% Today
                </button>
                <button
                  onClick={() => handleSendMessage("Can I extend the payment due date by 14 days?")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: '#202C33', border: '1px solid rgba(255,255,255,0.1)', color: '#60A5FA', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  📅 Request 14-Day Extension
                </button>
                <button
                  onClick={() => handleSendMessage("I can only pay 10% right now")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: '#202C33', border: '1px solid rgba(255,255,255,0.1)', color: '#EF4444', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  ⚠️ Lowball 10% Offer
                </button>
                <button
                  onClick={() => handleSendMessage("I have transferred 50000 via UPI")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: '#202C33', border: '1px solid rgba(255,255,255,0.1)', color: '#F59E0B', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  💳 Claim "Paid via UPI"
                </button>
              </div>

              {/* Chat Input Bar */}
              <div style={{ padding: '12px 16px', background: '#202C33', display: 'flex', gap: '10px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="Type a proposal message..."
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  style={{ flex: 1, padding: '10px 14px', borderRadius: '8px', background: '#2A3942', border: 'none', color: '#FFF', fontSize: '0.88rem' }}
                />
                <button
                  onClick={() => handleSendMessage()}
                  disabled={isSending}
                  style={{ padding: '10px 18px', borderRadius: '8px', background: '#00A884', color: '#FFF', border: 'none', cursor: 'pointer', fontWeight: '700', fontSize: '0.88rem' }}
                >
                  {isSending ? '...' : 'Send'}
                </button>
              </div>

            </div>

            {/* Right: Inspectable Real-Time Agent Trace Log */}
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: '700', color: '#FFF', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>🔍 Inspectable Agent Trace Log</span>
                </h3>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>Real-time audit step visualization for fintech safety</p>
              </div>

              {!agentTrace ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-dim)', fontSize: '0.85rem', textAlign: 'center', border: '1px dashed var(--border-color)', borderRadius: '12px' }}>
                  Send a message in the WhatsApp simulator to inspect real-time agent reasoning, guardrail evaluation, and integer paise currency conversions!
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, overflowY: 'auto' }}>
                  
                  {/* 1. Strategy & Thought */}
                  <div style={{ background: 'rgba(17, 24, 39, 0.9)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: '700', color: '#60A5FA', textTransform: 'uppercase', marginBottom: '4px' }}>🧠 Strategy & Reasoning Thought</div>
                    <p style={{ fontSize: '0.85rem', color: '#F3F4F6' }}>{agentTrace.thought}</p>
                  </div>

                  {/* 2. Guardrail Check Status */}
                  <div style={{ background: 'rgba(17, 24, 39, 0.9)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: '700', color: '#A5B4FC', textTransform: 'uppercase' }}>🛡️ Guardrail Engine Gateway</span>
                      <span style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '700', backgroundColor: agentTrace.guardrail_check.status === 'PASS' ? 'var(--success-bg)' : 'var(--danger-bg)', color: agentTrace.guardrail_check.status === 'PASS' ? 'var(--success)' : 'var(--danger)', border: `1px solid ${agentTrace.guardrail_check.status === 'PASS' ? 'var(--success)' : 'var(--danger)'}` }}>
                        {agentTrace.guardrail_check.status}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{agentTrace.guardrail_check.reason || "All merchant guardrails satisfied."}</p>
                  </div>

                  {/* 3. Integer Paise Currency Audit */}
                  {agentTrace.currency_conversion?.approved_amount_inr && (
                    <div style={{ background: 'rgba(17, 24, 39, 0.9)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: '700', color: '#F59E0B', textTransform: 'uppercase', marginBottom: '6px' }}>💱 Currency Math Audit (Zero Float Drift)</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>INR Rupee Amount:</span>
                        <strong style={{ color: '#FFF' }}>₹{agentTrace.currency_conversion.approved_amount_inr?.toLocaleString('en-IN')}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginTop: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Integer Paise Storage:</span>
                        <strong style={{ color: 'var(--success)', fontFamily: 'monospace' }}>{agentTrace.currency_conversion.approved_amount_paise} paise</strong>
                      </div>
                    </div>
                  )}

                  {/* 4. Tool Execution & Payment Link */}
                  <div style={{ background: 'rgba(17, 24, 39, 0.9)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: '700', color: '#C084FC', textTransform: 'uppercase', marginBottom: '6px' }}>⚡ Tool Execution & Idempotency</div>
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                      Tool: <strong style={{ color: '#FFF' }}>{agentTrace.tool_executed || 'None (Counter-offer issued)'}</strong>
                    </div>
                    {agentTrace.payment_link_url && (
                      <div style={{ marginTop: '10px', padding: '10px', background: 'rgba(0, 102, 255, 0.15)', borderRadius: '8px', border: '1px solid rgba(0, 102, 255, 0.4)' }}>
                        <div style={{ fontSize: '0.75rem', color: '#60A5FA', fontWeight: '600' }}>Generated Razorpay Link:</div>
                        <a href={agentTrace.payment_link_url} target="_blank" rel="noreferrer" style={{ fontSize: '0.85rem', color: '#FFF', fontWeight: '700', textDecoration: 'underline', wordBreak: 'break-all' }}>
                          {agentTrace.payment_link_url}
                        </a>
                      </div>
                    )}
                  </div>

                </div>
              )}

            </div>

          </div>
        )}

      </main>

      {/* CREATE NEW BILL MODAL */}
      {isCreateModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.75)',
          backdropFilter: 'blur(8px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div className="glass-panel" style={{
            width: '100%',
            maxWidth: '520px',
            padding: '32px',
            borderRadius: '20px',
            background: 'rgba(15, 23, 42, 0.95)',
            border: '1px solid rgba(255, 255, 255, 0.15)',
            boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.7)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <div>
                <h2 style={{ fontSize: '1.3rem', fontWeight: '700', color: '#FFF' }}>Add New Bill / Invoice</h2>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '2px' }}>Enter SME customer bill details for automated AI collection</p>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '1.4rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateBill} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: '#E2E8F0', marginBottom: '6px' }}>
                  Customer / SME Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Rajesh Enterprises"
                  value={newBillData.customer_name}
                  onChange={(e) => setNewBillData({ ...newBillData, customer_name: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    background: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid var(--border-color)',
                    color: '#FFF',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: '#E2E8F0', marginBottom: '6px' }}>
                  WhatsApp Phone Number *
                </label>
                <input
                  type="text"
                  placeholder="e.g. +919812345678"
                  value={newBillData.customer_phone}
                  onChange={(e) => setNewBillData({ ...newBillData, customer_phone: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    background: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid var(--border-color)',
                    color: '#FFF',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: '#E2E8F0', marginBottom: '6px' }}>
                  Original Invoice Amount (₹ INR) *
                </label>
                <input
                  type="number"
                  placeholder="e.g. 75000"
                  step="0.01"
                  value={newBillData.original_amount_inr}
                  onChange={(e) => setNewBillData({ ...newBillData, original_amount_inr: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    background: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid var(--border-color)',
                    color: '#FFF',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: '#E2E8F0', marginBottom: '6px' }}>
                  Payment Due Date *
                </label>
                <input
                  type="date"
                  value={newBillData.due_date}
                  onChange={(e) => setNewBillData({ ...newBillData, due_date: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '12px 14px',
                    borderRadius: '8px',
                    background: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid var(--border-color)',
                    color: '#FFF',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
                <button
                  type="button"
                  onClick={() => setIsCreateModalOpen(false)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    background: 'rgba(255, 255, 255, 0.05)',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontWeight: '600'
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  style={{
                    flex: 2,
                    padding: '12px',
                    borderRadius: '8px',
                    background: 'linear-gradient(135deg, #0066FF 0%, #6366F1 100%)',
                    color: '#FFF',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: '700',
                    boxShadow: '0 4px 12px rgba(0, 102, 255, 0.3)'
                  }}
                >
                  Create Invoice Bill
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
