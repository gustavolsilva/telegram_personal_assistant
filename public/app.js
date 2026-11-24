import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import htm from "htm";

const html = htm.bind(React.createElement);

const fmtBRL = (cents = 0) =>
  (cents / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });

function getHeaders() {
  const token = localStorage.getItem("tpa_access_token") || "";
  const headers = { "Content-Type": "application/json" };
  if (token) headers["X-Access-Token"] = token;
  return headers;
}

async function apiFetch(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { ...getHeaders(), ...(options.headers || {}) },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function getPeriodRange(period) {
  const now = new Date();
  let start;
  let end = now;
  if (period === "today") {
    start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0);
  } else if (period === "7d") {
    start = new Date(now.getTime() - 7 * 86400 * 1000);
  } else if (period === "prev_month") {
    start = new Date(now.getFullYear(), now.getMonth() - 1, 1, 0, 0, 0);
    end = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59);
  } else {
    start = new Date(now.getFullYear(), now.getMonth(), 1, 0, 0, 0);
  }
  return { start: start.toISOString(), end: end.toISOString(), refDate: start };
}

function EChartBox({ option, height = 280, isDark }) {
  const ref = useRef(null);
  const instanceRef = useRef(null);

  useEffect(() => {
    if (!ref.current || typeof window.echarts === "undefined") return;
    if (instanceRef.current) instanceRef.current.dispose();
    const chart = window.echarts.init(ref.current, isDark ? "dark" : undefined);
    instanceRef.current = chart;
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      instanceRef.current = null;
    };
  }, [isDark]);

  useEffect(() => {
    if (instanceRef.current && option) {
      instanceRef.current.setOption({ backgroundColor: "transparent", ...option }, true);
      instanceRef.current.resize();
    }
  }, [option, height]);

  return html`<div ref=${ref} style=${{ width: "100%", height: `${height}px` }}></div>`;
}

function DeltaPill({ pct, invertColors = false }) {
  if (pct === null || pct === undefined) {
    return html`<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-200/70 dark:bg-white/10 text-slate-500 dark:text-slate-400">Sem base</span>`;
  }
  const positive = pct >= 0;
  const good = invertColors ? !positive : positive;
  const cls = good
    ? "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400"
    : "bg-rose-500/15 text-rose-600 dark:text-rose-400";
  return html`
    <span class=${`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold tabular-nums ${cls}`}>
      ${positive ? "↗" : "↘"} ${Math.abs(pct)}%
    </span>
  `;
}

