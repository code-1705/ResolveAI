import React, { useState, useEffect, useRef, useMemo } from 'react';
import { supabase } from './supabaseClient';
import AuthView from './AuthView';
import LandingPage from './LandingPage';
import './index.css';

const API_BASE = import.meta.env.VITE_API_BASE_URL || (window.location.port === '5173' ? 'http://localhost:8000' : window.location.origin);

// Toast Container Component
function ToastContainer({ toasts, removeToast }) {
  if (!toasts || toasts.length === 0) return null;
  return (
    <div style={{
      position: 'fixed',
      top: '20px',
      right: '20px',
      zIndex: 9999,
      display: 'flex',
      flexDirection: 'column',
      gap: '10px',
      maxWidth: '380px'
    }}>
      {toasts.map((t) => (
        <div
          key={t.id}
          style={{
            padding: '12px 16px',
            borderRadius: '10px',
            background: t.type === 'error' ? '#FEF2F2' : t.type === 'success' ? '#F0FDF4' : '#EFF6FF',
            border: `1px solid ${t.type === 'error' ? '#FCA5A5' : t.type === 'success' ? '#86EFAC' : '#93C5FD'}`,
            color: t.type === 'error' ? '#991B1B' : t.type === 'success' ? '#166534' : '#1E40AF',
            fontSize: '0.85rem',
            fontWeight: '500',
            boxShadow: '0 10px 25px -5px rgba(0, 0, 0, 0.1)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>{t.type === 'error' ? '⚠️' : t.type === 'success' ? '✓' : 'ℹ️'}</span>
            <span>{t.message}</span>
          </div>
          <button
            onClick={() => removeToast(t.id)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 'bold' }}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

export default function App() {
    // Toast State Management
  const [toasts, setToasts] = useState([]);
  const showToast = (message, type = 'info') => {
    const id = Date.now() + Math.random();
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  };
  const removeToast = (id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  // Initialize route from current browser URL path
  const getInitialRoute = () => {
    const path = window.location.pathname.toLowerCase();
    if (path.includes('/login') || path.includes('/signin') || path.includes('/auth')) {
      return 'auth';
    }
    return 'landing';
  };

  const [unauthView, setUnauthView] = useState(getInitialRoute);

  const navigateTo = (route) => {
    setUnauthView(route);
    const targetPath = route === 'auth' ? '/login' : '/';
    if (window.location.pathname !== targetPath) {
      window.history.pushState({ route }, '', targetPath);
    }
  };

  useEffect(() => {
    const handlePopState = () => {
      const path = window.location.pathname.toLowerCase();
      if (path.includes('/login') || path.includes('/signin') || path.includes('/auth')) {
        setUnauthView('auth');
      } else {
        setUnauthView('landing');
      }
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const [merchantSession, setMerchantSession] = useState(() => {
    try {
      const saved = localStorage.getItem('resolveai_merchant_session');
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  const updateMerchantSession = (session) => {
    if (session) {
      try {
        localStorage.setItem('resolveai_merchant_session', JSON.stringify(session));
      } catch (e) {
        console.error('Failed to save session:', e);
      }
    } else {
      localStorage.removeItem('resolveai_merchant_session');
    }
    setMerchantSession(session);
  };

  useEffect(() => {
    if (merchantSession && !window.location.pathname.includes('/dashboard')) {
      window.history.replaceState({}, '', '/dashboard');
    }
  }, [merchantSession]);

  const [merchantProfile, setMerchantProfile] = useState(null);
  const [isAuthChecking, setIsAuthChecking] = useState(true);
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

  // Bank Settlement State
  const [bankConfig, setBankConfig] = useState({
    bank_beneficiary_name: '',
    bank_account_number: '',
    bank_account_confirm: '',
    bank_ifsc: '',
    bank_name: '',
    upi_id: '',
    pan_number: '',
    commission_pct: 1.0,
    settlement_payout_pct: 99.0,
    settlement_cycle: 'Instant Direct Settlement (Real-Time)',
    settlement_status: 'ACTIVE',
    bank_account_masked: 'Not Configured'
  });
  const [isSavingBank, setIsSavingBank] = useState(false);
  const [bankErrorMsg, setBankErrorMsg] = useState(null);
  const [isEditingBank, setIsEditingBank] = useState(false);
  const [isDataLoaded, setIsDataLoaded] = useState(false);
  const [settlementLedger, setSettlementLedger] = useState([]);

  // Mandatory Bank Account Setup Gate check
  const isBankSetupComplete = Boolean(
    bankConfig?.bank_account_number &&
    bankConfig.bank_account_number.trim().length >= 8 &&
    bankConfig?.bank_ifsc &&
    bankConfig.bank_ifsc.trim().length === 11
  );

  // Check if current logged-in merchant is a testing/demo account
  const isTestAccount = Boolean(
    merchantSession?.user?.email === 'merchant@resolveai.com' ||
    merchantProfile?.merchant_id === 'default_merchant' ||
    merchantSession?.user?.email?.toLowerCase().includes('test')
  );
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
    invoice_number: '',
    summary_description: '',
    customer_name: '',
    customer_phone: '',
    invoice_date: '',
    due_date: '',
    billing_address: '',
    shipping_address: '',
    line_items: [],
    original_amount_inr: '',
    remaining_amount_inr: 0,
    manual_payment_inr: ''
  });

  const handleOpenEditModal = (inv) => {
    const rawItems = inv.items || [];
    const meta = inv.metadata || {};

    const normalizedItems = rawItems.length > 0 ? rawItems.map(item => {
      const r = parseFloat(item.rate || item.unit_price) || 0;
      const q = parseFloat(item.quantity || item.qty) || 1;
      return {
        description: item.description || item.item_description || '',
        rate: r > 0 ? r : '',
        quantity: q,
        total: Math.round(((r || 0) * (q || 1) + Number.EPSILON) * 100) / 100
      };
    }) : [{
      description: meta.summary_description || 'Billed Services / Products',
      rate: inv.original_amount_inr || '',
      quantity: 1,
      total: inv.original_amount_inr || 0
    }];

    setEditingInvoice({
      invoice_id: inv.invoice_id,
      invoice_number: inv.invoice_id,
      summary_description: meta.summary_description || '',
      customer_name: inv.customer_name || '',
      customer_phone: inv.customer_phone || '',
      invoice_date: meta.invoice_date || inv.due_date || new Date().toISOString().split('T')[0],
      due_date: inv.due_date || '',
      billing_address: meta.billing_address || '',
      shipping_address: meta.shipping_address || '',
      line_items: normalizedItems,
      original_amount_inr: inv.original_amount_inr !== undefined ? inv.original_amount_inr : '',
      remaining_amount_inr: inv.remaining_amount_inr || 0,
      manual_payment_inr: ''
    });
    setIsEditModalOpen(true);
  };

  const handleAddEditLineItem = () => {
    setEditingInvoice(prev => ({
      ...prev,
      line_items: [...(prev.line_items || []), { description: '', rate: '', quantity: 1, total: 0 }]
    }));
  };

  const handleRemoveEditLineItem = (index) => {
    setEditingInvoice(prev => {
      const updated = (prev.line_items || []).filter((_, i) => i !== index);
      const newTotal = updated.reduce((acc, curr) => acc + (parseFloat(curr.total) || 0), 0);
      return {
        ...prev,
        line_items: updated.length > 0 ? updated : [{ description: '', rate: '', quantity: 1, total: 0 }],
        original_amount_inr: newTotal > 0 ? newTotal.toFixed(2) : prev.original_amount_inr
      };
    });
  };

  const handleEditLineItemChange = (index, field, value) => {
    setEditingInvoice(prev => {
      const updated = [...(prev.line_items || [])];
      const row = { ...updated[index], [field]: value };
      if (field === 'rate' || field === 'quantity') {
        const r = parseFloat(field === 'rate' ? value : row.rate) || 0;
        const q = parseFloat(field === 'quantity' ? value : row.quantity) || 0;
        row.total = Math.round(((r * q) + Number.EPSILON) * 100) / 100;
      }
      updated[index] = row;
      const sumTotal = updated.reduce((acc, curr) => acc + (parseFloat(curr.total) || 0), 0);
      return {
        ...prev,
        line_items: updated,
        original_amount_inr: sumTotal > 0 ? sumTotal.toFixed(2) : prev.original_amount_inr
      };
    });
  };

  const handleSaveEditInvoice = async (e) => {
    e.preventDefault();
    try {
      const res = await fetch(`${API_BASE}/api/invoices/${encodeURIComponent(editingInvoice.invoice_id)}`, {
        method: 'PUT',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          customer_name: editingInvoice.customer_name,
          customer_phone: editingInvoice.customer_phone,
          due_date: editingInvoice.due_date,
          summary_description: editingInvoice.summary_description || null,
          invoice_date: editingInvoice.invoice_date || null,
          billing_address: editingInvoice.billing_address || null,
          shipping_address: editingInvoice.shipping_address || null,
          line_items: editingInvoice.line_items || null,
          original_amount_inr: parseFloat(editingInvoice.original_amount_inr || 0) || null,
          manual_payment_inr: parseFloat(editingInvoice.manual_payment_inr || 0)
        })
      });

      if (res.ok) {
        setIsEditModalOpen(false);
        fetchData();
        showToast('Invoice updated successfully!', 'success');
      } else {
        const err = await res.json();
        showToast(err.detail || 'Failed to update invoice.', 'error');
      }
    } catch (err) {
      showToast(`Error updating invoice: ${err.message}`, 'error');
    }
  };

  // Create Bill Modal States
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractError, setExtractError] = useState(null);


  const [newBillData, setNewBillData] = useState({
    invoice_number: '',
    summary_description: '',
    customer_name: '',
    customer_phone: '',
    invoice_date: new Date().toISOString().split('T')[0],
    due_date: new Date().toISOString().split('T')[0],
    billing_address: '',
    shipping_address: '',
    line_items: [
      { description: '', rate: '', quantity: 1, total: 0 }
    ],
    original_amount_inr: '',
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


  // Supabase Auth Session Management
  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        updateMerchantSession(session);
      }
      setIsAuthChecking(false);
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session) {
        updateMerchantSession(session);
      }
      setIsAuthChecking(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  const getAuthHeaders = () => {
    const headers = { 'Content-Type': 'application/json' };
    let token = merchantSession?.access_token;
    if (!token) {
      try {
        const saved = localStorage.getItem('resolveai_merchant_session');
        token = saved ? JSON.parse(saved)?.access_token : null;
      } catch (e) {}
    }
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
  };

  // WhatsApp Rich Text Renderer (Converts *bold*, **bold**, `code`, and * bullets into clean styling)
  const renderWhatsAppText = (text) => {
    if (!text) return null;
    const lines = text.split('\n');
    return lines.map((line, lIdx) => {
      let cleanLine = line;
      if (cleanLine.trim().startsWith('* ') || cleanLine.trim().startsWith('- ')) {
        cleanLine = cleanLine.replace(/^(\s*)[*-]\s+/, '$1• ');
      }

      const parts = [];
      const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
      let match;
      let lastIndex = 0;

      while ((match = regex.exec(cleanLine)) !== null) {
        if (match.index > lastIndex) {
          parts.push(cleanLine.substring(lastIndex, match.index));
        }
        const token = match[0];
        if (token.startsWith('**') && token.endsWith('**')) {
          parts.push(<strong key={match.index}>{token.slice(2, -2)}</strong>);
        } else if (token.startsWith('*') && token.endsWith('*')) {
          parts.push(<strong key={match.index}>{token.slice(1, -1)}</strong>);
        } else if (token.startsWith('`') && token.endsWith('`')) {
          parts.push(
            <span key={match.index} style={{ background: 'rgba(0,0,0,0.06)', padding: '1px 5px', borderRadius: '4px', fontFamily: 'monospace', fontSize: '0.9em' }}>
              {token.slice(1, -1)}
            </span>
          );
        }
        lastIndex = regex.lastIndex;
      }

      if (lastIndex < cleanLine.length) {
        parts.push(cleanLine.substring(lastIndex));
      }

      return (
        <div key={lIdx} style={{ minHeight: cleanLine.trim() ? 'auto' : '10px' }}>
          {parts.length > 0 ? parts : cleanLine}
        </div>
      );
    });
  };

  // Mandatory Navigation & Tab Guard (Waits for data to load from server)
  useEffect(() => {
    if (!merchantSession || !isDataLoaded) return;

    if (!isBankSetupComplete) {
      if (activeTab !== 'settlement') {
        setActiveTab('settlement');
      }
    } else if (!isTestAccount && activeTab === 'simulator') {
      setActiveTab('dashboard');
    }
  }, [merchantSession, isDataLoaded, isBankSetupComplete, isTestAccount, activeTab]);

  // Fetch initial data scoped to authenticated merchant
  const fetchData = async () => {
    try {
      const headers = getAuthHeaders();
      const [invRes, guardRes, anaRes, profileRes, bankRes, ledgerRes] = await Promise.all([
        fetch(`${API_BASE}/api/invoices`, { headers }),
        fetch(`${API_BASE}/api/guardrails`, { headers }),
        fetch(`${API_BASE}/api/analytics`, { headers }),
        fetch(`${API_BASE}/api/auth/me`, { headers }),
        fetch(`${API_BASE}/api/merchant/bank-settlement`, { headers }),
        fetch(`${API_BASE}/api/merchant/settlement-ledger`, { headers })
      ]);
      if (invRes.ok) setInvoices(await invRes.json());
      if (guardRes.ok) setGuardrails(await guardRes.json());
      if (anaRes.ok) setAnalytics(await anaRes.json());
      if (profileRes.ok) setMerchantProfile(await profileRes.json());
      if (ledgerRes.ok) setSettlementLedger(await ledgerRes.json());
      if (bankRes.ok) {
        const bData = await bankRes.json();
        setBankConfig(prev => ({ ...prev, ...bData, bank_account_confirm: bData.bank_account_number || '' }));
        const isConfigured = Boolean(bData.bank_account_number && bData.bank_account_number.length >= 8 && bData.bank_ifsc);
        setIsEditingBank(!isConfigured);
        if (isConfigured && activeTab === 'settlement' && !isDataLoaded) {
          setActiveTab('dashboard');
        }
      }
      setIsDataLoaded(true);
    } catch (err) {
      console.error('API Fetch error:', err);
    }
  };

  // Trigger data fetch whenever active merchant session changes
  useEffect(() => {
    if (merchantSession) {
      fetchData();
    }
  }, [merchantSession]);

  useEffect(() => {
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
          const targetPhone = payload.data?.customer_phone || (activeCustomer ? activeCustomer.customer_phone : selectedPhone);
          if (targetPhone) {
            fetchChatHistory(targetPhone);
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


  // Fetch chat history for selected customer phone
  const fetchChatHistory = async (customerPhone, invoiceId = null) => {
    if (!customerPhone) return;
    try {
      const invParam = invoiceId ? `&invoice_id=${invoiceId}` : '';
      const res = await fetch(`${API_BASE}/api/chat/history?customer_phone=${encodeURIComponent(customerPhone)}${invParam}`);
      if (res.ok) {
        const data = await res.json();
        setChatMessages(data.messages || []);
      }
    } catch (err) {
      console.error('Error fetching chat history:', err);
    }
  };

  useEffect(() => {
    if (activeCustomer) {
      const firstInvId = activeCustomer.invoices && activeCustomer.invoices.length > 0 ? activeCustomer.invoices[0].invoice_id : null;
      fetchChatHistory(activeCustomer.customer_phone, firstInvId);
    }
  }, [selectedPhone, invoices, activeCustomer]); // Fix: re-fetch chat when customer or balance changes

  // Send message to simulator
  const handleSendMessage = async (customText = null) => {
    const textToSend = customText || inputMessage;
    if (!textToSend.trim() || !activeCustomer || isSending) return;

    const phone = activeCustomer.customer_phone;
    const currentInv = selectedInvoice || (activeCustomer.invoices && activeCustomer.invoices.length > 0 ? activeCustomer.invoices[0] : null);
    const invoice_id = currentInv ? currentInv.invoice_id : null;

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
          session_id: phone,
          customer_phone: phone,
          invoice_id: invoice_id,
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

  const roundTo2 = (num) => Math.round((num + Number.EPSILON) * 100) / 100;

  const handleAddLineItem = () => {
    setNewBillData(prev => ({
      ...prev,
      line_items: [...(prev.line_items || []), { description: '', rate: '', quantity: 1, total: 0 }]
    }));
  };

  const handleRemoveLineItem = (index) => {
    setNewBillData(prev => {
      const updated = (prev.line_items || []).filter((_, i) => i !== index);
      const newTotal = updated.reduce((acc, curr) => acc + (parseFloat(curr.total) || 0), 0);
      return {
        ...prev,
        line_items: updated.length > 0 ? updated : [{ description: '', rate: '', quantity: 1, total: 0 }],
        original_amount_inr: newTotal > 0 ? newTotal.toFixed(2) : prev.original_amount_inr
      };
    });
  };

  const handleLineItemChange = (index, field, value) => {
    setNewBillData(prev => {
      const updated = [...(prev.line_items || [])];
      const row = { ...updated[index], [field]: value };
      if (field === 'rate' || field === 'quantity') {
        const r = parseFloat(field === 'rate' ? value : row.rate) || 0;
        const q = parseFloat(field === 'quantity' ? value : row.quantity) || 0;
        row.total = roundTo2(r * q);
      }
      updated[index] = row;
      const sumTotal = updated.reduce((acc, curr) => acc + (parseFloat(curr.total) || 0), 0);
      return {
        ...prev,
        line_items: updated,
        original_amount_inr: sumTotal > 0 ? sumTotal.toFixed(2) : prev.original_amount_inr
      };
    });
  };

  // Create bill submission handler
  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    setIsExtracting(true);
    setExtractError(null);

    // Read file locally immediately so file is always preserved for Supabase Storage
    const reader = new FileReader();
    reader.onload = async (event) => {
      const b64 = event.target.result.split(',')[1];
      setNewBillData(prev => ({
        ...prev,
        file_name: file.name,
        file_mime_type: file.type || 'application/pdf',
        file_bytes_b64: b64
      }));

      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch(`${API_BASE}/api/invoices/extract`, {
          method: 'POST',
          body: formData
        });
        const json = await res.json();
        if (json.success && json.data) {
          const rawItems = json.data.line_items || [];
          const normalizedItems = rawItems.length > 0 ? rawItems.map(item => {
            const r = parseFloat(item.rate || item.unit_price) || 0;
            const q = parseFloat(item.quantity || item.qty) || 1;
            return {
              description: item.description || item.item_description || '',
              rate: r > 0 ? r : '',
              quantity: q,
              total: roundTo2((r || 0) * (q || 1))
            };
          }) : [{ description: '', rate: '', quantity: 1, total: 0 }];

          const computedSum = normalizedItems.reduce((acc, curr) => acc + (parseFloat(curr.total) || 0), 0);
          const finalTotal = json.data.total_amount_inr || json.data.original_amount_inr || (computedSum > 0 ? computedSum : undefined);

          setNewBillData(prev => ({
            ...prev,
            invoice_number: json.data.invoice_number || prev.invoice_number,
            summary_description: json.data.summary_description || json.data.notes || prev.summary_description,
            customer_name: json.data.customer_name || prev.customer_name,
            customer_phone: json.data.customer_phone || prev.customer_phone,
            invoice_date: json.data.invoice_date || prev.invoice_date,
            due_date: json.data.due_date || prev.due_date,
            billing_address: json.data.billing_address || prev.billing_address,
            shipping_address: json.data.shipping_address || prev.shipping_address,
            line_items: normalizedItems,
            original_amount_inr: finalTotal !== undefined ? finalTotal : prev.original_amount_inr,
            file_bytes_b64: json.file_bytes_b64 || b64,
            file_name: json.file_name || file.name,
            file_mime_type: json.file_mime_type || file.type
          }));
          showToast('✨ All bill details, addresses, and line items extracted successfully!', 'success');
        } else {
          setExtractError(json.error || 'Could not auto-extract all fields. Please enter details manually below.');
        }
      } catch (err) {
        setExtractError('AI extraction timed out. Please enter details manually below.');
      } finally {
        setIsExtracting(false);
      }
    };
    reader.readAsDataURL(file);
  };

  const handleCreateBill = async (e) => {
    e.preventDefault();
    if (!newBillData.file_name || !newBillData.file_bytes_b64) {
      showToast('Invoice document is required. Please upload an invoice PDF or image first.', 'error');
      return;
    }
    if (!newBillData.customer_name || !newBillData.customer_phone || !newBillData.original_amount_inr) {
      showToast('Please fill out all required fields.', 'error');
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/api/invoices`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          customer_name: newBillData.customer_name,
          customer_phone: newBillData.customer_phone,
          original_amount_inr: parseFloat(newBillData.original_amount_inr),
          due_date: newBillData.due_date,
          invoice_number: newBillData.invoice_number || null,
          summary_description: newBillData.summary_description || null,
          invoice_date: newBillData.invoice_date || null,
          billing_address: newBillData.billing_address || null,
          shipping_address: newBillData.shipping_address || null,
          line_items: newBillData.line_items || null,
          file_bytes_b64: newBillData.file_bytes_b64,
          file_name: newBillData.file_name,
          file_mime_type: newBillData.file_mime_type
        })
      });

      if (res.ok) {
        const createdInv = await res.json();
        setIsCreateModalOpen(false);
        setNewBillData({
          invoice_number: '',
          summary_description: '',
          customer_name: '',
          customer_phone: '',
          invoice_date: new Date().toISOString().split('T')[0],
          due_date: new Date().toISOString().split('T')[0],
          billing_address: '',
          shipping_address: '',
          line_items: [
            { description: '', rate: '', quantity: 1, total: 0 }
          ],
          original_amount_inr: '',
          file_bytes_b64: null,
          file_name: null,
          file_mime_type: null
        });
        fetchData();
        showToast(`Bill '${createdInv.invoice_id}' created and saved to Supabase Storage for ${createdInv.customer_name}!`, 'success');
      }
    } catch (err) {
      showToast(`Failed to create bill: ${err.message}`, 'error');
    }
  };

  // Razorpay Standard Web Checkout Modal Handler
  const handleRazorpayCheckout = async (inv) => {
    if (!inv || inv.remaining_amount_paise < 100) {
      showToast("Invoice remaining amount must be at least ₹1.00 (100 paise).", "error");
      return;
    }

    try {
      // 1. Call Backend POST /api/create-order
      const cleanInvId = String(inv.invoice_id || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(-15);
      const safeReceipt = `rcpt_${cleanInvId}_${Date.now()}`.slice(0, 40);

      const orderRes = await fetch(`${API_BASE}/api/create-order`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount_in_paise: Math.round(Number(inv.remaining_amount_paise)),
          invoice_id: inv.invoice_id,
          receipt: safeReceipt
        })
      });

      if (!orderRes.ok) {
        const errData = await orderRes.json();
        throw new Error(errData.detail || "Failed to create checkout order.");
      }

      const orderData = await orderRes.json();
      const razorpayKey = orderData.key_id || import.meta.env.VITE_RAZORPAY_KEY_ID;

      if (!razorpayKey) {
        throw new Error("Razorpay Key ID was not returned by the backend server. Please verify RAZORPAY_KEY_ID is configured in the backend environment.");
      }

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
              showToast(`Payment Verified Successfully! (ID: ${response.razorpay_payment_id})`, "success");
              fetchData();
              fetchChatHistory(inv);
            } else {
              const verifyErr = await verifyRes.json();
              showToast(`Payment Verification Failed: ${verifyErr.detail || "Signature Mismatch"}`, "error");
            }
          } catch (verifyError) {
            showToast(`Error verifying payment: ${verifyError.message}`, "error");
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
          showToast(`Payment Failed: ${resp.error.description || "Transaction failed"}`, "error");
        });
        rzp.open();
      } else {
        showToast("Razorpay SDK not loaded. Please refresh the page.", "error");
      }

    } catch (err) {
      showToast(`Checkout Error: ${err.message}`, "error");
    }
  };

  // Save Bank Settlement Details Handler
  const handleSaveBankConfig = async (e) => {
    e.preventDefault();
    setBankErrorMsg(null);

    const acc = (bankConfig.bank_account_number || '').trim();
    const confirmAcc = (bankConfig.bank_account_confirm || '').trim();
    const ifsc = (bankConfig.bank_ifsc || '').trim().toUpperCase();

    if (!acc || acc.length < 8) {
      const err = 'Bank Account Number must be at least 8 digits.';
      setBankErrorMsg(err);
      showToast(err, 'error');
      return;
    }
    if (acc !== confirmAcc) {
      const err = 'Bank Account Numbers do not match! Please check confirmation.';
      setBankErrorMsg(err);
      showToast(err, 'error');
      return;
    }
    if (!ifsc || ifsc.length !== 11) {
      const err = 'IFSC Code must be exactly 11 characters (e.g. HDFC0001234).';
      setBankErrorMsg(err);
      showToast(err, 'error');
      return;
    }

    setIsSavingBank(true);
    try {
      const res = await fetch(`${API_BASE}/api/merchant/bank-settlement`, {
        method: 'POST',
        headers: getAuthHeaders(),
        body: JSON.stringify({
          bank_beneficiary_name: bankConfig.bank_beneficiary_name || merchantProfile?.business_name || '',
          bank_account_number: acc,
          bank_ifsc: ifsc,
          bank_name: bankConfig.bank_name,
          upi_id: bankConfig.upi_id,
          pan_number: bankConfig.pan_number
        })
      });

      if (res.ok) {
        const data = await res.json();
        showToast('Bank Settlement Account configured successfully! Direct payouts active.', 'success');
        setBankErrorMsg(null);
        setIsEditingBank(false);
        fetchData();
      } else {
        const err = await res.json();
        const msg = err.detail || 'Failed to save bank details.';
        setBankErrorMsg(msg);
        showToast(msg, 'error');
      }
    } catch (err) {
      const msg = 'Network error saving bank settlement details.';
      setBankErrorMsg(msg);
      showToast(msg, 'error');
    } finally {
      setIsSavingBank(false);
    }
  };

  // Guardrail save handler
  const handleSaveGuardrails = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/guardrails`, {
        method: 'POST',
        headers: getAuthHeaders(),
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

  // 0. Loading State
  if (isAuthChecking) {
    return (
      <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'var(--bg-main)' }}>
        <div style={{ textAlign: 'center', color: 'var(--primary)', fontWeight: '600', fontSize: '1rem' }}>
          ⚡ Loading Merchant Workspace...
        </div>
      </div>
    );
  }

  // 1. Unauthenticated View (Landing Page or Sign In / Sign Up View)
  if (!merchantSession) {
    return (
      <>
        <ToastContainer toasts={toasts} removeToast={removeToast} />
        {unauthView === 'landing' ? (
          <LandingPage
            onGetStarted={() => navigateTo('auth')}
            onSignIn={() => navigateTo('auth')}
          />
        ) : (
          <AuthView
            onAuthSuccess={updateMerchantSession}
            showToast={showToast}
            onBackToLanding={() => navigateTo('landing')}
          />
        )}
      </>
    );
  }

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
      <ToastContainer toasts={toasts} removeToast={removeToast} />
      
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
            onClick={() => {
              if (!isBankSetupComplete) {
                showToast('⚠️ Setup Required: Please configure your bank account for 97% direct settlements first!', 'error');
                setActiveTab('settlement');
              } else {
                setActiveTab('dashboard');
              }
            }}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: '600',
              transition: 'all 0.2s',
              background: activeTab === 'dashboard' ? 'var(--text-main)' : 'transparent',
              color: activeTab === 'dashboard' ? '#FFF' : 'var(--text-muted)',
              opacity: !isBankSetupComplete ? 0.6 : 1
            }}
          >
            {!isBankSetupComplete ? '🔒 Invoices & Analytics' : '📊 Invoices & Analytics'}
          </button>

          <button
            onClick={() => {
              if (!isBankSetupComplete) {
                showToast('⚠️ Setup Required: Please configure your bank account for 97% direct settlements first!', 'error');
                setActiveTab('settlement');
              } else {
                setActiveTab('guardrails');
              }
            }}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: '600',
              transition: 'all 0.2s',
              background: activeTab === 'guardrails' ? 'var(--text-main)' : 'transparent',
              color: activeTab === 'guardrails' ? '#FFF' : 'var(--text-muted)',
              opacity: !isBankSetupComplete ? 0.6 : 1
            }}
          >
            {!isBankSetupComplete ? '🔒 Guardrail Policies' : '🛡️ Guardrail Policies'}
          </button>

          {/* WhatsApp Simulator: Displayed ONLY for Test Accounts with verified bank */}
          {isTestAccount && (
            <button
              onClick={() => {
                if (!isBankSetupComplete) {
                  showToast('⚠️ Setup Required: Please configure your bank account for 97% direct settlements first!', 'error');
                  setActiveTab('settlement');
                } else {
                  setActiveTab('simulator');
                }
              }}
              style={{
                padding: '8px 18px',
                borderRadius: '8px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '0.85rem',
                fontWeight: '600',
                transition: 'all 0.2s',
                background: activeTab === 'simulator' ? 'var(--text-main)' : 'transparent',
                color: activeTab === 'simulator' ? '#FFF' : 'var(--text-muted)',
                opacity: !isBankSetupComplete ? 0.6 : 1
              }}
            >
              {!isBankSetupComplete ? '🔒 WhatsApp Simulator (Test Mode)' : '💬 WhatsApp Simulator (Test Mode)'}
            </button>
          )}

          <button
            onClick={() => setActiveTab('settlement')}
            style={{
              padding: '8px 18px',
              borderRadius: '8px',
              border: 'none',
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: '600',
              transition: 'all 0.2s',
              background: activeTab === 'settlement' ? 'var(--text-main)' : 'transparent',
              color: activeTab === 'settlement' ? '#FFF' : 'var(--text-muted)',
              position: 'relative'
            }}
          >
            🏦 Bank & Settlement {!isBankSetupComplete && <span style={{ color: 'var(--danger)', fontWeight: 'bold' }}>*</span>}
          </button>
        </div>

        {/* Merchant Workspace & SSE Indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem', color: sseConnected ? 'var(--success)' : 'var(--text-dim)' }}>
            <div className="live-indicator" style={{ backgroundColor: sseConnected ? 'var(--success)' : 'var(--text-dim)' }}></div>
            <span>{sseConnected ? 'Live SSE' : 'Offline'}</span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '5px 12px', background: 'var(--bg-dark)', borderRadius: '8px', border: '1px solid var(--border-color)', fontSize: '0.82rem', color: 'var(--text-main)' }}>
            <span>🏢</span>
            <strong>{merchantProfile?.business_name || merchantSession?.user?.user_metadata?.business_name || 'Merchant Organization'}</strong>
          </div>

          <button
            onClick={async () => {
              await supabase.auth.signOut();
              updateMerchantSession(null);
              setMerchantProfile(null);
              navigateTo('landing');
              showToast('Signed out of Merchant Portal.', 'info');
            }}
            style={{
              padding: '6px 12px',
              borderRadius: '8px',
              border: '1px solid var(--border-color)',
              background: '#FFFFFF',
              color: 'var(--danger)',
              fontSize: '0.78rem',
              fontWeight: '600',
              cursor: 'pointer',
              transition: 'all 0.2s'
            }}
          >
            Sign Out
          </button>
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
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Active Client Conversations</p>
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

        {/* TAB 4: BANK & SETTLEMENT ACCOUNT CONFIGURATION */}
        {activeTab === 'settlement' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            
            {/* Mandatory Setup Banner if incomplete */}
            {!isBankSetupComplete && (
              <div style={{
                padding: '16px 20px',
                borderRadius: '12px',
                background: '#FEF2F2',
                border: '1px solid #FCA5A5',
                color: '#991B1B',
                fontSize: '0.9rem',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                boxShadow: '0 4px 12px rgba(239, 68, 68, 0.08)'
              }}>
                <span style={{ fontSize: '1.4rem' }}>⚠️</span>
                <div>
                  <strong style={{ fontSize: '0.95rem' }}>Mandatory Bank Account Setup:</strong>
                  <div style={{ fontSize: '0.82rem', marginTop: '2px' }}>
                    You must link your official bank account to enable invoice recovery, customer payment links, and 97% automated direct payouts.
                  </div>
                </div>
              </div>
            )}

            {/* Header Title */}
            <div>
              <h2 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>
                Bank & Direct Settlement Settings
              </h2>
              <p style={{ fontSize: '0.9rem', color: 'var(--text-muted)' }}>
                Configure your verified bank account to receive 97% automated payouts when customers pay invoices via WhatsApp.
              </p>
            </div>

            {/* Platform Monetization & Payout Split Overview */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '20px' }}>
              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Merchant Payout Share</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--success)' }}>{bankConfig.settlement_payout_pct || 99.0}%</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--success)', marginTop: '6px' }}>Direct Bank Deposit</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Platform Recovery Cut</p>
                <h3 style={{ fontSize: '1.8rem', fontWeight: '700', color: 'var(--primary)' }}>{bankConfig.commission_pct || 1.0}%</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Automated Take-Rate</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Settlement Cycle</p>
                <h3 style={{ fontSize: '1.4rem', fontWeight: '700', color: 'var(--text-main)' }}>Instant (Real-Time)</h3>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '6px' }}>Next Business Day NEFT/IMPS</p>
              </div>

              <div className="glass-panel" style={{ padding: '20px' }}>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '8px' }}>Gateway Status</p>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
                  <div className="live-indicator" style={{ backgroundColor: 'var(--success)' }}></div>
                  <span style={{ fontSize: '1.1rem', fontWeight: '700', color: 'var(--success)' }}>Active (Route)</span>
                </div>
                <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '8px' }}>Master Razorpay Escrow</p>
              </div>
            </div>

            {/* Full-Width Grid: Form + Architecture & Payout Guidelines */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '24px', alignItems: 'start' }}>
              
              {/* Left Column: Bank Configuration Form (with Edit/Readonly & Inline Error) */}
              <div className="glass-panel" style={{ padding: '32px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', borderBottom: '1px solid var(--border-color)', paddingBottom: '16px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ width: '42px', height: '42px', borderRadius: '10px', background: isBankSetupComplete && !isEditingBank ? 'var(--success)' : 'var(--primary)', color: '#FFF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.3rem' }}>
                      {isBankSetupComplete && !isEditingBank ? '✓' : '🏦'}
                    </div>
                    <div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <h3 style={{ fontSize: '1.15rem', fontWeight: '700', color: 'var(--text-main)' }}>
                          Beneficiary Bank Account Details
                        </h3>
                        {isBankSetupComplete && !isEditingBank && (
                          <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: '12px', background: 'var(--success-bg)', color: 'var(--success)', border: '1px solid var(--success)', fontWeight: '600' }}>
                            Verified & Active
                          </span>
                        )}
                      </div>
                      <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>
                        Recovered customer funds (97% net payout) will be deposited directly to this account.
                      </p>
                    </div>
                  </div>

                  {/* Top Edit Button if already saved & in read-only mode */}
                  {isBankSetupComplete && !isEditingBank && (
                    <button
                      type="button"
                      onClick={() => {
                        setIsEditingBank(true);
                        setBankErrorMsg(null);
                      }}
                      style={{
                        padding: '8px 16px',
                        borderRadius: '8px',
                        border: '1px solid var(--border-color)',
                        background: '#FFF',
                        color: 'var(--text-main)',
                        fontWeight: '600',
                        fontSize: '0.85rem',
                        cursor: 'pointer',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        boxShadow: '0 2px 4px rgba(0,0,0,0.04)'
                      }}
                    >
                      <span>✏️</span> Edit Details
                    </button>
                  )}
                </div>

                <form onSubmit={handleSaveBankConfig} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                      Account Holder / Legal Entity Name *
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Vanssh Limited / Apex Logistics"
                      value={bankConfig.bank_beneficiary_name || ''}
                      onChange={(e) => {
                        setBankConfig({ ...bankConfig, bank_beneficiary_name: e.target.value });
                        if (bankErrorMsg) setBankErrorMsg(null);
                      }}
                      disabled={isBankSetupComplete && !isEditingBank}
                      style={{
                        width: '100%',
                        padding: '12px 14px',
                        borderRadius: '8px',
                        border: '1px solid var(--border-color)',
                        background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                        color: 'var(--text-main)',
                        fontSize: '0.9rem',
                        outline: 'none',
                        boxSizing: 'border-box',
                        cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                      }}
                      required
                    />
                    <p style={{ fontSize: '0.75rem', color: 'var(--text-dim)', marginTop: '4px' }}>
                      Must exactly match your legal name registered with the bank.
                    </p>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Bank Account Number *
                      </label>
                      <input
                        type={isBankSetupComplete && !isEditingBank ? 'text' : 'password'}
                        placeholder="Enter account number"
                        value={isBankSetupComplete && !isEditingBank ? (bankConfig.bank_account_masked || '••••••••' + (bankConfig.bank_account_number || '').slice(-4)) : (bankConfig.bank_account_number || '')}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, bank_account_number: e.target.value });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          fontFamily: isBankSetupComplete && !isEditingBank ? 'monospace' : 'inherit',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Confirm Bank Account Number *
                      </label>
                      <input
                        type="text"
                        placeholder="Re-enter account number"
                        value={isBankSetupComplete && !isEditingBank ? (bankConfig.bank_account_masked || '••••••••' + (bankConfig.bank_account_number || '').slice(-4)) : (bankConfig.bank_account_confirm || '')}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, bank_account_confirm: e.target.value });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          fontFamily: isBankSetupComplete && !isEditingBank ? 'monospace' : 'inherit',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                        required
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Bank IFSC Code *
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. HDFC0001234"
                        value={bankConfig.bank_ifsc || ''}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, bank_ifsc: e.target.value.toUpperCase() });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        maxLength={11}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          fontFamily: 'monospace',
                          textTransform: 'uppercase',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Bank Name & Branch
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. HDFC Bank, Connaught Place"
                        value={bankConfig.bank_name || ''}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, bank_name: e.target.value });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Primary UPI ID / VPA
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. business@okaxis"
                        value={bankConfig.upi_id || ''}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, upi_id: e.target.value });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '8px' }}>
                        Business PAN / GSTIN
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. ABCDE1234F"
                        value={bankConfig.pan_number || ''}
                        onChange={(e) => {
                          setBankConfig({ ...bankConfig, pan_number: e.target.value.toUpperCase() });
                          if (bankErrorMsg) setBankErrorMsg(null);
                        }}
                        disabled={isBankSetupComplete && !isEditingBank}
                        style={{
                          width: '100%',
                          padding: '12px 14px',
                          borderRadius: '8px',
                          border: '1px solid var(--border-color)',
                          background: isBankSetupComplete && !isEditingBank ? '#FAFAF9' : 'var(--bg-dark)',
                          color: 'var(--text-main)',
                          fontSize: '0.9rem',
                          fontFamily: 'monospace',
                          textTransform: 'uppercase',
                          outline: 'none',
                          boxSizing: 'border-box',
                          cursor: isBankSetupComplete && !isEditingBank ? 'default' : 'text'
                        }}
                      />
                    </div>
                  </div>

                  {/* Security Notice */}
                  <div style={{ padding: '14px 18px', borderRadius: '10px', background: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.3)', color: 'var(--success)', fontSize: '0.85rem', display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span>🔒</span>
                    <div>
                      <strong>Direct Nodal Protection:</strong> Bank details are stored with AES-256 encryption. Payouts are reconciled via Razorpay Route.
                    </div>
                  </div>

                  {/* Bottom Action Bar: Left Error Box + Right Action Buttons */}
                  <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginTop: '10px',
                    gap: '16px'
                  }}>
                    {/* Left Space: Prominent Inline Validation Error Display */}
                    <div style={{ flex: 1, minHeight: '32px', display: 'flex', alignItems: 'center' }}>
                      {bankErrorMsg ? (
                        <div style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '8px',
                          padding: '8px 14px',
                          borderRadius: '8px',
                          background: '#FEF2F2',
                          border: '1px solid #FCA5A5',
                          color: '#B91C1C',
                          fontSize: '0.85rem',
                          fontWeight: '600'
                        }}>
                          <span>⚠️</span>
                          <span>{bankErrorMsg}</span>
                        </div>
                      ) : isBankSetupComplete && !isEditingBank ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--success)', fontSize: '0.85rem', fontWeight: '500' }}>
                          <span>✓</span> All payouts configured for direct settlement.
                        </div>
                      ) : null}
                    </div>

                    {/* Right Action Buttons */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      {isEditingBank && isBankSetupComplete && (
                        <button
                          type="button"
                          onClick={() => {
                            setIsEditingBank(false);
                            setBankErrorMsg(null);
                          }}
                          style={{
                            padding: '12px 20px',
                            borderRadius: '8px',
                            border: '1px solid var(--border-color)',
                            background: '#FFF',
                            color: 'var(--text-muted)',
                            fontWeight: '600',
                            fontSize: '0.9rem',
                            cursor: 'pointer'
                          }}
                        >
                          Cancel
                        </button>
                      )}

                      {(!isBankSetupComplete || isEditingBank) && (
                        <button
                          type="submit"
                          disabled={isSavingBank}
                          style={{
                            padding: '12px 28px',
                            borderRadius: '8px',
                            border: 'none',
                            background: 'var(--text-main)',
                            color: '#FFF',
                            fontWeight: '600',
                            fontSize: '0.9rem',
                            cursor: 'pointer',
                            transition: 'all 0.2s',
                            opacity: isSavingBank ? 0.7 : 1,
                            whiteSpace: 'nowrap'
                          }}
                        >
                          {isSavingBank ? 'Saving Account...' : isBankSetupComplete ? '💾 Update Settlement Account' : '💾 Save Settlement Account'}
                        </button>
                      )}
                    </div>
                  </div>

                </form>
              </div>

              {/* Right Column: Settlement Architecture & Benefits Cards */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                
                <div className="glass-panel" style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(0, 102, 255, 0.1)', color: '#0066FF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1rem' }}>
                      ⚡
                    </div>
                    <h4 style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--text-main)' }}>
                      How Payouts Work
                    </h4>
                  </div>
                  
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', fontSize: '0.84rem', color: 'var(--text-muted)', lineHeight: '1.5' }}>
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <span style={{ fontWeight: '700', color: 'var(--primary)' }}>1.</span>
                      <span>Customer pays an overdue invoice via Razorpay payment links over WhatsApp.</span>
                    </div>
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <span style={{ fontWeight: '700', color: 'var(--primary)' }}>2.</span>
                      <span>Resolve.ai automatically deducts the <strong>1.0%</strong> platform recovery take-rate.</span>
                    </div>
                    <div style={{ display: 'flex', gap: '10px' }}>
                      <span style={{ fontWeight: '700', color: 'var(--primary)' }}>3.</span>
                      <span>The remaining <strong>97.0%</strong> is auto-deposited directly to your verified bank account via instant settlement.</span>
                    </div>
                  </div>
                </div>

                <div className="glass-panel" style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
                    <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(55, 139, 89, 0.1)', color: 'var(--success)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.1rem' }}>
                      🛡️
                    </div>
                    <h4 style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--text-main)' }}>
                      Fintech Security & Compliance
                    </h4>
                  </div>
                  <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', lineHeight: '1.5' }}>
                    All transfers are routed through RBI-compliant nodal settlement accounts. Your bank credentials are encrypted and never exposed to customers.
                  </p>
                  
                  <div style={{ marginTop: '16px', paddingTop: '14px', borderTop: '1px solid var(--border-color)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>Connected Gateway:</span>
                    <span style={{ fontSize: '0.78rem', fontWeight: '600', color: '#0066FF' }}>Razorpay Route v1</span>
                  </div>
                </div>

              </div>

            </div>

            {/* Live Financial Settlement Audit Ledger */}
            <div className="glass-panel" style={{ padding: '28px', marginTop: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <h3 style={{ fontSize: '1.2rem', fontWeight: '700', color: 'var(--text-main)' }}>
                      📜 Live Financial Settlement & Audit Ledger
                    </h3>
                    <span style={{ fontSize: '0.72rem', padding: '2px 8px', borderRadius: '12px', background: 'rgba(0, 102, 255, 0.1)', color: '#0066FF', fontWeight: '600' }}>
                      Double-Entry Escrow Log
                    </span>
                  </div>
                  <p style={{ fontSize: '0.84rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    Immutable real-time audit record of customer payment inflows and 97% automated merchant direct bank wire payouts.
                  </p>
                </div>
                <button
                  onClick={fetchData}
                  style={{
                    padding: '8px 16px',
                    borderRadius: '8px',
                    border: '1px solid var(--border-color)',
                    background: '#FFF',
                    color: 'var(--text-main)',
                    fontSize: '0.82rem',
                    fontWeight: '600',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px'
                  }}
                >
                  🔄 Refresh Ledger
                </button>
              </div>

              {settlementLedger.length === 0 ? (
                <div style={{ padding: '40px 20px', textAlign: 'center', background: 'var(--bg-dark)', borderRadius: '12px', border: '1px dashed var(--border-color)' }}>
                  <span style={{ fontSize: '2rem', display: 'block', marginBottom: '8px' }}>🏦</span>
                  <strong style={{ fontSize: '0.95rem', color: 'var(--text-main)' }}>No Settlement Transactions Yet</strong>
                  <p style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginTop: '4px', maxWidth: '460px', margin: '4px auto 0' }}>
                    When customers pay invoices through WhatsApp, the gross amount, 1.0% platform fee, and 99.0% direct bank wire transfer will appear here with full Razorpay Route audit IDs.
                  </p>
                </div>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.86rem', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Date & Time</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Transaction Type</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Invoice & Customer</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Gross Amount</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Platform Cut (3%)</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Net Payout (97%)</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Transfer / Ref ID</th>
                        <th style={{ padding: '12px 14px', fontWeight: '600' }}>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {settlementLedger.map((tx) => (
                        <tr key={tx.id} style={{ borderBottom: '1px solid #F1F5F9', transition: 'background 0.15s' }}>
                          <td style={{ padding: '14px', color: 'var(--text-dim)', fontSize: '0.8rem', whiteSpace: 'nowrap' }}>
                            {new Date(tx.created_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })}
                          </td>
                          <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                            {tx.transaction_type === 'INFLOW_CUSTOMER_PAYMENT' ? (
                              <span style={{ padding: '3px 8px', borderRadius: '6px', background: 'rgba(0, 102, 255, 0.1)', color: '#0066FF', fontSize: '0.75rem', fontWeight: '600' }}>
                                ⬇ Customer Payment Inflow
                              </span>
                            ) : (
                              <span style={{ padding: '3px 8px', borderRadius: '6px', background: 'rgba(55, 139, 89, 0.1)', color: 'var(--success)', fontSize: '0.75rem', fontWeight: '600' }}>
                                ⬆ Direct Bank Wire (97%)
                              </span>
                            )}
                          </td>
                          <td style={{ padding: '14px' }}>
                            <div style={{ fontWeight: '600', color: 'var(--text-main)' }}>{tx.customer_name}</div>
                            <div style={{ fontSize: '0.75rem', color: 'var(--text-dim)', fontFamily: 'monospace' }}>{tx.invoice_id}</div>
                          </td>
                          <td style={{ padding: '14px', fontWeight: '600', color: 'var(--text-main)' }}>
                            ₹{tx.gross_amount_inr?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: '14px', color: 'var(--primary)', fontWeight: '600' }}>
                            -₹{tx.platform_fee_inr?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: '14px', color: 'var(--success)', fontWeight: '700', fontSize: '0.92rem' }}>
                            ₹{tx.merchant_amount_inr?.toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: '14px', fontFamily: 'monospace', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                            {tx.razorpay_transfer_id || tx.razorpay_payment_id || '—'}
                          </td>
                          <td style={{ padding: '14px', whiteSpace: 'nowrap' }}>
                            <span style={{
                              padding: '4px 10px',
                              borderRadius: '20px',
                              fontSize: '0.72rem',
                              fontWeight: '600',
                              background: tx.status === 'TRANSFERRED' ? 'var(--success-bg)' : 'rgba(0, 102, 255, 0.1)',
                              color: tx.status === 'TRANSFERRED' ? 'var(--success)' : '#0066FF',
                              border: `1px solid ${tx.status === 'TRANSFERRED' ? 'var(--success)' : 'rgba(0, 102, 255, 0.3)'}`
                            }}>
                              {tx.status === 'TRANSFERRED' ? '🟢 SETTLED (INSTANT)' : '🟢 CAPTURED'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
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
                        const urlMatch = msg.text ? msg.text.match(/(https?:\/\/[^\s]+|\/api\/invoices\/[^\s]+)/i) : null;
                        let cleanText = msg.text || '';
                        let attachedUrl = null;

                        // Clean duplicate bracketed links like [https://rzp.io/...] (https://rzp.io/...)
                        cleanText = cleanText.replace(/\[\s*(https?:\/\/rzp\.io\/[^\s\]\)]+)\s*\]\s*\(\s*(https?:\/\/rzp\.io\/[^\s\)]+)\s*\)/gi, '$1');
                        // Remove bare rzp.io links from text since the interactive Pay button is rendered below
                        cleanText = cleanText.replace(/https?:\/\/rzp\.io\/[^\s\)]+/gi, '').replace(/Please use this link to complete the [^:]+:\s*/i, '').trim();

                        if (urlMatch && !urlMatch[0].includes('rzp.io')) {
                          attachedUrl = urlMatch[0].startsWith('http') ? urlMatch[0] : `${API_BASE}${urlMatch[0]}`;
                          cleanText = cleanText.replace(urlMatch[0], '').replace(/📄\s*You can view your invoice statement here:?\s*/i, '').trim();
                        }

                        let mediaDocs = msg.metadata?.media_documents || [];
                        if (mediaDocs.length === 0 && msg.sender === 'agent' && index === 0) {
                          const bills = (activeCustomer?.invoices && activeCustomer.invoices.length > 0)
                            ? activeCustomer.invoices.filter(i => i.status !== 'PAID')
                            : (selectedInvoice ? [selectedInvoice] : []);
                          if (bills.length > 0) {
                            mediaDocs = bills.map(b => ({
                              invoice_id: b.invoice_id,
                              filename: `${b.invoice_id}_bill.pdf`,
                              url: b.document_url || b.file_url || `/api/invoices/${encodeURIComponent(b.invoice_id)}/document?customer_phone=${encodeURIComponent(activeCustomer?.customer_phone || selectedPhone || '')}`
                            }));
                          }
                        }

                        return (
                          <>
                            <div>{renderWhatsAppText(cleanText || msg.text)}</div>

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
            maxWidth: '760px',
            maxHeight: '90vh',
            overflowY: 'auto',
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

            <form onSubmit={handleSaveEditInvoice} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
              {/* Top Row: Invoice # and Brief Description */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '14px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                    Invoice #
                  </label>
                  <input
                    type="text"
                    value={editingInvoice.invoice_number || editingInvoice.invoice_id}
                    disabled
                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', color: 'var(--text-muted)', fontSize: '0.88rem', cursor: 'not-allowed' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                    Brief Description / Summary
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. Monthly Server Maintenance & Cloud Retainer"
                    value={editingInvoice.summary_description}
                    onChange={(e) => setEditingInvoice({ ...editingInvoice, summary_description: e.target.value })}
                    style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                  />
                </div>
              </div>

              {/* 2-Column Section: Customer & Addresses */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '18px', padding: '16px', background: 'var(--bg-dark)', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                {/* Left Column: Customer & Dates */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      Billing To (Customer Name) *
                    </label>
                    <input
                      type="text"
                      value={editingInvoice.customer_name}
                      onChange={(e) => setEditingInvoice({ ...editingInvoice, customer_name: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                      required
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      WhatsApp Phone Number *
                    </label>
                    <input
                      type="text"
                      value={editingInvoice.customer_phone}
                      onChange={(e) => setEditingInvoice({ ...editingInvoice, customer_phone: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                      required
                    />
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Issue Date
                      </label>
                      <input
                        type="date"
                        value={editingInvoice.invoice_date}
                        onChange={(e) => setEditingInvoice({ ...editingInvoice, invoice_date: e.target.value })}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.82rem' }}
                      />
                    </div>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Expiry / Due Date *
                      </label>
                      <input
                        type="date"
                        value={editingInvoice.due_date}
                        onChange={(e) => setEditingInvoice({ ...editingInvoice, due_date: e.target.value })}
                        style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.82rem' }}
                        required
                      />
                    </div>
                  </div>
                </div>

                {/* Right Column: Addresses */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      Billing Address
                    </label>
                    <textarea
                      rows="2"
                      placeholder="Enter billing address..."
                      value={editingInvoice.billing_address}
                      onChange={(e) => setEditingInvoice({ ...editingInvoice, billing_address: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.85rem', resize: 'vertical' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      Shipping Address
                    </label>
                    <textarea
                      rows="2"
                      placeholder="Enter shipping address..."
                      value={editingInvoice.shipping_address}
                      onChange={(e) => setEditingInvoice({ ...editingInvoice, shipping_address: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.85rem', resize: 'vertical' }}
                    />
                  </div>
                </div>
              </div>

              {/* Line Items Table */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <label style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--text-main)' }}>
                    Itemized Line Items
                  </label>
                  <button
                    type="button"
                    onClick={handleAddEditLineItem}
                    style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: '0.82rem', fontWeight: '600', cursor: 'pointer' }}
                  >
                    + Add Line Item
                  </button>
                </div>

                <div style={{ border: '1px solid var(--border-color)', borderRadius: '10px', overflow: 'hidden', background: '#FFF' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                    <thead>
                      <tr style={{ background: 'var(--bg-dark)', borderBottom: '1px solid var(--border-color)', textAlign: 'left', color: 'var(--text-muted)' }}>
                        <th style={{ padding: '8px 12px', fontWeight: '600' }}>DESCRIPTION</th>
                        <th style={{ padding: '8px 12px', fontWeight: '600', width: '130px' }}>RATE/ITEM (₹)</th>
                        <th style={{ padding: '8px 12px', fontWeight: '600', width: '80px' }}>QTY</th>
                        <th style={{ padding: '8px 12px', fontWeight: '600', width: '130px', textAlign: 'right' }}>TOTAL (₹)</th>
                        <th style={{ padding: '8px 8px', width: '40px', textAlign: 'center' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {(editingInvoice.line_items || []).map((item, idx) => (
                        <tr key={idx} style={{ borderBottom: '1px solid #F1F5F9' }}>
                          <td style={{ padding: '8px 10px' }}>
                            <input
                              type="text"
                              placeholder="Select or enter item description"
                              value={item.description}
                              onChange={(e) => handleEditLineItemChange(idx, 'description', e.target.value)}
                              style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                            />
                          </td>
                          <td style={{ padding: '8px 10px' }}>
                            <input
                              type="number"
                              step="0.01"
                              placeholder="0.00"
                              value={item.rate}
                              onChange={(e) => handleEditLineItemChange(idx, 'rate', e.target.value)}
                              style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                            />
                          </td>
                          <td style={{ padding: '8px 10px' }}>
                            <input
                              type="number"
                              min="1"
                              value={item.quantity}
                              onChange={(e) => handleEditLineItemChange(idx, 'quantity', e.target.value)}
                              style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                            />
                          </td>
                          <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: '600', color: 'var(--text-main)' }}>
                            ₹{parseFloat(item.total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                          </td>
                          <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                            <button
                              type="button"
                              onClick={() => handleRemoveEditLineItem(idx)}
                              style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.9rem' }}
                              title="Remove line item"
                            >
                              ✕
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Total Amount Summary */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '16px', padding: '12px 18px', background: 'var(--bg-dark)', borderRadius: '10px', border: '1px solid var(--border-color)' }}>
                <span style={{ fontSize: '0.95rem', fontWeight: '700', color: 'var(--text-main)' }}>
                  Total Invoice Amount:
                </span>
                <span style={{ fontSize: '1.2rem', fontWeight: '800', color: 'var(--primary)' }}>
                  ₹{parseFloat(editingInvoice.original_amount_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                </span>
              </div>

              {/* Record Manual / Offline Payment Section */}
              <div style={{ padding: '16px', borderRadius: '12px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <label style={{ fontSize: '0.85rem', fontWeight: '600', color: 'var(--text-main)' }}>
                    💳 Record Offline / Partial Payment (₹ INR)
                  </label>
                  <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Remaining Balance: ₹{editingInvoice.remaining_amount_inr?.toLocaleString('en-IN')}
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

              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
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
                    fontWeight: '600',
                    fontSize: '0.88rem',
                    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.15)'
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
            maxWidth: '760px',
            maxHeight: '90vh',
            overflowY: 'auto',
            padding: '32px',
            borderRadius: '16px',
            background: '#FFFFFF',
            border: '1px solid var(--border-color)',
            boxShadow: '0 20px 40px rgba(0, 0, 0, 0.12)'
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
              <div>
                <h2 style={{ fontSize: '1.4rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '4px' }}>Add New Invoice</h2>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Upload an invoice bill to auto-extract or enter details manually</p>
              </div>
              <button
                onClick={() => setIsCreateModalOpen(false)}
                style={{ background: 'none', border: 'none', color: 'var(--text-muted)', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* Step 1: Mandatory AI File Extraction Dropzone */}
            <div style={{
              marginBottom: '20px',
              padding: newBillData.file_name ? '14px 18px' : '24px 20px',
              borderRadius: '12px',
              border: newBillData.file_name ? '1px solid var(--success)' : '2px dashed var(--primary)',
              background: newBillData.file_name ? 'var(--success-bg)' : 'rgba(59, 130, 246, 0.04)',
              textAlign: 'center',
              cursor: 'pointer',
              position: 'relative',
              transition: 'all 0.2s',
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
                  <span>✨</span> Reading and extracting all line items, dates & amounts...
                </div>
              ) : extractError ? (
                <div>
                  <p style={{ fontSize: '0.88rem', fontWeight: '600', color: 'var(--danger)', marginBottom: '4px' }}>
                    ⚠️ {extractError}
                  </p>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    You can edit and fill details below, or click here to upload another file.
                  </p>
                </div>
              ) : newBillData.file_name ? (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', textAlign: 'left' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <span style={{ fontSize: '1.4rem' }}>📄</span>
                    <div>
                      <div style={{ fontWeight: '600', fontSize: '0.88rem', color: 'var(--text-main)' }}>
                        {newBillData.file_name}
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--success)', fontWeight: '500' }}>
                        ✓ Document Attached & Line Items Auto-Extracted
                      </div>
                    </div>
                  </div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--primary)', fontWeight: '600', textDecoration: 'underline' }}>
                    Change File
                  </span>
                </div>
              ) : (
                <div>
                  <p style={{ fontSize: '0.95rem', fontWeight: '600', color: 'var(--primary)', marginBottom: '4px' }}>
                    📁 Step 1: Upload Invoice File (Required)
                  </p>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
                    Upload a PDF or Image invoice. We will automatically extract Line Items, Rates, Addresses & Dates.
                  </p>
                </div>
              )}
            </div>

            {/* Step 2: Form Review & Submission (Unlocked only after file upload) */}
            {!newBillData.file_name && !isExtracting && (
              <div style={{ padding: '24px 20px', borderRadius: '12px', background: 'var(--bg-dark)', border: '1px solid var(--border-color)', textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                🔒 <strong>Step 2 is locked:</strong> Please upload an invoice bill above to automatically populate and edit details.
              </div>
            )}

            {newBillData.file_name && (
              <form onSubmit={handleCreateBill} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
                <div style={{ fontSize: '0.8rem', fontWeight: '700', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.5px' }}>
                  Step 2: Review & Edit Extracted Invoice
                </div>

                {/* Top Row: Invoice # and Brief Description */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: '14px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      Invoice #
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. INV-2026-001"
                      value={newBillData.invoice_number}
                      onChange={(e) => setNewBillData({ ...newBillData, invoice_number: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                    />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                      Brief Description / Summary
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. Monthly Server Maintenance & Cloud Retainer"
                      value={newBillData.summary_description}
                      onChange={(e) => setNewBillData({ ...newBillData, summary_description: e.target.value })}
                      style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                    />
                  </div>
                </div>

                {/* 2-Column Section: Billing Details & Addresses */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '18px', padding: '16px', background: 'var(--bg-dark)', borderRadius: '12px', border: '1px solid var(--border-color)' }}>
                  {/* Left Column: Customer & Dates */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Billing To (Customer Name) *
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. Rajesh Enterprises"
                        value={newBillData.customer_name}
                        onChange={(e) => setNewBillData({ ...newBillData, customer_name: e.target.value })}
                        style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                        required
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Customer WhatsApp Phone *
                      </label>
                      <input
                        type="text"
                        placeholder="e.g. +919812345678"
                        value={newBillData.customer_phone}
                        onChange={(e) => setNewBillData({ ...newBillData, customer_phone: e.target.value })}
                        style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.88rem' }}
                        required
                      />
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                          Issue Date
                        </label>
                        <input
                          type="date"
                          value={newBillData.invoice_date}
                          onChange={(e) => setNewBillData({ ...newBillData, invoice_date: e.target.value })}
                          style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.82rem' }}
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '0.78rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                          Expiry / Due Date *
                        </label>
                        <input
                          type="date"
                          value={newBillData.due_date}
                          onChange={(e) => setNewBillData({ ...newBillData, due_date: e.target.value })}
                          style={{ width: '100%', padding: '8px 10px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.82rem' }}
                          required
                        />
                      </div>
                    </div>
                  </div>

                  {/* Right Column: Billing & Shipping Addresses */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Billing Address
                      </label>
                      <textarea
                        rows="2"
                        placeholder="Enter full registered billing address..."
                        value={newBillData.billing_address}
                        onChange={(e) => setNewBillData({ ...newBillData, billing_address: e.target.value })}
                        style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.85rem', resize: 'vertical' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '0.82rem', fontWeight: '600', color: 'var(--text-main)', marginBottom: '5px' }}>
                        Shipping Address
                      </label>
                      <textarea
                        rows="2"
                        placeholder="Enter delivery or shipping address..."
                        value={newBillData.shipping_address}
                        onChange={(e) => setNewBillData({ ...newBillData, shipping_address: e.target.value })}
                        style={{ width: '100%', padding: '9px 12px', borderRadius: '8px', background: '#FFF', border: '1px solid var(--border-color)', color: 'var(--text-main)', fontSize: '0.85rem', resize: 'vertical' }}
                      />
                    </div>
                  </div>
                </div>

                {/* Line Items Table */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                    <label style={{ fontSize: '0.85rem', fontWeight: '700', color: 'var(--text-main)' }}>
                      Itemized Line Items
                    </label>
                    <button
                      type="button"
                      onClick={handleAddLineItem}
                      style={{ background: 'none', border: 'none', color: 'var(--primary)', fontSize: '0.82rem', fontWeight: '600', cursor: 'pointer' }}
                    >
                      + Add Line Item
                    </button>
                  </div>

                  <div style={{ border: '1px solid var(--border-color)', borderRadius: '10px', overflow: 'hidden', background: '#FFF' }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                      <thead>
                        <tr style={{ background: 'var(--bg-dark)', borderBottom: '1px solid var(--border-color)', textAlign: 'left', color: 'var(--text-muted)' }}>
                          <th style={{ padding: '8px 12px', fontWeight: '600' }}>DESCRIPTION</th>
                          <th style={{ padding: '8px 12px', fontWeight: '600', width: '130px' }}>RATE/ITEM (₹)</th>
                          <th style={{ padding: '8px 12px', fontWeight: '600', width: '80px' }}>QTY</th>
                          <th style={{ padding: '8px 12px', fontWeight: '600', width: '130px', textAlign: 'right' }}>TOTAL (₹)</th>
                          <th style={{ padding: '8px 8px', width: '40px', textAlign: 'center' }}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {(newBillData.line_items || []).map((item, idx) => (
                          <tr key={idx} style={{ borderBottom: '1px solid #F1F5F9' }}>
                            <td style={{ padding: '8px 10px' }}>
                              <input
                                type="text"
                                placeholder="Select or enter item description"
                                value={item.description}
                                onChange={(e) => handleLineItemChange(idx, 'description', e.target.value)}
                                style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                              />
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              <input
                                type="number"
                                step="0.01"
                                placeholder="0.00"
                                value={item.rate}
                                onChange={(e) => handleLineItemChange(idx, 'rate', e.target.value)}
                                style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                              />
                            </td>
                            <td style={{ padding: '8px 10px' }}>
                              <input
                                type="number"
                                min="1"
                                value={item.quantity}
                                onChange={(e) => handleLineItemChange(idx, 'quantity', e.target.value)}
                                style={{ width: '100%', padding: '6px 8px', borderRadius: '6px', border: '1px solid var(--border-color)', fontSize: '0.84rem' }}
                              />
                            </td>
                            <td style={{ padding: '8px 10px', textAlign: 'right', fontWeight: '600', color: 'var(--text-main)' }}>
                              ₹{parseFloat(item.total || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                            </td>
                            <td style={{ padding: '8px 6px', textAlign: 'center' }}>
                              <button
                                type="button"
                                onClick={() => handleRemoveLineItem(idx)}
                                style={{ background: 'none', border: 'none', color: 'var(--danger)', cursor: 'pointer', fontSize: '0.9rem' }}
                                title="Remove line item"
                              >
                                ✕
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Total Amount Summary Header */}
                <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: '16px', padding: '14px 18px', background: 'var(--bg-dark)', borderRadius: '10px', border: '1px solid var(--border-color)', marginTop: '4px' }}>
                  <span style={{ fontSize: '1rem', fontWeight: '700', color: 'var(--text-main)' }}>
                    Total Amount:
                  </span>
                  <span style={{ fontSize: '1.25rem', fontWeight: '800', color: 'var(--primary)' }}>
                    ₹{parseFloat(newBillData.original_amount_inr || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                  <button
                    type="button"
                    onClick={() => {
                      setIsCreateModalOpen(false);
                      setNewBillData({
                        invoice_number: '',
                        summary_description: '',
                        customer_name: '',
                        customer_phone: '',
                        invoice_date: new Date().toISOString().split('T')[0],
                        due_date: new Date().toISOString().split('T')[0],
                        billing_address: '',
                        shipping_address: '',
                        line_items: [
                          { description: '', rate: '', quantity: 1, total: 0 }
                        ],
                        original_amount_inr: '',
                        file_bytes_b64: null,
                        file_name: null,
                        file_mime_type: null
                      });
                    }}
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
                      background: 'var(--primary)',
                      color: '#FFF',
                      border: 'none',
                      cursor: 'pointer',
                      fontWeight: '600',
                      fontSize: '0.88rem',
                      boxShadow: '0 2px 8px rgba(218, 119, 86, 0.25)'
                    }}
                  >
                    Create Invoice Bill
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

    </div>
  );
}
