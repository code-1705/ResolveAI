import React, { useState, useEffect, useRef, useMemo } from 'react';
import './index.css';

const API_BASE = 'http://localhost:8000';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard'); // 'dashboard' | 'guardrails' | 'simulator'
  const [activeCategory, setActiveCategory] = useState('OVERDUE');
  
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
  const [selectedPhone, setSelectedPhone] = useState('');
  const [chatMessages, setChatMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [agentTrace, setAgentTrace] = useState(null);
  const [isSending, setIsSending] = useState(false);
  const [sseConnected, setSseConnected] = useState(false);

  // Edit Invoice Modal States
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [editingInvoice, setEditingInvoice] = useState({
    invoice_id: '',
    customer_name: '',
    customer_phone: '',
    due_date: '',
    remaining_amount_inr: 0,
    manual_payment_inr: ''
  });

  const handleOpenEditModal = (inv) => {
    setEditingInvoice({
      invoice_id: inv.invoice_id,
      customer_name: inv.customer_name,
      customer_phone: inv.customer_phone,
      due_date: inv.due_date,
      remaining_amount_inr: inv.remaining_amount_inr,
      manual_payment_inr: ''
    });
    setIsEditModalOpen(true);
  };

  const handleSaveEditInvoice = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/invoices/${editingInvoice.invoice_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          customer_name: editingInvoice.customer_name,
          customer_phone: editingInvoice.customer_phone,
          due_date: editingInvoice.due_date,
          manual_payment_inr: parseFloat(editingInvoice.manual_payment_inr || 0)
        })
      });

      if (res.ok) {
        setIsEditModalOpen(false);
        fetchData();
        showToast('Invoice updated successfully!', 'success');
      } else {
        const err = await res.json();
        showToast('Failed to update invoice.', 'error');
      }
    } catch (err) {
      alert('Error updating invoice: ' + err.message);
    }
  };

  // Create Bill Modal States
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractError, setExtractError] = useState(null);
  // Toast Notification System
  const [toast, setToast] = useState(null); // { message, type }

  const showToast = (message, type = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 4000);
  };

  const [newBillData, setNewBillData] = useState({
    customer_name: '',
    customer_phone: '',
    original_amount_inr: '',
    due_date: new Date().toISOString().split('T')[0],
    file_bytes_b64: null,
    file_name: null,
    file_mime_type: null
  });

  const chatScrollRef = useRef(null);

  const formatTime = (ts) => {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return ts;
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch {
      return ts;
    }
  };

  useEffect(() => {
    if (chatScrollRef.current) {
      chatScrollRef.current.scrollTo({
        top: chatScrollRef.current.scrollHeight,
        behavior: 'smooth'
      });
    }
  }, [chatMessages]);


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

  // Group Invoices by Customer Phone Number for Phone-Centric Account Simulator
  const customerAccounts = useMemo(() => {
    const groups = {};
    invoices.forEach(inv => {
      const phone = inv.customer_phone;
      if (!groups[phone]) {
        groups[phone] = {
          customer_name: inv.customer_name,
          customer_phone: phone,
          invoices: []
        };
      }
      groups[phone].invoices.push(inv);
    });
    return Object.values(groups);
  }, [invoices]);

  const activeCustomer = useMemo(() => {
    if (!customerAccounts.length) return null;
    return customerAccounts.find(c => c.customer_phone === selectedPhone) || customerAccounts[0];
  }, [customerAccounts, selectedPhone]);

  const selectedInvoice = activeCustomer?.invoices[0] || invoices[0];


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
    if (activeCustomer && activeCustomer.invoices.length > 0) {
      fetchChatHistory(activeCustomer.invoices[0]);
    }
  }, [selectedPhone, invoices, activeCustomer]); // Fix: re-fetch chat when invoice balance changes

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
          { sender: 'agent', text: data.response_text, timestamp: new Date().toLocaleTimeString(), trace: data.trace, metadata: data.metadata }
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
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setIsExtracting(true);
    setExtractError(null);
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/api/invoices/extract`, {
        method: 'POST',
        body: formData
      });
      const json = await res.json();
      if (json.success && json.data) {
        setNewBillData(prev => ({
          ...prev,
          customer_name: json.data.customer_name || prev.customer_name,
          customer_phone: json.data.customer_phone || prev.customer_phone,
          original_amount_inr: json.data.original_amount_inr !== undefined ? json.data.original_amount_inr : prev.original_amount_inr,
          due_date: json.data.due_date || prev.due_date,
          file_bytes_b64: json.file_bytes_b64 || null,
          file_name: json.file_name || null,
          file_mime_type: json.file_mime_type || null
        }));
        showToast('✨ Bill details extracted successfully!', 'success');
      } else {
        setExtractError(json.error || 'Could not extract bill details automatically.');
      }
    } catch (err) {
      setExtractError('Extraction timed out. You can manually enter bill details below.');
    } finally {
      setIsExtracting(false);
    }
  };

  const handleCreateBill = async (e) => {
    e.preventDefault();
    if (!newBillData.customer_name || !newBillData.customer_phone || !newBillData.original_amount_inr) {
      showToast('Please fill out all required fields.', 'error');
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
          due_date: newBillData.due_date,
          file_bytes_b64: newBillData.file_bytes_b64,
          file_name: newBillData.file_name,
          file_mime_type: newBillData.file_mime_type
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
        showToast('Merchant Guardrail Policy updated successfully!', 'success');
      }
    } catch (err) {
      showToast('Failed to update guardrails.', 'error');
    }
  };

  const getStatusBadge = (status, due_date) => {
    const today = new Date().toISOString().split('T')[0];
    const isPastDue = due_date && due_date < today && status !== 'PAID';

    if (status === 'PAID') {
      return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success)' }}>PAID</span>;
    }
    if (status === 'PARTIALLY_PAID') {
      return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: 'var(--primary)', border: '1px solid var(--primary)' }}>{isPastDue ? 'PARTIAL (OVERDUE)' : 'PARTIALLY PAID'}</span>;
    }
    if (status === 'NEGOTIATING') {
      return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--warning-bg)', color: 'var(--warning)', border: '1px solid var(--warning)' }}>NEGOTIATING</span>;
    }
    if (isPastDue) {
      return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'var(--danger-bg)', color: 'var(--danger)', border: '1px solid var(--danger)' }}>OVERDUE</span>;
    }
    return <span style={{ padding: '4px 10px', borderRadius: '20px', fontSize: '0.75rem', fontWeight: '600', backgroundColor: 'rgba(107, 114, 128, 0.15)', color: 'var(--text-muted)', border: '1px solid var(--border-color)' }}>UNPAID</span>;
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      
      {/* Top Navbar */}
      <header style={{ height: '70px', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-card)', backdropFilter: 'blur(12px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 32px', position: 'sticky', top: 0, zIndex: 100 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="brand-font" style={{ fontSize: '1.3rem', fontWeight: '700', color: 'var(--text-main)' }}>Resolve.ai</span>
              <span style={{ fontSize: '0.7rem', padding: '2px 8px', borderRadius: '12px', background: 'rgba(0, 102, 255, 0.2)', color: 'var(--primary)', border: '1px solid rgba(0, 102, 255, 0.4)', fontWeight: '600' }}>
                Razorpay SME Agent
              </span>
            </div>
            <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Autonomous Guardrail-Constrained Collections</p>
          </div>
        </div>

        {/* Tab Buttons */}
        <div style={{ display: 'flex', gap: '8px', background: 'var(--bg-dark)', padding: '4px', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
          <button
            onClick={() => setActiveTab('dashboard')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'dashboard' ? 'var(--text-main)' : 'transparent', color: activeTab === 'dashboard' ? '#FFF' : 'var(--text-muted)' }}
          >
            📊 Invoices & Analytics
          </button>
          <button
            onClick={() => setActiveTab('guardrails')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'guardrails' ? 'var(--text-main)' : 'transparent', color: activeTab === 'guardrails' ? '#FFF' : 'var(--text-muted)' }}
          >
            🛡️ Guardrail Policies
          </button>
          <button
            onClick={() => setActiveTab('simulator')}
            style={{ padding: '8px 18px', borderRadius: '8px', border: 'none', cursor: 'pointer', fontSize: '0.85rem', fontWeight: '600', transition: 'all 0.2s', background: activeTab === 'simulator' ? 'var(--text-main)' : 'transparent', color: activeTab === 'simulator' ? '#FFF' : 'var(--text-muted)' }}
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
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--text-main)' }}>₹{analytics.total_overdue_tpv_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Across 3 SME Invoices</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Recovered TPV</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--success)' }}>₹{analytics.recovered_tpv_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--success)', marginTop: '6px' }}>Verified via Razorpay Webhooks</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Recovery Rate</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--primary)' }}>{analytics.recovery_rate_pct}%</h3>
                <div style={{ height: '6px', background: 'var(--border-color)', borderRadius: '3px', marginTop: '12px', overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${analytics.recovery_rate_pct}%`, background: 'linear-gradient(90deg, var(--primary), var(--success))', borderRadius: '3px' }}></div>
                </div>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Active Negotiations</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--warning)' }}>{analytics.active_negotiations_count}</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Automated AI Sessions</p>
              </div>
            </div>

            {/* Master Invoices Table */}
            <div className="glass-panel" style={{ padding: '28px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
                <div>
                  <h2 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>Invoices</h2>
                  <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>Categorized real-time tracking of merchant collections</p>
                </div>
                <button
                  onClick={() => setIsCreateModalOpen(true)}
                  style={{
                    padding: '10px 18px',
                    borderRadius: '8px',
                    background: 'var(--text-main)',
                    color: '#FFF',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: '500',
                    fontSize: '0.88rem',
                    transition: 'background 0.2s',
                  }}
                  onMouseOver={(e) => e.target.style.background = '#403d39'}
                  onMouseOut={(e) => e.target.style.background = 'var(--text-main)'}
                >
                  + Create Invoice
                </button>
              </div>

              {/* Categorization Tabs */}
              <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px' }}>
                {[
                  { id: 'FLAGGED', label: 'Flagged / Attention' },
                  { id: 'OVERDUE', label: 'Unpaid & Overdue' },
                  { id: 'PARTIAL', label: 'Partially Paid' },
                  { id: 'PAID', label: 'Fully Paid' }
                ].map(tab => {
                  
                  // Compute counts dynamically
                  const count = tab.id === 'FLAGGED' ? invoices.filter(i => i.requires_human_attention).length :
                                tab.id === 'OVERDUE' ? invoices.filter(i => !i.requires_human_attention && i.status === 'UNPAID').length :
                                tab.id === 'PARTIAL' ? invoices.filter(i => !i.requires_human_attention && i.status === 'PARTIALLY_PAID').length :
                                invoices.filter(i => !i.requires_human_attention && i.status === 'PAID').length;

                  const isActive = activeCategory === tab.id;
                  
                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveCategory(tab.id)}
                      style={{
                        padding: '8px 16px',
                        borderRadius: '20px',
                        background: isActive ? (tab.id === 'FLAGGED' ? 'var(--danger)' : 'var(--text-main)') : 'transparent',
                        color: isActive ? '#FFF' : 'var(--text-muted)',
                        border: `1px solid ${isActive ? 'transparent' : 'var(--border-color)'}`,
                        cursor: 'pointer',
                        fontWeight: '500',
                        fontSize: '0.85rem',
                        transition: 'all 0.2s ease',
                      }}
                    >
                      {tab.label} <span style={{ opacity: 0.8, marginLeft: '4px', fontSize: '0.75rem' }}>({count})</span>
                    </button>
                  );
                })}
              </div>

              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '0.9rem' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)', fontSize: '0.8rem', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Invoice ID</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Customer</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Phone</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Due Date</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Original</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Remaining</th>
                    <th style={{ padding: '12px 16px', fontWeight: '600' }}>Status</th>
                    <th style={{ padding: '12px 16px', textAlign: 'right', fontWeight: '600' }}>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {(() => {
                    const displayed = activeCategory === 'FLAGGED' ? invoices.filter(i => i.requires_human_attention) :
                                      activeCategory === 'OVERDUE' ? invoices.filter(i => !i.requires_human_attention && i.status === 'UNPAID') :
                                      activeCategory === 'PARTIAL' ? invoices.filter(i => !i.requires_human_attention && i.status === 'PARTIALLY_PAID') :
                                      invoices.filter(i => !i.requires_human_attention && i.status === 'PAID');
                    
                    if (displayed.length === 0) {
                       return (
                         <tr>
                           <td colSpan="8" style={{ textAlign: 'center', padding: '40px', color: 'var(--text-muted)', fontStyle: 'italic' }}>
                             No invoices in this category.
                           </td>
                         </tr>
                       );
                    }

                    return displayed.map((inv) => (
                      <tr key={inv.invoice_id} style={{ borderBottom: '1px solid var(--border-color)', transition: 'background 0.2s' }} onMouseOver={(e) => e.currentTarget.style.background = 'rgba(0,0,0,0.02)'} onMouseOut={(e) => e.currentTarget.style.background = 'transparent'}>
                        <td style={{ padding: '16px', fontFamily: 'monospace', color: 'var(--text-dim)' }}>{inv.invoice_id}</td>
                        <td style={{ padding: '16px', fontWeight: '500', color: 'var(--text-main)' }}>{inv.customer_name}</td>
                        <td style={{ padding: '16px', color: 'var(--text-muted)' }}>{inv.customer_phone}</td>
                        <td style={{ padding: '16px', color: 'var(--text-muted)', fontWeight: '500' }}>{inv.due_date}</td>
                        <td style={{ padding: '16px', color: 'var(--text-dim)' }}>₹{inv.original_amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}</td>
                        <td style={{ padding: '16px', fontWeight: '600', color: inv.remaining_amount_inr === 0 ? 'var(--success)' : 'var(--text-main)' }}>
                          ₹{inv.remaining_amount_inr.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                        </td>
                        <td style={{ padding: '16px' }}>{getStatusBadge(inv.status, inv.due_date)}</td>
                        <td style={{ padding: '16px', textAlign: 'right' }}>
                          <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                            <button
                              onClick={() => {
                                setSelectedPhone(inv.customer_phone);
                                setActiveTab('simulator');
                              }}
                              title="Chat / WhatsApp Simulator"
                              style={{
                                padding: '8px 12px',
                                borderRadius: '8px',
                                border: '1px solid var(--border-color)',
                                background: '#FFF',
                                cursor: 'pointer',
                                fontSize: '1rem',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                transition: 'all 0.2s ease',
                              }}
                              onMouseOver={(e) => e.currentTarget.style.background = 'var(--bg-dark)'}
                              onMouseOut={(e) => e.currentTarget.style.background = '#FFF'}
                            >
                              💬
                            </button>
                            <button
                              onClick={() => handleOpenEditModal(inv)}
                              title="Edit Bill / Record Payment"
                              style={{
                                padding: '8px 12px',
                                borderRadius: '8px',
                                border: '1px solid var(--border-color)',
                                background: '#FFF',
                                cursor: 'pointer',
                                fontSize: '1rem',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                transition: 'all 0.2s ease',
                              }}
                              onMouseOver={(e) => e.currentTarget.style.background = 'var(--bg-dark)'}
                              onMouseOut={(e) => e.currentTarget.style.background = '#FFF'}
                            >
                              ✏️
                            </button>
                          </div>
                        </td>
                      </tr>
                    ));
                  })()}
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
                <h2 style={{ fontSize: '1.4rem', fontWeight: '700', color: 'var(--text-main)' }}>Merchant Guardrail Policies</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                  Set rigid mathematical boundaries that the LLM agent cannot override.
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                
                {/* Min Partial Payment Pct */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                    <label style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--text-main)' }}>Minimum Initial Partial Payment (%)</label>
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
                    <label style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--text-main)' }}>Maximum Allowed Due Date Extension (Days)</label>
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
                  <label style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--text-main)', display: 'block', marginBottom: '8px' }}>Negotiation Persona & Tone</label>
                  <select
                    value={guardrails.tone}
                    onChange={(e) => setGuardrails({ ...guardrails, tone: e.target.value })}
                    style={{ width: '100%', padding: '12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.9rem' }}
                  >
                    <option value="professional_empathetic">Professional & Empathetic (Recommended)</option>
                    <option value="firm_compliance">Firm & Compliance Oriented</option>
                    <option value="flexible_sme_partner">Flexible SME Growth Partner</option>
                  </select>
                </div>

                {/* Save Button */}
                <button
                  onClick={handleSaveGuardrails}
                  style={{ marginTop: '12px', padding: '14px', borderRadius: '10px', background: 'var(--text-main)', color: '#FFF', border: 'none', cursor: 'pointer', fontWeight: '700', fontSize: '0.95rem' }}
                >
                  Save Guardrail Policy
                </button>

              </div>
            </div>
          </div>
        )}

        {/* TAB 3: WHATSAPP SIMULATOR & AGENT TRACE */}
        {activeTab === 'simulator' && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', height: '640px' }}>
            
            {/* Left: WhatsApp Interface Simulator */}
            <div className="glass-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', borderRadius: '16px', overflow: 'hidden', background: '#FFFFFF', border: '1px solid var(--border-color)', boxShadow: '0 4px 12px rgba(0,0,0,0.03)' }}>
              
              {/* WhatsApp Header */}
              <div style={{ padding: '14px 20px', background: 'var(--bg-dark)', borderBottom: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ width: '38px', height: '38px', borderRadius: '50%', background: 'var(--text-main)', color: '#FFF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '1.1rem' }}>
                    💬
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1rem', fontWeight: '600', color: 'var(--text-main)' }}>WhatsApp Simulator</h3>
                    <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>Resolving {selectedInvoice?.customer_name}</p>
                  </div>
                </div>

                {/* Phone-Centric Customer Account Switcher */}
                <select
                  value={activeCustomer?.customer_phone || ''}
                  onChange={(e) => setSelectedPhone(e.target.value)}
                  style={{ padding: '6px 12px', borderRadius: '8px', border: '1px solid var(--border-color)', background: '#FFF', color: 'var(--text-main)', fontSize: '0.82rem', fontWeight: '600' }}
                >
                  {customerAccounts.map(c => {
                    const totalRem = c.invoices.reduce((sum, inv) => sum + (inv.status !== 'PAID' ? inv.remaining_amount_inr : 0), 0);
                    return (
                      <option key={c.customer_phone} value={c.customer_phone}>
                        {c.customer_name} ({c.customer_phone}) - {c.invoices.length} Bill(s) (₹{totalRem.toLocaleString('en-IN')})
                      </option>
                    );
                  })}
                </select>
              </div>

              {/* Customer Account Context Banner */}
              <div style={{ background: '#FFF', padding: '10px 16px', borderBottom: '1px solid var(--border-color)', fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                📌 Active Customer: <strong style={{ color: 'var(--text-main)' }}>{activeCustomer?.customer_name} ({activeCustomer?.customer_phone})</strong> | Total Balance: <strong style={{ color: 'var(--success)' }}>₹{(activeCustomer?.invoices || []).reduce((sum, inv) => sum + (inv.status !== 'PAID' ? inv.remaining_amount_inr : 0), 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</strong> ({activeCustomer?.invoices?.length || 0} Bills: {activeCustomer?.invoices?.map(i => i.invoice_id).join(', ')})
              </div>

              {/* Chat Bubble Area (Fixed Height with Auto-Scroll) */}
              <div ref={chatScrollRef} style={{ flex: 1, minHeight: 0, padding: '20px', background: '#F5F3ED', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                
                {chatMessages.length === 0 && (
                  <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', margin: 'auto 0' }}>
                    Type a message below or click a proposal preset to simulate a negotiation session on WhatsApp!
                  </div>
                )}

                {chatMessages.map((msg, index) => {
                  const isUser = msg.sender === 'user';
                  return (
                    <div
                      key={index}
                      style={{
                        maxWidth: '78%',
                        alignSelf: isUser ? 'flex-end' : 'flex-start',
                        background: isUser ? '#D9FDD3' : '#FFFFFF',
                        color: isUser ? '#111B21' : 'var(--text-main)',
                        border: isUser ? 'none' : '1px solid var(--border-color)',
                        padding: '10px 14px',
                        borderRadius: isUser ? '12px 12px 0px 12px' : '12px 12px 12px 0px',
                        fontSize: '0.88rem',
                        lineHeight: '1.4',
                        boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
                        whiteSpace: 'pre-line'
                      }}
                    >
                      {(() => {
                        // Extract any Supabase or PDF URL from message text to display clean PDF Document Card
                        const urlMatch = msg.text ? msg.text.match(/(https?:\/\/[^\s]+)/i) : null;
                        let cleanText = msg.text || '';
                        let attachedUrl = null;

                        if (urlMatch && !urlMatch[0].includes('rzp.io')) {
                          attachedUrl = urlMatch[0];
                          cleanText = msg.text.replace(attachedUrl, '').trim();
                        }

                        const mediaDocs = msg.metadata?.media_documents || [];

                        return (
                          <>
                            <div>{cleanText || msg.text}</div>

                            {/* Render explicit media_documents attached by the Agent */}
                            {mediaDocs.length > 0 && (
                              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginTop: '10px' }}>
                                {mediaDocs.map((doc, dIdx) => (
                                  <div key={dIdx} style={{ padding: '10px 12px', background: '#F8F9FA', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                      <span style={{ fontSize: '1.4rem' }}>📄</span>
                                      <div>
                                        <div style={{ fontWeight: '600', fontSize: '0.82rem', color: 'var(--text-main)' }}>
                                          {doc.filename || `${doc.invoice_id}_bill.pdf`}
                                        </div>
                                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Official Invoice PDF</div>
                                      </div>
                                    </div>
                                    <a
                                      href={doc.url?.startsWith('http') ? doc.url : `${API_BASE}${doc.url}`}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        padding: '5px 12px',
                                        borderRadius: '6px',
                                        background: 'var(--primary)',
                                        color: '#FFF',
                                        fontSize: '0.75rem',
                                        fontWeight: '600',
                                        textDecoration: 'none'
                                      }}
                                    >
                                      Open PDF
                                    </a>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* Fallback Single URL attachment */}
                            {attachedUrl && mediaDocs.length === 0 && (
                              <div style={{ marginTop: '10px', padding: '10px 12px', background: '#F8F9FA', borderRadius: '8px', border: '1px solid var(--border-color)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                                  <span style={{ fontSize: '1.4rem' }}>📄</span>
                                  <div>
                                    <div style={{ fontWeight: '600', fontSize: '0.82rem', color: 'var(--text-main)' }}>
                                      {selectedInvoice?.invoice_id || 'Invoice'}_bill.pdf
                                    </div>
                                    <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Official PDF Document</div>
                                  </div>
                                </div>
                                <a
                                  href={attachedUrl}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={{
                                    padding: '5px 12px',
                                    borderRadius: '6px',
                                    background: 'var(--primary)',
                                    color: '#FFF',
                                    fontSize: '0.75rem',
                                    fontWeight: '600',
                                    textDecoration: 'none'
                                  }}
                                >
                                  Open PDF
                                </a>
                              </div>
                            )}
                          </>
                        );
                      })()}

                      {/* Interactive Invoice Document Attachment Link */}
                      {selectedInvoice && (selectedInvoice.has_document || selectedInvoice.document_url) && index === 0 && (
                        <div style={{ marginTop: '8px', paddingTop: '6px', borderTop: '1px solid var(--border-color)' }}>
                          <a
                            href={selectedInvoice.document_url || `${API_BASE}/api/invoices/${selectedInvoice.invoice_id}/document?customer_phone=${encodeURIComponent(selectedInvoice.customer_phone)}`}
                            target="_blank"
                            rel="noreferrer"
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '6px',
                              padding: '6px 12px',
                              borderRadius: '6px',
                              background: 'var(--bg-dark)',
                              border: '1px solid var(--border-color)',
                              color: 'var(--text-main)',
                              fontSize: '0.78rem',
                              fontWeight: '600',
                              textDecoration: 'none'
                            }}
                          >
                            📄 View Original Invoice Bill (PDF/Image)
                          </a>
                        </div>
                      )}

                      {/* Interactive Payment Button inside Chat Bubble when payment link is generated */}
                      {msg.sender === 'agent' && (msg.metadata?.payment_link_url || msg.text.includes('https://rzp.io/')) && selectedInvoice && selectedInvoice.remaining_amount_inr > 0 && (
                        <div style={{ marginTop: '10px', paddingTop: '8px', borderTop: '1px solid var(--border-color)' }}>
                          <button
                            onClick={() => handleRazorpayCheckout(selectedInvoice)}
                            style={{
                              width: '100%',
                              padding: '8px 14px',
                              borderRadius: '6px',
                              background: 'var(--success)',
                              color: '#FFF',
                              border: 'none',
                              fontWeight: '600',
                              fontSize: '0.82rem',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              gap: '6px',
                              boxShadow: '0 2px 6px rgba(16, 185, 129, 0.3)'
                            }}
                          >
                            💳 Pay Now via Razorpay
                          </button>
                        </div>
                      )}

                      <div style={{ fontSize: '0.65rem', color: isUser ? '#54656F' : 'var(--text-muted)', textAlign: 'right', marginTop: '4px' }}>
                        {formatTime(msg.timestamp)}
                      </div>
                    </div>
                  );
                })}

              </div>

              {/* Quick Preset Action Buttons */}
              <div style={{ padding: '10px 16px', background: '#FFF', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '8px', overflowX: 'auto' }}>
                <button
                  onClick={() => handleSendMessage("Can I pay 40% today and the rest next week?")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: 'var(--text-main)', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  ⚡ Propose 40% Today
                </button>
                <button
                  onClick={() => handleSendMessage("Can I extend the payment due date by 14 days?")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: 'var(--primary)', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  📅 Request 14-Day Extension
                </button>
                <button
                  onClick={() => handleSendMessage("I can only pay 10% right now")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  ⚠️ Lowball 10% Offer
                </button>
                <button
                  onClick={() => handleSendMessage("I have transferred 50000 via UPI")}
                  style={{ padding: '6px 12px', borderRadius: '16px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: 'var(--warning)', cursor: 'pointer', fontSize: '0.75rem', whitespace: 'nowrap' }}
                >
                  💳 Claim "Paid via UPI"
                </button>
              </div>

              {/* Chat Input Bar */}
              <div style={{ padding: '12px 16px', background: 'var(--bg-dark)', borderTop: '1px solid var(--border-color)', display: 'flex', gap: '10px', alignItems: 'center' }}>
                <input
                  type="text"
                  placeholder="Type a proposal message..."
                  value={inputMessage}
                  onChange={(e) => setInputMessage(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
                  style={{ flex: 1, padding: '10px 14px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                />
                <button
                  onClick={() => handleSendMessage()}
                  disabled={isSending}
                  style={{ padding: '10px 18px', borderRadius: '8px', background: 'var(--text-main)', color: '#FFF', border: 'none', cursor: 'pointer', fontWeight: '600', fontSize: '0.88rem' }}
                >
                  {isSending ? '...' : 'Send'}
                </button>
              </div>

            </div>

            {/* Right: Inspectable Real-Time Agent Trace Log */}
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', height: '100%', borderRadius: '16px', background: '#FFFFFF', border: '1px solid var(--border-color)', boxShadow: '0 4px 12px rgba(0,0,0,0.03)', overflow: 'hidden' }}>
              <div>
                <h3 style={{ fontSize: '1.1rem', fontWeight: '600', color: 'var(--text-main)', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <span>🔍 Inspectable Agent Trace Log</span>
                </h3>
                <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>Real-time audit step visualization for fintech safety</p>
              </div>

              {!agentTrace ? (
                <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center', border: '1px dashed var(--border-color)', borderRadius: '12px', margin: '16px 0' }}>
                  Send a message in the WhatsApp simulator to inspect real-time agent reasoning, guardrail evaluation, and integer paise currency conversions!
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', flex: 1, overflowY: 'auto', marginTop: '16px', paddingRight: '4px' }}>
                  
                  {/* 1. Strategy & Thought */}
                  <div style={{ background: 'var(--bg-dark)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: '700', color: 'var(--primary)', textTransform: 'uppercase', marginBottom: '4px' }}>🧠 Strategy & Reasoning Thought</div>
                    <p style={{ fontSize: '0.85rem', color: 'var(--text-main)' }}>{agentTrace.thought}</p>
                  </div>

                  {/* 2. Guardrail Check Status */}
                  <div style={{ background: 'var(--bg-dark)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.75rem', fontWeight: '700', color: 'var(--text-main)', textTransform: 'uppercase' }}>🛡️ Guardrail Engine Gateway</span>
                      <span style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '0.75rem', fontWeight: '700', backgroundColor: agentTrace.guardrail_check.status === 'PASS' ? 'var(--success-bg)' : 'var(--danger-bg)', color: agentTrace.guardrail_check.status === 'PASS' ? 'var(--success)' : 'var(--danger)', border: `1px solid ${agentTrace.guardrail_check.status === 'PASS' ? 'var(--success)' : 'var(--danger)'}` }}>
                        {agentTrace.guardrail_check.status}
                      </span>
                    </div>
                    <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{agentTrace.guardrail_check.reason || "All merchant guardrails satisfied."}</p>
                  </div>

                  {/* 3. Integer Paise Currency Audit */}
                  {agentTrace.currency_conversion?.approved_amount_inr && (
                    <div style={{ background: 'var(--bg-dark)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                      <div style={{ fontSize: '0.75rem', fontWeight: '700', color: 'var(--warning)', textTransform: 'uppercase', marginBottom: '6px' }}>💱 Currency Math Audit (Zero Float Drift)</div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '4px' }}>
                        <span style={{ color: 'var(--text-muted)' }}>INR Rupee Amount:</span>
                        <strong style={{ color: 'var(--text-main)' }}>₹{agentTrace.currency_conversion.approved_amount_inr?.toLocaleString('en-IN')}</strong>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Integer Paise Storage:</span>
                        <strong style={{ color: 'var(--primary)', fontFamily: 'monospace' }}>{agentTrace.currency_conversion.approved_amount_paise?.toLocaleString('en-IN')} paise</strong>
                      </div>
                    </div>
                  )}

                  {/* 4. Verified Invoice Status */}
                  <div style={{ background: 'var(--bg-dark)', padding: '14px', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                    <div style={{ fontSize: '0.75rem', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>📌 Database Verified Status</div>
                    <p style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)' }}>{agentTrace.verified_invoice_status || "UNPAID"}</p>
                  </div>

                </div>
              )}

            </div>

          </div>
        )}
      </main>


      {/* EDIT INVOICE & RECORD OFFLINE PAYMENT MODAL */}
      {isEditModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '540px',
            padding: '32px',
            borderRadius: '16px',
            background: '#FFFFFF',
            border: '1px solid var(--border-color)',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.12)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>Edit Invoice Details</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Invoice ID: {editingInvoice.invoice_id}</p>
              </div>
              <button
                onClick={() => setIsEditModalOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSaveEditInvoice} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  Customer / SME Name
                </label>
                <input
                  type="text"
                  value={editingInvoice.customer_name}
                  onChange={(e) => setEditingInvoice({ ...editingInvoice, customer_name: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  WhatsApp Phone Number
                </label>
                <input
                  type="text"
                  value={editingInvoice.customer_phone}
                  onChange={(e) => setEditingInvoice({ ...editingInvoice, customer_phone: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  Payment Due Date
                </label>
                <input
                  type="date"
                  value={editingInvoice.due_date}
                  onChange={(e) => setEditingInvoice({ ...editingInvoice, due_date: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              {/* Record Manual / Offline Payment Section */}
              <div style={{ padding: '16px', borderRadius: '12px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)' }}>
                    💳 Record Offline / Partial Payment (₹ INR)
                  </label>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Remaining: ₹{editingInvoice.remaining_amount_inr?.toLocaleString('en-IN')}
                  </span>
                </div>
                <input
                  type="number"
                  placeholder="e.g. 15000 (Cash, Bank Transfer, Offline UPI)"
                  step="0.01"
                  value={editingInvoice.manual_payment_inr}
                  onChange={(e) => setEditingInvoice({ ...editingInvoice, manual_payment_inr: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                />
                <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '6px' }}>
                  Entering an amount here will deduct it from the outstanding balance and log an offline transaction.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
                <button
                  type="button"
                  onClick={() => setIsEditModalOpen(false)}
                  style={{
                    flex: 1,
                    padding: '12px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontWeight: '500',
                    fontSize: '0.88rem'
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
                    background: 'var(--text-main)',
                    color: '#FFF',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: '500',
                    fontSize: '0.88rem',
                  }}
                >
                  Save Changes
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* CREATE NEW BILL MODAL */}
      {isCreateModalOpen && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0, 0, 0, 0.4)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 1000,
          padding: '20px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '540px',
            padding: '32px',
            borderRadius: '16px',
            background: '#FFFFFF',
            border: '1px solid var(--border-color)',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.12)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>Add New Invoice</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Upload a bill or enter customer details for AI recovery</p>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* AI File Extraction Dropzone */}
            <div style={{
              marginBottom: '20px',
              padding: '20px',
              borderRadius: '12px',
              border: '2px dashed var(--border-color)',
              background: 'var(--bg-dark)',
              textAlign: 'center',
              cursor: 'pointer',
              position: 'relative',
              transition: 'border-color 0.2s',
            }}>
              <input
                type="file"
                accept="image/*,application/pdf"
                onChange={handleFileUpload}
                style={{
                  position: 'absolute',
                  top: 0, left: 0, width: '100%', height: '100%',
                  opacity: 0, cursor: 'pointer'
                }}
              />
              {isExtracting ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', color: 'var(--primary)', fontWeight: '600', fontSize: '0.9rem' }}>
                  <span>✨</span> Gemini AI is reading your invoice bill...
                </div>
              ) : extractError ? (
                <div>
                  <p style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--danger)', marginBottom: '4px' }}>
                    ⚠️ {extractError}
                  </p>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    Click to try another file or enter details manually below.
                  </p>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '0.9rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>
                    📄 Upload Invoice File (PDF / Image)
                  </p>
                  <p style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                    Gemini AI will automatically extract Name, Amount, Due Date & Phone
                  </p>
                </div>
              )}
            </div>

            <form onSubmit={handleCreateBill} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  Customer / SME Name *
                </label>
                <input
                  type="text"
                  placeholder="e.g. Rajesh Enterprises"
                  value={newBillData.customer_name}
                  onChange={(e) => setNewBillData({ ...newBillData, customer_name: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  WhatsApp Phone Number *
                </label>
                <input
                  type="text"
                  placeholder="e.g. +919812345678"
                  value={newBillData.customer_phone}
                  onChange={(e) => setNewBillData({ ...newBillData, customer_phone: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
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
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
                    fontSize: '0.9rem'
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '500', color: 'var(--text-main)', marginBottom: '6px' }}>
                  Payment Due Date *
                </label>
                <input
                  type="date"
                  value={newBillData.due_date}
                  onChange={(e) => setNewBillData({ ...newBillData, due_date: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '10px 14px',
                    borderRadius: '8px',
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-main)',
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
                    background: '#FFF',
                    border: '1px solid var(--border-color)',
                    color: 'var(--text-muted)',
                    cursor: 'pointer',
                    fontWeight: '500',
                    fontSize: '0.88rem'
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
                    background: 'var(--text-main)',
                    color: '#FFF',
                    border: 'none',
                    cursor: 'pointer',
                    fontWeight: '500',
                    fontSize: '0.88rem',
                  }}
                >
                  Create Invoice Bill
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
      {/* Toast Notification Container */}
      {toast && (
        <div style={{
          position: 'fixed',
          bottom: '24px',
          right: '24px',
          zIndex: 2000,
          padding: '12px 20px',
          borderRadius: '10px',
          background: toast.type === 'success' ? '#10B981' : toast.type === 'error' ? '#EF4444' : 'var(--text-main)',
          color: '#FFFFFF',
          fontSize: '0.88rem',
          fontWeight: '500',
          boxShadow: '0 10px 25px rgba(0,0,0,0.2)',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          transition: 'all 0.3s ease'
        }}>
          {toast.type === 'success' ? '✅' : toast.type === 'error' ? '⚠️' : 'ℹ️'} {toast.message}
        </div>
      )}
    </div>
  );
}