function App() {
  const [authChecked, setAuthChecked] = useState(false);
  const [authRequired, setAuthRequired] = useState(true);
  const [usernameRequired, setUsernameRequired] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [authError, setAuthError] = useState(false);
  const [loginUser, setLoginUser] = useState("");
  const [loginPass, setLoginPass] = useState("");
  const [trustBrowser, setTrustBrowser] = useState(true);
  const [twoFAChallenge, setTwoFAChallenge] = useState(null);
  const [twoFACode, setTwoFACode] = useState("");
  const [loginError, setLoginError] = useState("");
  const [loginLoading, setLoginLoading] = useState(false);
  const [showPass, setShowPass] = useState(false);

  const [tab, setTab] = useState("overview");
  const [period, setPeriod] = useState("month");
  const [isDark, setIsDark] = useState(() => (localStorage.getItem("tpa_theme") || "dark") === "dark");
  const [offline, setOffline] = useState(false);
  const [toast, setToast] = useState(null);

  const [categories, setCategories] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [summary, setSummary] = useState(null);
  const [daily, setDaily] = useState(null);
  const [monthly, setMonthly] = useState([]);
  const [catBreakdown, setCatBreakdown] = useState([]);
  const [weekdays, setWeekdays] = useState([]);
  const [balances, setBalances] = useState(null);
  const [installments, setInstallments] = useState([]);
  const [bills, setBills] = useState([]);
  const [upcoming, setUpcoming] = useState([]);
  const [transactions, setTransactions] = useState([]);
  const [syncStatus, setSyncStatus] = useState(null);

  const [billForm, setBillForm] = useState({
    name: "",
    amount: "",
    due_day: 10,
    recurrence: "monthly",
    due_month: 1,
    category_id: "",
    account_id: "",
  });
  const [cardForm, setCardForm] = useState({ name: "", closing_day: 3, due_day: 10 });
  const [accountForm, setAccountForm] = useState({ name: "", type: "checking", initial_balance: "" });

  const [search, setSearch] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterCat, setFilterCat] = useState("");

  const [quickCmd, setQuickCmd] = useState("");
  const [quickLoading, setQuickLoading] = useState(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatMsgs, setChatMsgs] = useState([
    {
      who: "bot",
      text: "Olá! Pergunte seu saldo, parcelas ou registre um gasto direto aqui (ex: '45,90 almoço nubank').",
    },
  ]);

  const [modalOpen, setModalOpen] = useState(false);
  const [txForm, setTxForm] = useState({
    tx_type: "expense",
    amount: "",
    description: "",
    category_id: "",
    account_id: "",
    transfer_to_account_id: "",
    installments_total: 1,
  });

  const [accessToken, setAccessToken] = useState(() => localStorage.getItem("tpa_access_token") || "");
  const [sidebarPinned, setSidebarPinned] = useState(() => localStorage.getItem("tpa_sidebar_pinned") !== "false");
  const [sidebarHovered, setSidebarHovered] = useState(false);
  const [privacyMode, setPrivacyMode] = useState(() => localStorage.getItem("tpa_privacy") === "true");
  const [activeCardIdx, setActiveCardIdx] = useState(0);
  const [selectedCatFilter, setSelectedCatFilter] = useState(null);

  const sidebarExpanded = sidebarPinned || sidebarHovered;

  const showMoney = useCallback(
    (cents = 0) => (privacyMode ? "R$ •••••" : fmtBRL(cents)),
    [privacyMode]
  );

  useEffect(() => {
    localStorage.setItem("tpa_privacy", String(privacyMode));
  }, [privacyMode]);

  useEffect(() => {
    localStorage.setItem("tpa_sidebar_pinned", String(sidebarPinned));
    const timer = setTimeout(() => window.dispatchEvent(new Event("resize")), 220);
    return () => clearTimeout(timer);
  }, [sidebarPinned, sidebarHovered]);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    localStorage.setItem("tpa_theme", isDark ? "dark" : "light");
  }, [isDark]);

  const showToast = useCallback((msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 3200);
  }, []);

  const loadAll = useCallback(async () => {
    try {
      setOffline(false);
      const { start, end, refDate } = getPeriodRange(period);
      const qs = `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;

      const [cats, accs, sum, dly, mth, cbd, wkd, bal, inst, billsData, upcData, txs, sync] = await Promise.all([
        apiFetch("/api/finance/categories"),
        apiFetch("/api/finance/accounts"),
        apiFetch(`/api/finance/summary?${qs}`),
        apiFetch(`/api/finance/charts/daily?year=${refDate.getFullYear()}&month=${refDate.getMonth() + 1}`),
        apiFetch("/api/finance/charts/monthly?months=6"),
        apiFetch(`/api/finance/charts/categories?${qs}&tx_type=expense`),
        apiFetch(`/api/finance/charts/weekdays?${qs}`),
        apiFetch("/api/finance/balances"),
        apiFetch("/api/finance/installments"),
        apiFetch("/api/finance/bills"),
        apiFetch("/api/finance/upcoming"),
        apiFetch(`/api/finance/transactions?limit=100`),
        apiFetch("/api/finance/sync-status"),
      ]);

      setCategories(cats);
      setAccounts(accs);
      setSummary(sum);
      setDaily(dly);
      setMonthly(mth);
      setCatBreakdown(cbd);
      setWeekdays(wkd);
      setBalances(bal);
      setInstallments(inst);
      setBills(billsData);
      setUpcoming(upcData);
      setTransactions(txs);
      setSyncStatus(sync);

      setBillForm((prev) => ({
        ...prev,
        category_id: prev.category_id || cats.find((c) => c.name === "Moradia")?.id || cats[0]?.id || "",
        account_id: prev.account_id || accs[0]?.id || "",
      }));

      setTxForm((prev) => ({
        ...prev,
        category_id: prev.category_id || cats.find((c) => c.type === prev.tx_type)?.id || "",
        account_id: prev.account_id || accs[0]?.id || "",
        transfer_to_account_id: prev.transfer_to_account_id || accs[1]?.id || accs[0]?.id || "",
      }));
    } catch {
      setOffline(true);
    }
  }, [period]);

  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }
    (async () => {
      try {
        const status = await apiFetch("/api/auth/status");
        setAuthError(false);
        setAuthRequired(Boolean(status.auth_required));
        setUsernameRequired(Boolean(status.username_required));
        setAuthenticated(Boolean(status.authenticated));
        setAuthChecked(true);
        if (status.authenticated) {
          await loadAll();
        }
      } catch {
        setAuthError(true);
        setAuthChecked(true);
      }
    })();
  }, [loadAll]);

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoginError("");
    setLoginLoading(true);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: loginUser, password: loginPass, trust_browser: trustBrowser }),
      });
      if (!res.ok) {
        setLoginError("Usuário ou senha incorretos.");
        return;
      }
      const data = await res.json();
      if (data.requires_2fa) {
        setTwoFAChallenge(data.challenge_token);
        setTwoFACode("");
        return;
      }
      if (data.token) {
        localStorage.setItem("tpa_access_token", data.token);
        setAccessToken(data.token);
      }
      setLoginPass("");
      setAuthenticated(true);
      await loadAll();
    } catch {
      setLoginError("Erro de conexão ao autenticar.");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleVerify2FA = async (e) => {
    e.preventDefault();
    setLoginError("");
    setLoginLoading(true);
    try {
      const res = await fetch("/api/auth/verify-2fa", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          challenge_token: twoFAChallenge,
          code: twoFACode,
          trust_browser: trustBrowser,
        }),
      });
      if (!res.ok) {
        setLoginError("Código 2FA inválido ou expirado.");
        return;
      }
      const data = await res.json();
      if (data.token) {
        localStorage.setItem("tpa_access_token", data.token);
        setAccessToken(data.token);
      }
      setTwoFAChallenge(null);
      setTwoFACode("");
      setLoginPass("");
      setAuthenticated(true);
      await loadAll();
    } catch {
      setLoginError("Erro de conexão ao validar 2FA.");
    } finally {
      setLoginLoading(false);
    }
  };

  const handleLogout = async () => {
    localStorage.removeItem("tpa_access_token");
    setAccessToken("");
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    if (authRequired) setAuthenticated(false);
  };

  const openModalWithType = (type) => {
    const ct = type === "transfer" ? "expense" : type;
    const firstCat = categories.find((c) => c.type === ct)?.id || "";
    setTxForm((p) => ({ ...p, tx_type: type, category_id: firstCat }));
    setModalOpen(true);
  };

  const sendConversational = async (text, fromWidget = false) => {
    const clean = text.trim();
    if (!clean) return;
    if (fromWidget) {
      setChatMsgs((m) => [...m, { who: "user", text: clean }]);
      setChatInput("");
    } else {
      setQuickLoading(true);
    }
    try {
      const res = await apiFetch("/api/finance/chat", {
        method: "POST",
        body: JSON.stringify({ message: clean }),
      });
      if (fromWidget) {
        setChatMsgs((m) => [...m, { who: "bot", text: res.reply }]);
      } else {
        setQuickCmd("");
        showToast(res.reply.split("\n")[0]);
        if (!res.refresh) {
          setChatMsgs((m) => [...m, { who: "user", text: clean }, { who: "bot", text: res.reply }]);
          setChatOpen(true);
        }
      }
      if (res.refresh) await loadAll();
    } catch {
      if (fromWidget) {
        setChatMsgs((m) => [...m, { who: "bot", text: "⚠️ Falha de conexão com a API." }]);
      } else {
        showToast("Erro ao processar comando.");
      }
    } finally {
      setQuickLoading(false);
    }
  };

  const handleDeleteTx = async (id) => {
    await apiFetch(`/api/finance/transactions/${id}`, { method: "DELETE" });
    showToast("🗑️ Lançamento removido.");
    await loadAll();
  };

  const handleAdjustBalance = async (acc) => {
    const cur = (acc.balance_cents / 100).toFixed(2).replace(".", ",");
    const raw = prompt(`Ajustar saldo atual de "${acc.name}" (R$):`, cur);
    if (raw === null) return;
    const val = parseFloat(raw.replace(/\./g, "").replace(",", "."));
    if (Number.isNaN(val)) return;
    await apiFetch(`/api/finance/accounts/${acc.id}/balance`, {
      method: "PATCH",
      body: JSON.stringify({ target_balance_cents: Math.round(val * 100) }),
    });
    showToast(`✅ Saldo de ${acc.name} atualizado.`);
    await loadAll();
  };

  const handleCreateTx = async (e) => {
    e.preventDefault();
    const amountCents = Math.round(parseFloat(txForm.amount) * 100);
    if (!amountCents || amountCents <= 0) return;
    await apiFetch("/api/finance/transactions", {
      method: "POST",
      body: JSON.stringify({
        tx_type: txForm.tx_type,
        amount_cents: amountCents,
        description: txForm.description,
        category_id: txForm.category_id,
        account_id: txForm.account_id,
        transfer_to_account_id: txForm.tx_type === "transfer" ? txForm.transfer_to_account_id : null,
        installments_total: txForm.tx_type === "expense" ? Number(txForm.installments_total || 1) : 1,
      }),
    });
    setModalOpen(false);
    setTxForm((p) => ({ ...p, amount: "", description: "", installments_total: 1 }));
    showToast("✅ Lançamento salvo!");
    await loadAll();
  };

  const filteredTransactions = useMemo(() => {
    return transactions.filter((t) => {
      if (filterType && t.type !== filterType) return false;
      if (filterCat && t.category_id !== filterCat) return false;
      if (search && !t.description.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [transactions, filterType, filterCat, search]);

  const exportCSV = () => {
    const header = "Data,Tipo,Valor_BRL,Descricao,Categoria,Conta\n";
    const rows = filteredTransactions
      .map((t) =>
        [
          new Date(t.occurred_at).toLocaleDateString("pt-BR"),
          t.type,
          (t.amount_cents / 100).toFixed(2),
          `"${t.description.replace(/"/g, '""')}"`,
          `"${t.category_name}"`,
          `"${t.account_name}"`,
        ].join(",")
      )
      .join("\n");
    const blob = new Blob([header + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "extrato_financeiro.csv";
    a.click();
    URL.revokeObjectURL(url);
  };

  const dailyOption = useMemo(() => {
    if (!daily) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0, textStyle: { fontSize: 11 } },
      grid: { left: 46, right: 12, top: 34, bottom: 24 },
      xAxis: { type: "category", data: daily.days.map((d) => d.day), axisLine: { show: false }, axisTick: { show: false } },
      yAxis: { type: "value", splitLine: { lineStyle: { opacity: 0.08 } } },
      series: [
        {
          name: "Ganhos",
          type: "bar",
          barMaxWidth: 10,
          itemStyle: { color: "#10b981", borderRadius: [4, 4, 0, 0] },
          data: daily.days.map((d) => +(d.income_cents / 100).toFixed(2)),
        },
        {
          name: "Gastos",
          type: "bar",
          barMaxWidth: 10,
          itemStyle: { color: "#f43f5e", borderRadius: [4, 4, 0, 0] },
          data: daily.days.map((d) => +(d.expense_cents / 100).toFixed(2)),
        },
        {
          name: "Saldo Acum.",
          type: "line",
          smooth: true,
          symbol: "none",
          lineStyle: { width: 2.5, color: "#6366f1" },
          areaStyle: {
            color: {
              type: "linear", x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: "rgba(99, 102, 241, 0.28)" },
                { offset: 1, color: "rgba(99, 102, 241, 0.0)" },
              ],
            },
          },
          data: daily.days.map((d) => +(d.cumulative_balance_cents / 100).toFixed(2)),
        },
      ],
    };
  }, [daily]);

  const categoryOption = useMemo(() => {
    const sorted = [...catBreakdown].sort((a, b) => b.total_cents - a.total_cents);
    return {
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "none" },
        formatter: (params) => {
          const item = sorted[params[0]?.dataIndex ?? 0];
          if (!item) return "";
          return `${item.icon} ${item.name}: <b>${privacyMode ? "R$ •••••" : fmtBRL(item.total_cents)}</b> (${item.share_pct}%)`;
        },
      },
      grid: { left: 108, right: 92, top: 8, bottom: 8 },
      xAxis: { type: "value", show: false, max: (v) => Math.ceil(v.max * 1.15) },
      yAxis: {
        type: "category",
        inverse: true,
        data: sorted.map((c) => `${c.icon} ${c.name}`),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          fontSize: 11,
          color: isDark ? "#cbd5e1" : "#334155",
          width: 96,
          overflow: "truncate",
        },
      },
      series: [
        {
          type: "bar",
          barMaxWidth: 16,
          showBackground: true,
          backgroundStyle: {
            color: isDark ? "rgba(255,255,255,0.04)" : "rgba(15,23,42,0.04)",
            borderRadius: [0, 8, 8, 0],
          },
          label: {
            show: true,
            position: "right",
            fontSize: 11,
            fontWeight: 600,
            color: isDark ? "#e2e8f0" : "#1e293b",
            formatter: (params) => {
              const item = sorted[params.dataIndex];
              if (!item) return "";
              return privacyMode ? `${item.share_pct}%` : `${fmtBRL(item.total_cents)} (${item.share_pct}%)`;
            },
          },
          data: sorted.map((c) => ({
            value: +(c.total_cents / 100).toFixed(2),
            itemStyle: { color: c.color, borderRadius: [0, 8, 8, 0] },
          })),
        },
      ],
    };
  }, [catBreakdown, isDark, privacyMode]);

  const monthlyOption = useMemo(() => ({
    tooltip: { trigger: "axis" },
    legend: { bottom: 0 },
    grid: { left: 48, right: 16, top: 20, bottom: 38 },
    xAxis: { type: "category", data: monthly.map((m) => m.label) },
    yAxis: { type: "value", splitLine: { lineStyle: { opacity: 0.08 } } },
    series: [
      { name: "Ganhos", type: "bar", itemStyle: { color: "#10b981", borderRadius: [6, 6, 0, 0] }, data: monthly.map((m) => +(m.income_cents / 100).toFixed(2)) },
      { name: "Gastos", type: "bar", itemStyle: { color: "#f43f5e", borderRadius: [6, 6, 0, 0] }, data: monthly.map((m) => +(m.expense_cents / 100).toFixed(2)) },
      { name: "Líquido", type: "line", smooth: true, lineStyle: { width: 3, color: "#6366f1" }, data: monthly.map((m) => +(m.net_cents / 100).toFixed(2)) },
    ],
  }), [monthly]);

  const dayCurveOption = useMemo(() => {
    if (!daily) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { bottom: 0 },
      grid: { left: 48, right: 16, top: 20, bottom: 38 },
      xAxis: { type: "category", data: daily.days.map((d) => d.day) },
      yAxis: { type: "value", splitLine: { lineStyle: { opacity: 0.08 } } },
      series: [
        { name: "Mês Atual", type: "line", smooth: true, symbol: "none", lineStyle: { width: 3, color: "#f43f5e" }, data: daily.days.map((d) => +(d.cumulative_expense_cents / 100).toFixed(2)) },
        { name: "Mês Anterior", type: "line", smooth: true, symbol: "none", lineStyle: { width: 2, type: "dashed", color: "#94a3b8" }, data: daily.days.map((d) => +(d.prev_month_cumulative_expense_cents / 100).toFixed(2)) },
      ],
    };
  }, [daily]);

  const weekdayOption = useMemo(() => ({
    tooltip: { trigger: "axis" },
    grid: { left: 48, right: 16, top: 20, bottom: 28 },
    xAxis: { type: "category", data: weekdays.map((w) => w.label) },
    yAxis: { type: "value", splitLine: { lineStyle: { opacity: 0.08 } } },
    series: [{ type: "bar", itemStyle: { color: "#8b5cf6", borderRadius: [8, 8, 0, 0] }, data: weekdays.map((w) => +(w.expense_cents / 100).toFixed(2)) }],
  }), [weekdays]);

  const navItems = [
    { id: "overview", label: "Dashboard", icon: "📊" },
    { id: "bills", label: "Fixas & Cartões", icon: "💳" },
    { id: "compare", label: "Análises", icon: "📈" },
    { id: "ledger", label: "Extrato", icon: "🧾" },
    { id: "settings", label: "Cofre & Sync", icon: "🔐" },
  ];

  const creditAccounts = (balances?.accounts || []).filter((a) => a.type === "credit");
  const safeCardIdx = creditAccounts.length ? activeCardIdx % creditAccounts.length : 0;
  const creditAccount = creditAccounts[safeCardIdx];
  const cashAccounts = (balances?.accounts || []).filter((a) => a.type !== "credit");
  const creditUsed = creditAccount
    ? Math.max(0, creditAccount.expenses_cents - creditAccount.incomes_cents - creditAccount.initial_balance_cents)
    : 0;
  const incomeCents = summary?.income_cents || 0;
  const expenseCents = summary?.expense_cents || 0;
  const burnPct = incomeCents > 0 ? Math.min(100, Math.round((expenseCents / incomeCents) * 100)) : 0;
  const modalCategories = categories.filter((c) => c.type === (txForm.tx_type === "transfer" ? "expense" : txForm.tx_type));

  if (!authChecked) {
    return html`
      <div class="min-h-screen flex items-center justify-center mesh-bg">
        <div class="text-sm font-semibold text-slate-400 animate-pulse">Verificando acesso seguro...</div>
      </div>
    `;
  }

  if (authError) {
    return html`
      <div class="min-h-screen flex items-center justify-center mesh-bg p-4">
        <div class="w-full max-w-sm p-6 rounded-3xl bg-white dark:bg-obsidian-900 border border-rose-500/30 text-center space-y-4">
          <div class="text-2xl">⚠️</div>
          <div class="text-sm font-semibold">Não foi possível verificar a autenticação com o servidor.</div>
          <button
            onClick=${() => window.location.reload()}
            class="px-4 py-2.5 rounded-xl bg-royal-600 dark:bg-gold-500 text-white dark:text-obsidian-950 text-xs font-bold"
          >
            Tentar Novamente
          </button>
        </div>
      </div>
    `;
  }

  if (authRequired && !authenticated) {
    return html`
      <div class="min-h-screen flex items-center justify-center mesh-bg p-4">
        <div class="w-full max-w-md p-7 rounded-3xl bg-white/95 dark:bg-obsidian-900/95 backdrop-blur-xl border border-blue-100 dark:border-gold-500/25 shadow-2xl animate-enter">
          <div class="flex items-center justify-between mb-6">
            <div class="flex items-center gap-3">
              <div class="w-11 h-11 rounded-2xl bg-gradient-to-br from-royal-500 to-royal-700 dark:from-gold-400 dark:to-gold-600 flex items-center justify-center text-white dark:text-obsidian-950 font-extrabold text-lg shadow-lg">F</div>
              <div>
                <h1 class="font-extrabold text-lg tracking-tight">Finanças AI</h1>
                <p class="text-xs text-slate-400">Acesso Privado Protegido</p>
              </div>
            </div>
            <button
              type="button"
              onClick=${() => setIsDark(!isDark)}
              class="p-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm"
              title="Alternar tema"
            >
              ${isDark ? "☀️" : "🌙"}
            </button>
          </div>

          ${twoFAChallenge ? html`
            <form onSubmit=${handleVerify2FA} class="space-y-4">
              <div class="p-3.5 rounded-2xl bg-royal-500/10 dark:bg-gold-500/10 border border-royal-500/20 dark:border-gold-500/20 text-xs">
                📲 Enviamos um <strong>token aleatório de 6 dígitos</strong> para o seu Telegram.
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1.5">Código 2FA</label>
                <input
                  required
                  inputMode="numeric"
                  maxLength="6"
                  value=${twoFACode}
                  onInput=${(e) => setTwoFACode(e.target.value)}
                  placeholder="000000"
                  class="w-full px-4 py-3 rounded-2xl bg-slate-100 dark:bg-obsidian-800 text-center text-xl font-extrabold tracking-[0.4em] tabular-nums outline-none"
                />
              </div>

              ${loginError && html`
                <div class="px-3.5 py-2.5 rounded-xl bg-rose-500/15 text-rose-500 text-xs font-semibold">
                  ⚠️ ${loginError}
                </div>
              `}

              <div class="flex gap-2">
                <button
                  type="button"
                  onClick=${() => { setTwoFAChallenge(null); setLoginError(""); }}
                  class="px-4 py-3 rounded-2xl bg-slate-200 dark:bg-obsidian-800 text-xs font-semibold"
                >
                  Voltar
                </button>
                <button
                  type="submit"
                  disabled=${loginLoading}
                  class="flex-1 py-3 rounded-2xl bg-royal-600 hover:bg-royal-700 dark:bg-gradient-to-r dark:from-gold-400 dark:to-gold-500 text-white dark:text-obsidian-950 font-bold text-sm shadow-lg transition"
                >
                  ${loginLoading ? "Validando..." : "✅ Confirmar Token"}
                </button>
              </div>
            </form>
          ` : html`
            <form onSubmit=${handleLogin} class="space-y-4">
              <div>
                <label class="block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1.5">Usuário</label>
                <input
                  required
                  value=${loginUser}
                  onInput=${(e) => setLoginUser(e.target.value)}
                  placeholder="Seu usuário"
                  autocomplete="username"
                  class="w-full px-4 py-3 rounded-2xl bg-slate-100 dark:bg-obsidian-800 border border-transparent focus:border-royal-500 dark:focus:border-gold-500 text-sm outline-none"
                />
              </div>
              <div>
                <label class="block text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1.5">Senha de Acesso</label>
                <div class="relative">
                  <input
                    required
                    type=${showPass ? "text" : "password"}
                    value=${loginPass}
                    onInput=${(e) => setLoginPass(e.target.value)}
                    placeholder="••••••••••••"
                    autocomplete="current-password"
                    class="w-full px-4 py-3 pr-11 rounded-2xl bg-slate-100 dark:bg-obsidian-800 border border-transparent focus:border-royal-500 dark:focus:border-gold-500 text-sm outline-none"
                  />
                  <button
                    type="button"
                    onClick=${() => setShowPass(!showPass)}
                    class="absolute right-3 top-1/2 -translate-y-1/2 text-sm opacity-70 hover:opacity-100"
                  >
                    ${showPass ? "🙈" : "👁️"}
                  </button>
                </div>
              </div>

              <label class="flex items-center gap-2.5 text-xs text-slate-500 dark:text-slate-400 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked=${trustBrowser}
                  onChange=${(e) => setTrustBrowser(e.target.checked)}
                  class="rounded accent-royal-600 dark:accent-gold-500"
                />
                <span>Confiar neste navegador (manter conectado por 30 dias)</span>
              </label>

              ${loginError && html`
                <div class="px-3.5 py-2.5 rounded-xl bg-rose-500/15 text-rose-500 text-xs font-semibold">
                  ⚠️ ${loginError}
                </div>
              `}

              <button
                type="submit"
                disabled=${loginLoading}
                class="w-full py-3 rounded-2xl bg-royal-600 hover:bg-royal-700 dark:bg-gradient-to-r dark:from-gold-400 dark:to-gold-500 text-white dark:text-obsidian-950 font-bold text-sm shadow-lg transition"
              >
                ${loginLoading ? "Entrando..." : "🔐 Entrar no Painel"}
              </button>
            </form>
          `}
        </div>
      </div>
    `;
  }

  return html`
    <div class="min-h-screen flex mesh-bg">
      <!-- SIDEBAR (FIXA OU AUTOHIDE — PRETO/DOURADO NO DARK, BRANCO/AZUL NO LIGHT) -->
      <aside
        onMouseEnter=${() => setSidebarHovered(true)}
        onMouseLeave=${() => setSidebarHovered(false)}
        class=${`hidden md:flex flex-col border-r border-blue-100 dark:border-gold-500/15 bg-white/90 dark:bg-obsidian-900/90 backdrop-blur-xl sticky top-0 h-screen transition-all duration-200 z-30 ${
          sidebarExpanded ? "w-64 p-5" : "w-[74px] p-3 items-center"
        }`}
      >
        <div class=${`flex items-center pb-6 w-full ${sidebarExpanded ? "justify-between px-1" : "justify-center"}`}>
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-2xl bg-gradient-to-br from-royal-500 to-royal-700 dark:from-gold-400 dark:to-gold-600 flex items-center justify-center text-white dark:text-obsidian-950 font-extrabold shadow-lg shadow-royal-500/25 dark:shadow-gold-500/20 shrink-0">F</div>
            ${sidebarExpanded && html`
              <div>
                <div class="font-bold text-base tracking-tight whitespace-nowrap">Finanças AI</div>
                <div class="text-[11px] text-slate-500 dark:text-gold-300/80 flex items-center gap-1.5 whitespace-nowrap">
                  <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
                  Private Bot
                </div>
              </div>
            `}
          </div>
          ${sidebarExpanded && html`
            <button
              onClick=${() => setSidebarPinned(!sidebarPinned)}
              title=${sidebarPinned ? "Ativar Autohide (recolher)" : "Fixar painel lateral"}
              class=${`p-1.5 rounded-lg text-xs transition ${
                sidebarPinned
                  ? "bg-royal-500/15 text-royal-600 dark:bg-gold-500/20 dark:text-gold-400"
                  : "bg-slate-100 dark:bg-white/10 text-slate-400"
              }`}
            >
              ${sidebarPinned ? "📌" : "◀"}
            </button>
          `}
        </div>

        <nav class="flex flex-col gap-1.5 flex-1 w-full">
          ${navItems.map((item) => html`
            <button
              key=${item.id}
              onClick=${() => setTab(item.id)}
              title=${item.label}
              class=${`flex items-center rounded-xl text-sm font-medium transition-all ${
                sidebarExpanded ? "gap-3 px-3.5 py-2.5" : "justify-center p-3"
              } ${
                tab === item.id
                  ? "bg-royal-600 text-white dark:bg-gradient-to-r dark:from-gold-400 dark:to-gold-500 dark:text-obsidian-950 font-bold shadow-sm"
                  : "text-slate-600 dark:text-slate-400 hover:bg-blue-50 dark:hover:bg-white/5"
              }`}
            >
              <span class="text-base">${item.icon}</span>
              ${sidebarExpanded && html`<span class="whitespace-nowrap">${item.label}</span>`}
            </button>
          `)}
        </nav>

        ${sidebarExpanded ? html`
          <div class="p-4 rounded-2xl bg-gradient-to-br from-royal-600 to-royal-700 dark:from-obsidian-800 dark:to-black text-white border border-blue-400/20 dark:border-gold-500/25 text-xs w-full">
            <div class="font-semibold mb-1 flex items-center justify-between">
              <span class="dark:text-gold-300">Cofre Telegram</span>
              <span class="text-emerald-400">●</span>
            </div>
            <div class="text-blue-100 dark:text-slate-400 text-[11px]">
              ${syncStatus?.channel_configured ? "Backup AES-256 ativo" : "Configure o canal no .env"}
            </div>
          </div>
        ` : html`
          <button
            onClick=${() => setSidebarPinned(true)}
            title="Fixar menu lateral"
            class="p-2.5 rounded-xl bg-slate-100 dark:bg-white/5 text-xs text-slate-400 hover:text-royal-500 dark:hover:text-gold-400 transition"
          >
            📌
          </button>
        `}
      </aside>

      <!-- MAIN -->
      <main class="flex-1 max-w-7xl mx-auto w-full px-4 sm:px-7 py-5 pb-28 md:pb-10">
        <!-- TOPBAR -->
        <header class="flex flex-wrap items-center justify-between gap-4 mb-5">
          <div>
            <h1 class="text-2xl font-extrabold tracking-tight">${navItems.find((n) => n.id === tab)?.label}</h1>
            <p class="text-xs text-slate-500 dark:text-slate-400">
              ${offline ? "Modo offline · exibindo último cache" : "Visão financeira consolidada em tempo real"}
            </p>
          </div>

          <div class="flex flex-wrap items-center gap-2.5">
            <div class="inline-flex p-1 rounded-xl bg-slate-200/70 dark:bg-obsidian-900 border border-slate-200 dark:border-white/10">
              ${[
                { id: "today", label: "Hoje" },
                { id: "7d", label: "7 dias" },
                { id: "month", label: "Este mês" },
                { id: "prev_month", label: "Mês passado" },
              ].map((p) => html`
                <button
                  key=${p.id}
                  onClick=${() => setPeriod(p.id)}
                  class=${`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                    period === p.id
                      ? "bg-white dark:bg-obsidian-800 text-slate-900 dark:text-white shadow-sm"
                      : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-white"
                  }`}
                >
                  ${p.label}
                </button>
              `)}
            </div>

            <button
              onClick=${() => setPrivacyMode(!privacyMode)}
              class="p-2.5 rounded-xl bg-white dark:bg-obsidian-900 border border-slate-200 dark:border-white/10 hover:scale-105 transition"
              title=${privacyMode ? "Mostrar valores" : "Ocultar valores (Privacidade)"}
            >
              ${privacyMode ? "🙈" : "👁️"}
            </button>

            <button
              onClick=${() => setIsDark(!isDark)}
              class="p-2.5 rounded-xl bg-white dark:bg-obsidian-900 border border-slate-200 dark:border-white/10 hover:scale-105 transition"
              title="Alternar tema"
            >
              ${isDark ? "☀️" : "🌙"}
            </button>

            ${authRequired && html`
              <button
                onClick=${handleLogout}
                class="p-2.5 rounded-xl bg-white dark:bg-obsidian-900 border border-slate-200 dark:border-white/10 hover:text-rose-500 transition text-xs font-semibold"
                title="Sair / Bloquear painel"
              >
                🔒
              </button>
            `}
          </div>
        </header>

        <!-- BARRA CONVERSACIONAL RÁPIDA -->
        <form
          onSubmit=${(e) => { e.preventDefault(); sendConversational(quickCmd, false); }}
          class="mb-6 flex items-center gap-2 p-2 rounded-2xl bg-white/95 dark:bg-obsidian-900/90 backdrop-blur-xl border border-blue-100 dark:border-gold-500/20 shadow-sm focus-within:ring-2 focus-within:ring-royal-500/40 dark:focus-within:ring-gold-500/40"
        >
          <span class="pl-2.5 text-lg">✨</span>
          <input
            value=${quickCmd}
            onInput=${(e) => setQuickCmd(e.target.value)}
            placeholder="Comando rápido: '45,90 almoço nubank', '600 celular 6x' ou 'Qual meu saldo?'"
            class="flex-1 bg-transparent text-sm outline-none placeholder:text-slate-400 py-1.5 min-w-0"
          />
          <button
            type="submit"
            disabled=${quickLoading}
            class="px-4 py-2 rounded-xl bg-royal-600 hover:bg-royal-700 dark:bg-gradient-to-r dark:from-gold-400 dark:to-gold-500 text-white dark:text-obsidian-950 text-xs font-bold transition shrink-0"
          >
            ${quickLoading ? "..." : "Executar"}
          </button>
        </form>

        <!-- TAB 1: BENTO DASHBOARD -->
        ${tab === "overview" && html`
          <div class="space-y-5 animate-enter">
            ${upcoming.length > 0 && html`
              <div class="ticker-wrap h-10 px-3 rounded-2xl bg-amber-500/10 dark:bg-gold-500/10 border border-amber-500/25 dark:border-gold-500/25 flex items-center gap-3 overflow-hidden">
                <span class="shrink-0 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-lg bg-amber-500/20 dark:bg-gold-500/20 text-amber-700 dark:text-gold-300 text-[11px] font-extrabold uppercase tracking-wider">
                  <span class="w-1.5 h-1.5 rounded-full bg-amber-500 dark:bg-gold-400 animate-pulse"></span>
                  Vencimentos
                </span>
                <div class="flex-1 overflow-hidden relative">
                  <div class="ticker-track items-center gap-6 text-xs font-medium text-amber-900 dark:text-amber-100">
                    ${[...upcoming, ...upcoming].map((u, idx) => html`
                      <span key=${`${u.id}-${idx}`} class="inline-flex items-center gap-1.5 whitespace-nowrap">
                        <span>${u.title}</span>
                        <strong class="tabular-nums font-bold dark:text-gold-300">${showMoney(u.amount_cents)}</strong>
                        <span class="text-[10px] opacity-70">(${u.days_until_due < 0 ? "atrasado" : u.days_until_due === 0 ? "hoje" : `dia ${u.due_day}`})</span>
                        <span class="opacity-30 pl-3">•</span>
                      </span>
                    `)}
                  </div>
                </div>
                <button
                  onClick=${() => setTab("bills")}
                  class="shrink-0 px-2.5 py-1 rounded-lg bg-amber-500 hover:bg-amber-600 dark:bg-gold-500 dark:hover:bg-gold-400 text-white dark:text-obsidian-950 text-[11px] font-bold transition"
                >
                  Gerenciar
                </button>
              </div>
            `}
            <!-- BENTO ROW 1: WALLET HERO + VIRTUAL CARD CAROUSEL + KPI STACK -->
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">
              <!-- WALLET HERO (5 COLS) -->
              <div class="lg:col-span-5 p-6 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm card-interactive flex flex-col justify-between">
                <div>
                  <div class="flex items-center justify-between mb-1">
                    <span class="text-xs font-semibold uppercase tracking-wider text-slate-400">Saldo Disponível Total</span>
                    <span class="px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-500">
                      ${incomeCents > 0 ? `${burnPct}% da renda usada` : "Contas Ativas"}
                    </span>
                  </div>
                  <div class="text-3xl sm:text-4xl font-extrabold tabular-nums tracking-tight mt-1">
                    ${showMoney(balances?.total_available_cents || 0)}
                  </div>
                  ${incomeCents > 0 && html`
                    <div class="mt-3">
                      <div class="w-full h-1.5 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden">
                        <div
                          class=${`h-full rounded-full transition-all duration-500 ${burnPct > 85 ? "bg-rose-500" : burnPct > 65 ? "bg-amber-500" : "bg-emerald-500"}`}
                          style=${{ width: `${burnPct}%` }}
                        ></div>
                      </div>
                    </div>
                  `}
                </div>

                <!-- QUICK ACTIONS PILLS -->
                <div class="grid grid-cols-3 gap-2 my-5">
                  <button onClick=${() => openModalWithType("income")} class="py-2.5 px-3 rounded-2xl bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 text-xs font-bold transition">+ Receita</button>
                  <button onClick=${() => openModalWithType("expense")} class="py-2.5 px-3 rounded-2xl bg-rose-500/15 hover:bg-rose-500/25 text-rose-600 dark:text-rose-400 text-xs font-bold transition">- Despesa</button>
                  <button onClick=${() => openModalWithType("transfer")} class="py-2.5 px-3 rounded-2xl bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-600 dark:text-indigo-400 text-xs font-bold transition">⇄ Transferir</button>
                </div>

                <!-- MINI ACCOUNTS LIST -->
                <div class="grid grid-cols-3 gap-2 pt-3 border-t border-slate-100 dark:border-white/10">
                  ${cashAccounts.slice(0, 3).map((acc) => html`
                    <div key=${acc.id} class="p-2.5 rounded-xl bg-slate-50 dark:bg-obsidian-800/50">
                      <div class="flex items-center justify-between text-[11px] text-slate-400 mb-0.5">
                        <span class="truncate">${acc.name}</span>
                        <button onClick=${() => handleAdjustBalance(acc)} class="hover:text-emerald-400" title="Ajustar">✏️</button>
                      </div>
                      <div class="text-xs font-bold tabular-nums truncate">${showMoney(acc.balance_cents)}</div>
                    </div>
                  `)}
                </div>
              </div>

              <!-- VIRTUAL CREDIT CARD CAROUSEL (4 COLS) — BLACK METAL & GOLD / ROYAL BLUE -->
              <div class="lg:col-span-4 p-6 rounded-3xl bg-gradient-to-br from-royal-600 via-royal-700 to-blue-900 dark:from-[#17171c] dark:via-[#1d1910] dark:to-[#09090b] text-white shadow-xl border border-blue-400/20 dark:border-gold-500/35 card-interactive flex flex-col justify-between relative overflow-hidden">
                <div class="absolute -right-10 -top-10 w-40 h-40 rounded-full bg-white/10 dark:bg-gold-500/15 blur-2xl"></div>
                <div class="flex items-center justify-between z-10">
                  <div class="flex items-center gap-2">
                    <div class="w-9 h-6 rounded-md bg-gradient-to-br from-amber-200 via-gold-400 to-amber-500 opacity-95 shadow-sm"></div>
                    <span class="text-xs font-semibold tracking-wider uppercase opacity-95 dark:text-gold-300">
                      ${creditAccount?.name || "Cartão de Crédito"}
                    </span>
                  </div>
                  <div class="flex items-center gap-1.5">
                    ${creditAccounts.length > 1 && html`
                      <button onClick=${() => setActiveCardIdx((i) => (i - 1 + creditAccounts.length) % creditAccounts.length)} class="px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 text-xs">◀</button>
                      <button onClick=${() => setActiveCardIdx((i) => (i + 1) % creditAccounts.length)} class="px-2 py-0.5 rounded bg-white/10 hover:bg-white/20 text-xs">▶</button>
                    `}
                    <button onClick=${() => setTab("bills")} class="text-[11px] opacity-85 hover:opacity-100 underline ml-1">Gerenciar</button>
                  </div>
                </div>

                <div class="my-5 z-10">
                  <div class="flex items-center justify-between text-xs text-blue-100 dark:text-gold-300/80 mb-1">
                    <span>Fatura Atual</span>
                    <span>${creditAccount?.due_day ? `Vence dia ${creditAccount.due_day}` : ""}</span>
                  </div>
                  <div class="text-3xl font-extrabold tabular-nums">${showMoney(creditUsed)}</div>
                </div>

                <div class="z-10 space-y-2">
                  <div class="flex justify-between text-xs text-blue-100 dark:text-slate-300">
                    <span>Parcelas futuras acumuladas</span>
                    <span class="font-bold text-white dark:text-gold-300 tabular-nums">${showMoney(creditAccount?.future_installments_cents || 0)}</span>
                  </div>
                  <div class="w-full h-1.5 rounded-full bg-white/15 overflow-hidden">
                    <div
                      class="h-full bg-gradient-to-r from-sky-300 to-white dark:from-gold-400 dark:to-amber-200 rounded-full transition-all duration-500"
                      style=${{ width: `${Math.min(100, Math.round((creditUsed / Math.max(1, creditUsed + (creditAccount?.future_installments_cents || 0))) * 100))}%` }}
                    ></div>
                  </div>
                </div>
              </div>

              <!-- KPI STACK (3 COLS) -->
              <div class="lg:col-span-3 flex flex-col gap-3.5 justify-between">
                <div class="p-4 rounded-2xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm card-interactive flex-1 flex flex-col justify-center">
                  <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                    <span>Entradas</span>
                    ${html`<${DeltaPill} pct=${summary?.income_change_pct} />`}
                  </div>
                  <div class="text-xl font-extrabold text-emerald-500 tabular-nums">${showMoney(incomeCents)}</div>
                </div>

                <div class="p-4 rounded-2xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm card-interactive flex-1 flex flex-col justify-center">
                  <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                    <span>Saídas</span>
                    ${html`<${DeltaPill} pct=${summary?.expense_change_pct} invertColors=${true} />`}
                  </div>
                  <div class="text-xl font-extrabold text-rose-500 tabular-nums">${showMoney(expenseCents)}</div>
                </div>

                <div class="p-4 rounded-2xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm card-interactive flex-1 flex flex-col justify-center">
                  <div class="flex items-center justify-between text-xs text-slate-400 mb-1">
                    <span>Taxa de Economia</span>
                    <span class="text-[11px] font-semibold text-indigo-400">${summary?.count || 0} lanç.</span>
                  </div>
                  <div class="text-xl font-extrabold tabular-nums">${summary?.savings_rate_pct || 0}%</div>
                </div>
              </div>
            </div>

            <!-- BENTO ROW 2: CHARTS -->
            <div class="grid grid-cols-1 lg:grid-cols-12 gap-5">
              <div class="lg:col-span-8 p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
                <h2 class="font-bold text-base mb-1">Fluxo de Caixa Diário</h2>
                <p class="text-xs text-slate-400 mb-2">Entradas, saídas e saldo acumulado dia a dia</p>
                ${dailyOption && html`<${EChartBox} option=${dailyOption} isDark=${isDark} />`}
              </div>

              <div class="lg:col-span-4 p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm flex flex-col">
                <div class="flex items-center justify-between mb-3">
                  <div>
                    <h2 class="font-bold text-base">Custos por Categoria</h2>
                    <p class="text-[11px] text-slate-400">Clique para filtrar movimentações</p>
                  </div>
                  ${selectedCatFilter && html`
                    <button onClick=${() => setSelectedCatFilter(null)} class="text-[11px] text-royal-600 dark:text-gold-400 font-semibold underline">Limpar</button>
                  `}
                </div>
                ${catBreakdown.length ? html`
                  <div class="space-y-3 overflow-y-auto max-h-[300px] pr-1">
                    ${(() => {
                      const sorted = [...catBreakdown].sort((a, b) => b.total_cents - a.total_cents);
                      const maxVal = sorted[0]?.total_cents || 1;
                      return sorted.map((c) => {
                        const barPct = Math.max(4, Math.round((c.total_cents / maxVal) * 100));
                        const isSelected = selectedCatFilter === c.category_id;
                        return html`
                          <button
                            key=${c.category_id}
                            onClick=${() => setSelectedCatFilter((prev) => (prev === c.category_id ? null : c.category_id))}
                            class=${`w-full text-left p-2.5 rounded-2xl transition-all border ${
                              isSelected
                                ? "bg-royal-500/10 border-royal-500/40 dark:bg-gold-500/15 dark:border-gold-500/40"
                                : "border-transparent hover:bg-slate-50 dark:hover:bg-white/5"
                            }`}
                          >
                            <div class="flex items-center justify-between text-xs mb-1.5 gap-2">
                              <span class="font-semibold truncate">${c.icon} ${c.name}</span>
                              <span class="font-bold tabular-nums shrink-0">
                                ${showMoney(c.total_cents)}
                                <span class="text-slate-400 font-normal ml-1">(${c.share_pct}%)</span>
                              </span>
                            </div>
                            <div class="w-full h-2.5 rounded-full bg-slate-100 dark:bg-white/10 overflow-hidden">
                              <div
                                class="h-full rounded-full transition-all duration-500"
                                style=${{ width: `${barPct}%`, backgroundColor: c.color }}
                              ></div>
                            </div>
                          </button>
                        `;
                      });
                    })()}
                  </div>
                ` : html`<div class="flex-1 flex items-center justify-center text-sm text-slate-400">Sem despesas no período</div>`}
              </div>
            </div>

            <!-- BENTO ROW 3: RECENT TRANSACTIONS -->
            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <div class="flex items-center justify-between mb-4">
                <h2 class="font-bold text-base">
                  ${selectedCatFilter ? "Movimentações da Categoria Selecionada" : "Últimas Movimentações"}
                </h2>
                <button onClick=${() => setTab("ledger")} class="text-xs font-semibold text-emerald-500 hover:underline">Abrir extrato completo →</button>
              </div>
              <div class="divide-y divide-slate-100 dark:divide-white/5">
                ${transactions
                  .filter((tx) => !selectedCatFilter || tx.category_id === selectedCatFilter)
                  .slice(0, 6)
                  .map((tx) => html`
                    <div key=${tx.id} class="py-3 flex items-center justify-between gap-3">
                      <div class="flex items-center gap-3 min-w-0">
                        <div class="w-10 h-10 rounded-2xl bg-slate-100 dark:bg-obsidian-800 flex items-center justify-center text-lg shrink-0">${tx.category_icon}</div>
                        <div class="min-w-0">
                          <div class="font-semibold text-sm truncate">${tx.description}</div>
                          <div class="text-xs text-slate-400">${tx.category_name} · ${tx.account_name} · ${new Date(tx.occurred_at).toLocaleDateString("pt-BR")}</div>
                        </div>
                      </div>
                      <div class=${`font-bold text-sm tabular-nums shrink-0 ${
                        tx.type === "income" ? "text-emerald-500" : tx.type === "transfer" ? "text-indigo-400" : "text-rose-500"
                      }`}>
                        ${tx.type === "income" ? "+" : tx.type === "transfer" ? "⇄ " : "-"}${showMoney(tx.amount_cents)}
                      </div>
                    </div>
                  `)}
              </div>
            </div>
          </div>
        `}

        <!-- TAB: FIXAS & CARTÕES -->
        ${tab === "bills" && html`
          <div class="space-y-6">
            <!-- CONTAS BANCÁRIAS & CARTEIRAS -->
            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                <h2 class="font-bold text-base">🏦 Contas Bancárias & Carteiras</h2>
                <form
                  onSubmit=${async (e) => {
                    e.preventDefault();
                    const initCents = accountForm.initial_balance
                      ? Math.round(parseFloat(accountForm.initial_balance) * 100)
                      : 0;
                    await apiFetch("/api/finance/accounts", {
                      method: "POST",
                      body: JSON.stringify({
                        name: accountForm.name,
                        type: accountForm.type,
                        initial_balance_cents: initCents,
                      }),
                    });
                    setAccountForm({ name: "", type: "checking", initial_balance: "" });
                    showToast("🏦 Conta criada!");
                    await loadAll();
                  }}
                  class="flex flex-wrap items-center gap-2"
                >
                  <input required value=${accountForm.name} onInput=${(e) => setAccountForm((p) => ({ ...p, name: e.target.value }))} placeholder="Nome (ex: Bradesco)" class="px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs outline-none" />
                  <select value=${accountForm.type} onChange=${(e) => setAccountForm((p) => ({ ...p, type: e.target.value }))} class="px-2.5 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs">
                    <option value="checking">Corrente</option>
                    <option value="savings">Poupança</option>
                    <option value="wallet">Carteira</option>
                  </select>
                  <input type="number" step="0.01" value=${accountForm.initial_balance} onInput=${(e) => setAccountForm((p) => ({ ...p, initial_balance: e.target.value }))} placeholder="Saldo inicial R$" class="w-28 px-2.5 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs outline-none" />
                  <button type="submit" class="px-3 py-1.5 rounded-xl bg-emerald-500 text-white text-xs font-semibold">+ Conta</button>
                </form>
              </div>
              <div class="grid grid-cols-1 sm:grid-cols-3 gap-3.5">
                ${cashAccounts.map((acc) => html`
                  <div key=${acc.id} class="p-4 rounded-2xl bg-slate-50 dark:bg-obsidian-800/50 border border-slate-200/70 dark:border-white/10">
                    <div class="flex justify-between items-center text-xs text-slate-400 mb-1">
                      <span class="font-semibold text-slate-700 dark:text-slate-200">🏦 ${acc.name}</span>
                      <button onClick=${() => handleAdjustBalance(acc)} class="hover:text-emerald-500">✏️</button>
                    </div>
                    <div class="text-xl font-extrabold tabular-nums">${fmtBRL(acc.balance_cents)}</div>
                  </div>
                `)}
              </div>
            </div>

            <!-- CARTÕES DE CRÉDITO -->
            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <div class="flex flex-wrap items-center justify-between gap-3 mb-4">
                <h2 class="font-bold text-base">💳 Meus Cartões de Crédito</h2>
                <form
                  onSubmit=${async (e) => {
                    e.preventDefault();
                    await apiFetch("/api/finance/accounts", {
                      method: "POST",
                      body: JSON.stringify({
                        name: cardForm.name,
                        type: "credit",
                        closing_day: Number(cardForm.closing_day),
                        due_day: Number(cardForm.due_day),
                      }),
                    });
                    setCardForm({ name: "", closing_day: 3, due_day: 10 });
                    showToast("💳 Cartão adicionado!");
                    await loadAll();
                  }}
                  class="flex flex-wrap items-center gap-2"
                >
                  <input required value=${cardForm.name} onInput=${(e) => setCardForm((p) => ({ ...p, name: e.target.value }))} placeholder="Nome (ex: Inter)" class="px-3 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs outline-none" />
                  <input type="number" min="1" max="31" value=${cardForm.closing_day} onInput=${(e) => setCardForm((p) => ({ ...p, closing_day: e.target.value }))} title="Dia fechamento" class="w-16 px-2 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs" />
                  <input type="number" min="1" max="31" value=${cardForm.due_day} onInput=${(e) => setCardForm((p) => ({ ...p, due_day: e.target.value }))} title="Dia vencimento" class="w-16 px-2 py-1.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs" />
                  <button type="submit" class="px-3 py-1.5 rounded-xl bg-indigo-500 text-white text-xs font-semibold">+ Cartão</button>
                </form>
              </div>
              <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                ${creditAccounts.map((acc) => {
                  const used = Math.max(0, acc.expenses_cents - acc.incomes_cents - acc.initial_balance_cents);
                  return html`
                    <div key=${acc.id} class="p-4 rounded-2xl bg-gradient-to-br from-slate-900 to-indigo-950 text-white border border-white/10">
                      <div class="flex justify-between text-xs opacity-80 mb-2">
                        <span class="font-bold">💳 ${acc.name}</span>
                        <span>${acc.due_day ? `Vence dia ${acc.due_day}` : "Sem venc."}</span>
                      </div>
                      <div class="text-2xl font-extrabold tabular-nums">${fmtBRL(used)}</div>
                      <div class="text-[11px] text-indigo-200 mt-1">Parcelas futuras: ${fmtBRL(acc.future_installments_cents)}</div>
                    </div>
                  `;
                })}
              </div>
            </div>

            <!-- CONTAS FIXAS E ANUAIS (ÁGUA, LUZ, INTERNET, ALUGUEL, FINANCIAMENTO, IPVA) -->
            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <h2 class="font-bold text-base mb-3">📄 Contas Fixas & Despesas Anuais (Água, Luz, Internet, Aluguel, Veículo)</h2>
              <form
                onSubmit=${async (e) => {
                  e.preventDefault();
                  await apiFetch("/api/finance/bills", {
                    method: "POST",
                    body: JSON.stringify({
                      name: billForm.name,
                      amount_cents: Math.round(parseFloat(billForm.amount) * 100),
                      due_day: Number(billForm.due_day),
                      recurrence: billForm.recurrence,
                      due_month: billForm.recurrence === "yearly" ? Number(billForm.due_month) : null,
                      category_id: billForm.category_id,
                      account_id: billForm.account_id,
                    }),
                  });
                  setBillForm((p) => ({ ...p, name: "", amount: "" }));
                  showToast("📄 Conta fixa cadastrada!");
                  await loadAll();
                }}
                class="grid grid-cols-2 md:grid-cols-6 gap-2.5 mb-5 p-3.5 rounded-2xl bg-slate-50 dark:bg-obsidian-800/40"
              >
                <input required value=${billForm.name} onInput=${(e) => setBillForm((p) => ({ ...p, name: e.target.value }))} placeholder="Ex: Água, Luz, IPVA..." class="col-span-2 px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs outline-none" />
                <input required type="number" step="0.01" min="0.01" value=${billForm.amount} onInput=${(e) => setBillForm((p) => ({ ...p, amount: e.target.value }))} placeholder="Valor R$" class="px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs outline-none" />
                <input required type="number" min="1" max="31" value=${billForm.due_day} onInput=${(e) => setBillForm((p) => ({ ...p, due_day: e.target.value }))} placeholder="Dia venc." class="px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs outline-none" />
                <select value=${billForm.recurrence} onChange=${(e) => setBillForm((p) => ({ ...p, recurrence: e.target.value }))} class="px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs">
                  <option value="monthly">Mensal</option>
                  <option value="yearly">Anual (IPVA/Lic.)</option>
                </select>
                <button type="submit" class="px-3 py-2 rounded-xl bg-emerald-500 text-white text-xs font-bold">+ Cadastrar</button>
                <select value=${billForm.category_id} onChange=${(e) => setBillForm((p) => ({ ...p, category_id: e.target.value }))} class="col-span-2 md:col-span-3 px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs">
                  ${categories.filter((c) => c.type === "expense").map((c) => html`<option key=${c.id} value=${c.id}>${c.icon} ${c.name}</option>`)}
                </select>
                <select value=${billForm.account_id} onChange=${(e) => setBillForm((p) => ({ ...p, account_id: e.target.value }))} class="col-span-2 md:col-span-3 px-3 py-2 rounded-xl bg-white dark:bg-obsidian-800 text-xs">
                  ${accounts.map((a) => html`<option key=${a.id} value=${a.id}>Pagar via: ${a.name}</option>`)}
                </select>
              </form>

              <div class="divide-y divide-slate-100 dark:divide-white/5">
                ${bills.length ? bills.map((b) => {
                  const statusBadge =
                    b.status === "paid"
                      ? html`<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/15 text-emerald-500">✅ Pago</span>`
                      : b.status === "overdue"
                      ? html`<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-500/15 text-rose-500">🔴 Atrasado</span>`
                      : b.status === "due_soon"
                      ? html`<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-500">⚠️ Vence em ${b.days_until_due}d</span>`
                      : html`<span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-slate-200 dark:bg-white/10 text-slate-500">⏳ Dia ${b.due_day}</span>`;
                  return html`
                    <div key=${b.id} class="py-3 flex flex-wrap items-center justify-between gap-3">
                      <div class="flex items-center gap-3">
                        <div class="w-10 h-10 rounded-2xl bg-slate-100 dark:bg-obsidian-800 flex items-center justify-center text-lg">${b.category_icon}</div>
                        <div>
                          <div class="font-semibold text-sm">${b.name}</div>
                          <div class="text-xs text-slate-400">${b.recurrence === "yearly" ? "Anual" : "Mensal"} · Venc. dia ${b.due_day} · ${b.account_name}</div>
                        </div>
                      </div>
                      <div class="flex items-center gap-2.5">
                        ${statusBadge}
                        <strong class="text-sm tabular-nums">${fmtBRL(b.amount_cents)}</strong>
                        ${b.status !== "paid" && html`
                          <button
                            onClick=${async () => { await apiFetch(`/api/finance/bills/${b.id}/pay`, { method: "POST" }); showToast(`✅ ${b.name} pago!`); await loadAll(); }}
                            class="px-3 py-1.5 rounded-xl bg-emerald-500 text-white text-xs font-semibold"
                          >
                            Pagar
                          </button>
                        `}
                        <button onClick=${async () => { await apiFetch(`/api/finance/bills/${b.id}`, { method: "DELETE" }); await loadAll(); }} class="p-1.5 text-slate-400 hover:text-rose-500">🗑️</button>
                      </div>
                    </div>
                  `;
                }) : html`<p class="text-sm text-slate-400">Nenhuma conta fixa cadastrada ainda.</p>`}
              </div>
            </div>
          </div>
        `}

        <!-- TAB 2: ANÁLISES & COMPARATIVOS -->
        ${tab === "compare" && html`
          <div class="space-y-5">
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
                <h2 class="font-bold text-base mb-2">Comparativo Mensal (6 Meses)</h2>
                ${html`<${EChartBox} option=${monthlyOption} isDark=${isDark} />`}
              </div>
              <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
                <h2 class="font-bold text-base mb-2">Gasto Acumulado: Mês Atual vs Anterior</h2>
                ${dayCurveOption && html`<${EChartBox} option=${dayCurveOption} isDark=${isDark} />`}
              </div>
            </div>

            <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
              <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
                <h2 class="font-bold text-base mb-2">Gastos por Dia da Semana</h2>
                ${html`<${EChartBox} option=${weekdayOption} isDark=${isDark} />`}
              </div>
              <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
                <h2 class="font-bold text-base mb-3">Benchmark Pessoal (vs Média 3 Meses)</h2>
                <div class="space-y-2.5 max-h-72 overflow-y-auto pr-1">
                  ${catBreakdown.map((c) => html`
                    <div key=${c.category_id} class="p-3 rounded-2xl bg-slate-50 dark:bg-obsidian-800/50 flex items-center justify-between">
                      <div class="flex items-center gap-2.5">
                        <span>${c.icon}</span>
                        <div>
                          <div class="text-sm font-semibold">${c.name}</div>
                          <div class="text-xs text-slate-400">Média 3m: ${fmtBRL(c.avg_3m_cents)}</div>
                        </div>
                      </div>
                      <div class="text-right">
                        <div class="text-sm font-bold tabular-nums">${fmtBRL(c.total_cents)}</div>
                        ${html`<${DeltaPill} pct=${c.deviation_vs_avg_pct} invertColors=${true} />`}
                      </div>
                    </div>
                  `)}
                </div>
              </div>
            </div>

            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <h2 class="font-bold text-base mb-3">💳 Parcelamentos Acumulados no Cartão</h2>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                ${installments.length ? installments.map((inst) => {
                  const paid = inst.total_installments - inst.remaining_installments;
                  const pct = Math.round((paid / inst.total_installments) * 100);
                  return html`
                    <div key=${inst.installment_group_id} class="p-4 rounded-2xl bg-slate-50 dark:bg-obsidian-800/60 border border-slate-200/60 dark:border-white/10">
                      <div class="flex justify-between items-start mb-2">
                        <div>
                          <div class="font-semibold text-sm">${inst.category_icon} ${inst.description}</div>
                          <div class="text-xs text-slate-400">${inst.account_name} · ${inst.total_installments}x de ${fmtBRL(inst.installment_amount_cents)}</div>
                        </div>
                        <div class="text-sm font-bold tabular-nums">${fmtBRL(inst.remaining_cents)}</div>
                      </div>
                      <div class="w-full h-2 rounded-full bg-slate-200 dark:bg-obsidian-950 overflow-hidden">
                        <div class="h-full bg-indigo-500 rounded-full" style=${{ width: `${pct}%` }}></div>
                      </div>
                      <div class="text-[11px] text-slate-400 mt-1.5">Restam ${inst.remaining_installments} de ${inst.total_installments} parcelas</div>
                    </div>
                  `;
                }) : html`<p class="text-sm text-slate-400">Nenhum parcelamento ativo.</p>`}
              </div>
            </div>
          </div>
        `}

        <!-- TAB 3: EXTRATO -->
        ${tab === "ledger" && html`
          <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
            <div class="flex flex-wrap gap-2.5 mb-4">
              <input
                value=${search}
                onInput=${(e) => setSearch(e.target.value)}
                placeholder="Buscar descrição..."
                class="flex-1 min-w-[180px] px-3.5 py-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm outline-none"
              />
              <select value=${filterType} onChange=${(e) => setFilterType(e.target.value)} class="px-3 py-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm">
                <option value="">Todos os tipos</option>
                <option value="expense">Gastos</option>
                <option value="income">Ganhos</option>
                <option value="transfer">Transferências</option>
              </select>
              <select value=${filterCat} onChange=${(e) => setFilterCat(e.target.value)} class="px-3 py-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm">
                <option value="">Todas categorias</option>
                ${categories.map((c) => html`<option key=${c.id} value=${c.id}>${c.icon} ${c.name}</option>`)}
              </select>
              <button onClick=${exportCSV} class="px-3.5 py-2 rounded-xl bg-slate-200 dark:bg-obsidian-800 text-xs font-semibold hover:opacity-80">⬇ CSV</button>
            </div>

            <div class="divide-y divide-slate-100 dark:divide-white/5">
              ${filteredTransactions.map((tx) => html`
                <div key=${tx.id} class="py-3 flex items-center justify-between gap-3">
                  <div class="flex items-center gap-3 min-w-0">
                    <div class="w-10 h-10 rounded-2xl bg-slate-100 dark:bg-obsidian-800 flex items-center justify-center text-lg shrink-0">${tx.category_icon}</div>
                    <div class="min-w-0">
                      <div class="font-semibold text-sm truncate">${tx.description}</div>
                      <div class="text-xs text-slate-400">${tx.category_name} · ${tx.account_name} · ${new Date(tx.occurred_at).toLocaleDateString("pt-BR")}</div>
                    </div>
                  </div>
                  <div class="flex items-center gap-3 shrink-0">
                    <span class=${`font-bold text-sm tabular-nums ${
                      tx.type === "income" ? "text-emerald-500" : tx.type === "transfer" ? "text-indigo-400" : "text-rose-500"
                    }`}>
                      ${tx.type === "income" ? "+" : tx.type === "transfer" ? "⇄ " : "-"}${fmtBRL(tx.amount_cents)}
                    </span>
                    <button onClick=${() => handleDeleteTx(tx.id)} class="p-1.5 rounded-lg hover:bg-rose-500/15 text-slate-400 hover:text-rose-500 transition">🗑️</button>
                  </div>
                </div>
              `)}
            </div>
          </div>
        `}

        <!-- TAB 4: COFRE & SYNC -->
        ${tab === "settings" && html`
          <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <h2 class="font-bold text-base mb-2">Backup Criptografado no Telegram</h2>
              <p class="text-sm text-slate-400 mb-4">
                ${syncStatus?.channel_configured
                  ? `Último snapshot: ${syncStatus.last_synced_at ? new Date(syncStatus.last_synced_at).toLocaleString("pt-BR") : "Ainda não enviado"} (Msg #${syncStatus.pinned_msg_id || "-"})`
                  : "Canal Privado não configurado no .env."}
              </p>
              <button
                onClick=${async () => { await apiFetch("/api/finance/sync-now", { method: "POST" }); showToast("🔐 Snapshot enviado ao canal!"); await loadAll(); }}
                class="px-4 py-2.5 rounded-xl bg-emerald-500 text-white text-sm font-semibold hover:bg-emerald-600 transition"
              >
                🔐 Forçar Backup Agora
              </button>
            </div>

            <div class="p-5 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200/80 dark:border-white/10 shadow-sm">
              <h2 class="font-bold text-base mb-2">Token de Acesso Remoto</h2>
              <p class="text-xs text-slate-400 mb-3">Caso tenha definido WEB_ACCESS_TOKEN no servidor:</p>
              <div class="flex gap-2">
                <input
                  type="password"
                  value=${accessToken}
                  onInput=${(e) => setAccessToken(e.target.value)}
                  placeholder="Token de acesso"
                  class="flex-1 px-3.5 py-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm outline-none"
                />
                <button
                  onClick=${() => { localStorage.setItem("tpa_access_token", accessToken.trim()); showToast("Token salvo."); loadAll(); }}
                  class="px-4 py-2 rounded-xl bg-slate-900 dark:bg-indigo-500 text-white text-sm font-semibold"
                >
                  Salvar
                </button>
              </div>
            </div>
          </div>
        `}
      </main>

      <!-- BOTTOM NAV MOBILE (RESPONSIVO PARA SMARTPHONES) -->
      <nav class="md:hidden fixed bottom-0 left-0 right-0 bg-white/95 dark:bg-obsidian-900/95 backdrop-blur-xl border-t border-blue-100 dark:border-gold-500/20 flex justify-around py-2 pb-[calc(0.5rem+env(safe-area-inset-bottom))] z-40">
        ${navItems.map((item) => html`
          <button
            key=${item.id}
            onClick=${() => setTab(item.id)}
            class=${`flex flex-col items-center gap-0.5 text-[11px] font-medium px-2 py-1 rounded-xl ${
              tab === item.id ? "text-royal-600 dark:text-gold-400 font-bold" : "text-slate-400"
            }`}
          >
            <span class="text-lg">${item.icon}</span>
            <span>${item.label}</span>
          </button>
        `)}
      </nav>

      <!-- WIDGET CONVERSACIONAL -->
      <button
        onClick=${() => setChatOpen(!chatOpen)}
        class="fixed right-4 bottom-20 md:bottom-6 z-50 px-4 py-3 rounded-full bg-gradient-to-r from-royal-600 to-blue-700 dark:from-gold-400 dark:to-gold-600 text-white dark:text-obsidian-950 font-bold text-sm shadow-xl shadow-royal-500/30 dark:shadow-gold-500/25 flex items-center gap-2 hover:scale-105 transition"
      >
        <span>💬</span>
        <span>Assistente</span>
      </button>

      ${chatOpen && html`
        <div class="fixed right-3 sm:right-4 bottom-36 md:bottom-22 w-[360px] max-w-[calc(100vw-1.5rem)] h-[470px] rounded-3xl bg-white dark:bg-obsidian-900 border border-blue-100 dark:border-gold-500/25 shadow-2xl flex flex-col overflow-hidden z-50">
          <div class="px-4 py-3.5 bg-gradient-to-r from-royal-600 to-blue-700 dark:from-obsidian-800 dark:to-black text-white dark:text-gold-300 border-b border-white/10 dark:border-gold-500/20 flex items-center justify-between font-bold text-sm">
            <span>🤖 Assistente Financeiro</span>
            <button onClick=${() => setChatOpen(false)} class="opacity-80 hover:opacity-100">✕</button>
          </div>
          <div class="flex-1 overflow-y-auto p-3.5 space-y-2.5">
            ${chatMsgs.map((m, idx) => html`
              <div key=${idx} class=${`max-w-[85%] px-3.5 py-2.5 rounded-2xl text-xs leading-relaxed whitespace-pre-line ${
                m.who === "user"
                  ? "ml-auto bg-emerald-500 text-white rounded-br-sm"
                  : "bg-slate-100 dark:bg-obsidian-800 text-slate-800 dark:text-slate-100 rounded-bl-sm"
              }`}>
                ${m.text}
              </div>
            `)}
          </div>
          <div class="px-3 py-2 border-t border-slate-100 dark:border-white/10 flex gap-1.5 overflow-x-auto">
            ${["Qual meu saldo?", "Parcelas do cartão", "Quanto gastei esse mês?", "Quanto gastei hoje?"].map((q) => html`
              <button
                key=${q}
                onClick=${() => sendConversational(q, true)}
                class="px-2.5 py-1 rounded-full bg-slate-100 dark:bg-obsidian-800 text-[11px] whitespace-nowrap hover:bg-emerald-500/20"
              >
                ${q}
              </button>
            `)}
          </div>
          <form onSubmit=${(e) => { e.preventDefault(); sendConversational(chatInput, true); }} class="p-2.5 border-t border-slate-100 dark:border-white/10 flex gap-2">
            <input
              value=${chatInput}
              onInput=${(e) => setChatInput(e.target.value)}
              placeholder="Digite um gasto ou pergunta..."
              class="flex-1 px-3 py-2 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-xs outline-none"
            />
            <button type="submit" class="px-3.5 py-2 rounded-xl bg-emerald-500 text-white text-xs font-semibold">Enviar</button>
          </form>
        </div>
      `}

      <!-- MODAL NOVO LANÇAMENTO -->
      ${modalOpen && html`
        <div class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 z-50">
          <form onSubmit=${handleCreateTx} class="w-full max-w-md p-6 rounded-3xl bg-white dark:bg-obsidian-900 border border-slate-200 dark:border-white/10 shadow-2xl space-y-3.5">
            <h3 class="text-lg font-bold">Novo Lançamento</h3>
            <select
              value=${txForm.tx_type}
              onChange=${(e) => {
                const nt = e.target.value;
                const ct = nt === "transfer" ? "expense" : nt;
                const firstCat = categories.find((c) => c.type === ct)?.id || "";
                setTxForm((p) => ({ ...p, tx_type: nt, category_id: firstCat }));
              }}
              class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm"
            >
              <option value="expense">🔴 Despesa</option>
              <option value="income">🟢 Receita</option>
              <option value="transfer">🔁 Transferência</option>
            </select>
            <input
              type="number"
              step="0.01"
              min="0.01"
              required
              value=${txForm.amount}
              onInput=${(e) => setTxForm((p) => ({ ...p, amount: e.target.value }))}
              placeholder="Valor em R$ (ex: 45.90)"
              class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm outline-none"
            />
            <input
              required
              value=${txForm.description}
              onInput=${(e) => setTxForm((p) => ({ ...p, description: e.target.value }))}
              placeholder="Descrição"
              class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm outline-none"
            />
            <select
              value=${txForm.category_id}
              onChange=${(e) => setTxForm((p) => ({ ...p, category_id: e.target.value }))}
              class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm"
            >
              ${modalCategories.map((c) => html`<option key=${c.id} value=${c.id}>${c.icon} ${c.name}</option>`)}
            </select>
            <select
              value=${txForm.account_id}
              onChange=${(e) => setTxForm((p) => ({ ...p, account_id: e.target.value }))}
              class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm"
            >
              ${accounts.map((a) => html`<option key=${a.id} value=${a.id}>${a.name}</option>`)}
            </select>
            ${txForm.tx_type === "transfer" && html`
              <select
                value=${txForm.transfer_to_account_id}
                onChange=${(e) => setTxForm((p) => ({ ...p, transfer_to_account_id: e.target.value }))}
                class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm"
              >
                ${accounts.map((a) => html`<option key=${a.id} value=${a.id}>Destino: ${a.name}</option>`)}
              </select>
            `}
            ${txForm.tx_type === "expense" && html`
              <input
                type="number"
                min="1"
                max="48"
                value=${txForm.installments_total}
                onInput=${(e) => setTxForm((p) => ({ ...p, installments_total: e.target.value }))}
                placeholder="Parcelas (1 = à vista)"
                class="w-full px-3.5 py-2.5 rounded-xl bg-slate-100 dark:bg-obsidian-800 text-sm outline-none"
              />
            `}
            <div class="flex justify-end gap-2 pt-2">
              <button type="button" onClick=${() => setModalOpen(false)} class="px-4 py-2 rounded-xl bg-slate-200 dark:bg-obsidian-800 text-sm font-medium">Cancelar</button>
              <button type="submit" class="px-4 py-2 rounded-xl bg-emerald-500 text-white text-sm font-semibold">Salvar</button>
            </div>
          </form>
        </div>
      `}

      <!-- TOAST -->
      ${toast && html`
        <div class="fixed top-5 right-5 z-50 px-4 py-3 rounded-xl bg-slate-900 dark:bg-white text-white dark:text-slate-900 text-xs font-semibold shadow-xl">
          ${toast}
        </div>
      `}
    </div>
  `;
}

createRoot(document.getElementById("root")).render(html`<${App} />`);
