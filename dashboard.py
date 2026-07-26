"""
dashboard.py — ATOM Bot v2 Dashboard
Puerto 8080 — Optimizado para tablet Samsung Tab A9
"""
import http.server, json, os, threading, time
from datetime import datetime

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
ESTADO_FILE = os.path.join(BASE_DIR, "logs", "estado_atom.json")
TRADING_FILE= os.path.join(BASE_DIR, "logs", "estado_trading.json")
HIST_FILE   = os.path.join(BASE_DIR, "logs", "historial_trades.json")
PORT        = int(os.environ.get("DASHBOARD_PORT", "8080"))

def cargar_json(path, default):
    try:    return json.load(open(path))
    except: return default

def api_datos():
    estado   = cargar_json(ESTADO_FILE, {})
    trading  = cargar_json(TRADING_FILE, {})
    historial= cargar_json(HIST_FILE, [])

    precio_usd  = estado.get("precio_actual") or 0
    precio_ref  = estado.get("precio_ref") or precio_usd
    tc          = estado.get("tc") or 17.5
    saldos      = estado.get("saldos") or {}
    ts_upd      = estado.get("ultima_actualizacion","")

    disponible  = saldos.get("disponible", 0)
    staking     = saldos.get("staking", 0)
    rewards     = saldos.get("rewards", 0)
    unbonding   = saldos.get("unbonding", 0)
    total_atom  = disponible + staking + rewards + unbonding
    valor_mxn   = total_atom * precio_usd * tc
    cambio_ref  = ((precio_usd-precio_ref)/precio_ref*100) if precio_ref else 0

    APR       = 0.15
    mes_atom  = staking * APR / 12
    mes_mxn   = mes_atom * precio_usd * tc

    # Trading stats
    en_trade    = trading.get("en_trade", False)
    trade_act   = trading.get("trade_actual")
    balance     = trading.get("balance_mxn", 0)
    total_trades= trading.get("trades_total", 0)
    ganados     = trading.get("trades_ganados", 0)
    wr          = ganados/total_trades*100 if total_trades else 0

    # P&L trade activo
    pnl_actual = 0
    gmxn_actual = 0
    if en_trade and trade_act:
        pe   = trade_act.get("precio_entrada", 0)
        tipo = trade_act.get("tipo","long")
        cap_ef = trade_act.get("capital_efectivo_mxn", 80000)
        # precio actual desde estado
        p_actual = precio_usd  # ADA precio
        if pe > 0:
            if tipo in ("long","scalping"):
                pnl_actual = (p_actual-pe)/pe*100
            else:
                pnl_actual = (pe-p_actual)/pe*100
            gmxn_actual = cap_ef * pnl_actual / 100

    return {
        "atom": {
            "precio_usd": precio_usd,
            "precio_mxn": precio_usd * tc,
            "cambio_ref": cambio_ref,
            "tc": tc,
            "disponible": disponible,
            "staking": staking,
            "rewards": rewards,
            "unbonding": unbonding,
            "total": total_atom,
            "valor_mxn": valor_mxn,
            "mes_atom": mes_atom,
            "mes_mxn": mes_mxn,
            "ts": ts_upd[:19].replace("T"," ") if ts_upd else "--",
        },
        "trading": {
            "en_trade": en_trade,
            "trade_actual": trade_act,
            "balance": balance,
            "total_trades": total_trades,
            "ganados": ganados,
            "wr": wr,
            "pnl_actual": pnl_actual,
            "gmxn_actual": gmxn_actual,
        },
        "historial": historial[-8:],
    }

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ATOM Bot v2</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Space+Mono:wght@400;700&display=swap');

  :root {
    --bg:       #0a0e1a;
    --surface:  #111827;
    --card:     #1a2235;
    --border:   #1e2d45;
    --accent:   #3b82f6;
    --accent2:  #8b5cf6;
    --green:    #10b981;
    --red:      #ef4444;
    --yellow:   #f59e0b;
    --text:     #e2e8f0;
    --muted:    #64748b;
    --atom:     #4f9cf9;
  }

  * { margin:0; padding:0; box-sizing:border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    min-height: 100vh;
    padding: 12px;
  }

  /* Header */
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    margin-bottom: 14px;
  }
  .header-left { display: flex; align-items: center; gap: 12px; }
  .logo {
    width: 44px; height: 44px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    font-size: 22px;
  }
  .title { font-size: 20px; font-weight: 700; }
  .subtitle { font-size: 13px; color: var(--muted); }
  .status-dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--green);
    box-shadow: 0 0 8px var(--green);
    animation: pulse 2s infinite;
  }
  @keyframes pulse {
    0%,100% { opacity:1; } 50% { opacity:0.4; }
  }
  .ts { font-size: 12px; color: var(--muted); font-family: 'Space Mono', monospace; }

  /* Grid principal */
  .grid-main {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 12px;
  }
  .grid-3 {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 12px;
    margin-bottom: 12px;
  }

  /* Cards */
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 18px;
  }
  .card-header {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 14px;
  }
  .card-icon { font-size: 20px; }
  .card-title { font-size: 14px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }

  /* Precio ATOM grande */
  .precio-big {
    font-size: 42px; font-weight: 700;
    font-family: 'Space Mono', monospace;
    color: var(--atom);
    line-height: 1;
  }
  .precio-sub { font-size: 18px; color: var(--muted); margin-top: 4px; }
  .cambio {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 16px; font-weight: 600;
    padding: 4px 10px; border-radius: 8px; margin-top: 8px;
  }
  .cambio.pos { background: rgba(16,185,129,0.15); color: var(--green); }
  .cambio.neg { background: rgba(239,68,68,0.15); color: var(--red); }
  .cambio.neu { background: rgba(100,116,139,0.15); color: var(--muted); }

  /* Filas de datos */
  .data-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 15px;
  }
  .data-row:last-child { border-bottom: none; }
  .data-label { color: var(--muted); }
  .data-value { font-weight: 600; font-family: 'Space Mono', monospace; }
  .data-value.green { color: var(--green); }
  .data-value.atom  { color: var(--atom); }
  .data-value.yellow{ color: var(--yellow); }

  /* Stat cards */
  .stat-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 16px;
    text-align: center;
  }
  .stat-icon { font-size: 28px; margin-bottom: 8px; }
  .stat-value {
    font-size: 28px; font-weight: 700;
    font-family: 'Space Mono', monospace;
  }
  .stat-label { font-size: 12px; color: var(--muted); margin-top: 4px; }

  /* Trading card */
  .trading-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 12px;
  }
  .mode-badge {
    display: inline-flex; align-items: center; gap: 8px;
    padding: 8px 16px; border-radius: 10px;
    font-size: 15px; font-weight: 600;
    margin-bottom: 14px;
  }
  .mode-vigilancia { background: rgba(59,130,246,0.15); color: var(--accent); border: 1px solid rgba(59,130,246,0.3); }
  .mode-ninja-long { background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }
  .mode-ninja-short { background: rgba(239,68,68,0.15); color: var(--red); border: 1px solid rgba(239,68,68,0.3); }
  .mode-ninja-scalping { background: rgba(139,92,246,0.15); color: var(--accent2); border: 1px solid rgba(139,92,246,0.3); }

  .pnl-big {
    font-size: 36px; font-weight: 700;
    font-family: 'Space Mono', monospace;
    text-align: center; padding: 16px 0;
  }
  .pnl-big.pos { color: var(--green); }
  .pnl-big.neg { color: var(--red); }
  .pnl-big.neu { color: var(--muted); }

  /* Capital bars */
  .cap-bars { display: flex; flex-direction: column; gap: 8px; }
  .cap-bar { display: flex; align-items: center; gap: 10px; }
  .cap-label { font-size: 13px; color: var(--muted); width: 80px; }
  .cap-track { flex:1; height: 8px; background: var(--border); border-radius: 4px; }
  .cap-fill { height: 8px; border-radius: 4px; }
  .cap-amount { font-size: 13px; font-family: 'Space Mono', monospace; width: 90px; text-align: right; }

  /* Historial */
  .hist-item {
    display: flex; align-items: center; gap: 10px;
    padding: 10px 0; border-bottom: 1px solid var(--border);
    font-size: 14px;
  }
  .hist-item:last-child { border-bottom: none; }
  .hist-emoji { font-size: 18px; width: 24px; text-align: center; }
  .hist-tipo {
    font-size: 11px; font-weight: 700; padding: 2px 6px;
    border-radius: 4px; width: 60px; text-align: center;
  }
  .hist-long    { background: rgba(16,185,129,0.2); color: var(--green); }
  .hist-short   { background: rgba(239,68,68,0.2); color: var(--red); }
  .hist-scalping{ background: rgba(139,92,246,0.2); color: var(--accent2); }
  .hist-fecha { color: var(--muted); font-size: 12px; flex:1; }
  .hist-pnl { font-family: 'Space Mono', monospace; font-weight: 700; }
  .hist-mxn { font-family: 'Space Mono', monospace; font-size: 13px; color: var(--muted); }

  /* Indicadores */
  .indicadores-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .ind-item {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 12px;
  }
  .ind-name { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .ind-value { font-size: 22px; font-weight: 700; font-family: 'Space Mono', monospace; margin-top: 4px; }
  .ind-ctx { font-size: 11px; margin-top: 2px; }

  /* Progress bar RSI */
  .rsi-track { height: 6px; background: var(--border); border-radius: 3px; margin-top: 6px; position: relative; }
  .rsi-fill { height: 6px; border-radius: 3px; transition: width 0.5s; }
  .rsi-markers { display: flex; justify-content: space-between; font-size: 9px; color: var(--muted); margin-top: 2px; }

  /* FNG bar */
  .fng-bar { height: 8px; border-radius: 4px; margin-top: 6px;
    background: linear-gradient(to right, #ef4444, #f59e0b, #10b981, #f59e0b, #ef4444); position: relative; }
  .fng-pointer { position: absolute; top: -4px; width: 4px; height: 16px; background: white; border-radius: 2px; transform: translateX(-50%); }

  /* Full width */
  .full { grid-column: 1 / -1; }

  /* Refresh */
  .refresh-bar {
    display: flex; align-items: center; justify-content: center;
    gap: 8px; padding: 10px;
    font-size: 12px; color: var(--muted);
  }
  .spin { animation: spin 2s linear infinite; display: inline-block; }
  @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }

  @media (max-width: 600px) {
    .grid-main { grid-template-columns: 1fr; }
    .grid-3 { grid-template-columns: 1fr 1fr; }
    .precio-big { font-size: 32px; }
  }
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="logo">🌌</div>
    <div>
      <div class="title">ATOM Bot v2</div>
      <div class="subtitle">Trading Monitor</div>
    </div>
  </div>
  <div style="text-align:right">
    <div class="status-dot" style="margin-left:auto;margin-bottom:4px"></div>
    <div class="ts" id="ts">--</div>
  </div>
</div>

<!-- ATOM precio + cartera -->
<div class="grid-main" style="margin-bottom:12px">
  <div class="card">
    <div class="card-header">
      <span class="card-icon">⚛️</span>
      <span class="card-title">Precio ATOM</span>
    </div>
    <div class="precio-big" id="precio-usd">$-.----</div>
    <div class="precio-sub" id="precio-mxn">$--.-- MXN</div>
    <div class="cambio neu" id="cambio-ref">±0.00%</div>
    <div style="margin-top:16px; border-top:1px solid var(--border); padding-top:14px;">
      <div class="data-row">
        <span class="data-label">TC USD/MXN</span>
        <span class="data-value atom" id="tc">$--.--</span>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <span class="card-icon">💼</span>
      <span class="card-title">Cartera ATOM</span>
    </div>
    <div class="data-row">
      <span class="data-label">🔓 Libre</span>
      <span class="data-value atom" id="disponible">-.---- ATOM</span>
    </div>
    <div class="data-row">
      <span class="data-label">🔒 Staking</span>
      <span class="data-value atom" id="staking">-.-- ATOM</span>
    </div>
    <div class="data-row">
      <span class="data-label">🎁 Rewards</span>
      <span class="data-value green" id="rewards">-.---- ATOM</span>
    </div>
    <div class="data-row">
      <span class="data-label">📊 Total</span>
      <span class="data-value atom" id="total-atom">-.-- ATOM</span>
    </div>
    <div class="data-row">
      <span class="data-label">💰 Valor</span>
      <span class="data-value green" id="valor-mxn">$-,--- MXN</span>
    </div>
  </div>
</div>

<!-- Stats ATOM -->
<div class="grid-3" style="margin-bottom:12px">
  <div class="stat-card">
    <div class="stat-icon">📅</div>
    <div class="stat-value green" id="dia-mxn">$-.--</div>
    <div class="stat-label">MXN / día (15% APR)</div>
  </div>
  <div class="stat-card">
    <div class="stat-icon">📆</div>
    <div class="stat-value green" id="mes-mxn">$---.--</div>
    <div class="stat-label">MXN / mes</div>
  </div>
  <div class="stat-card">
    <div class="stat-icon">🏛️</div>
    <div class="stat-value atom" style="font-size:18px">Everstake</div>
    <div class="stat-label">Validador activo</div>
  </div>
</div>

<!-- TRADING -->
<div class="trading-card">
  <div class="card-header">
    <span class="card-icon">🤖</span>
    <span class="card-title">Sistema de Trading</span>
  </div>

  <div id="mode-badge" class="mode-badge mode-vigilancia">
    🔍 MODO VIGILANCIA
  </div>

  <div class="grid-main" style="margin-bottom:14px">
    <!-- P&L activo -->
    <div style="text-align:center; background:var(--surface); border-radius:12px; padding:16px;">
      <div style="font-size:13px; color:var(--muted); margin-bottom:8px;">P&L TRADE ACTIVO</div>
      <div class="pnl-big neu" id="pnl-pct">--.--%</div>
      <div style="font-size:18px; font-family:'Space Mono',monospace; color:var(--muted)" id="pnl-mxn">$0 MXN</div>
    </div>
    <!-- Balance acumulado -->
    <div style="text-align:center; background:var(--surface); border-radius:12px; padding:16px;">
      <div style="font-size:13px; color:var(--muted); margin-bottom:8px;">P&L ACUMULADO</div>
      <div class="pnl-big neu" id="balance">$0</div>
      <div style="font-size:14px; color:var(--muted)" id="wr-total">WR: 0% | 0 trades</div>
    </div>
  </div>

  <!-- Capital bars -->
  <div style="margin-bottom:14px">
    <div style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:0.05em;">Capital Efectivo</div>
    <div class="cap-bars">
      <div class="cap-bar">
        <span class="cap-label">📈 LONG</span>
        <div class="cap-track"><div class="cap-fill" style="width:80%; background:var(--green)"></div></div>
        <span class="cap-amount green">$80,000</span>
      </div>
      <div class="cap-bar">
        <span class="cap-label">📉 SHORT</span>
        <div class="cap-track"><div class="cap-fill" style="width:80%; background:var(--red)"></div></div>
        <span class="cap-amount" style="color:var(--red)">$80,000</span>
      </div>
      <div class="cap-bar">
        <span class="cap-label">⚡ SCALP</span>
        <div class="cap-track"><div class="cap-fill" style="width:40%; background:var(--accent2)"></div></div>
        <span class="cap-amount" style="color:var(--accent2)">$40,000</span>
      </div>
    </div>
  </div>

  <!-- Indicadores de mercado ADA -->
  <div style="font-size:12px; color:var(--muted); margin-bottom:8px; text-transform:uppercase; letter-spacing:0.05em;">Indicadores ADA/USDT</div>
  <div class="indicadores-grid">
    <div class="ind-item">
      <div class="ind-name">RSI (14)</div>
      <div class="ind-value" id="rsi-val">--.-</div>
      <div class="rsi-track">
        <div class="rsi-fill" id="rsi-fill" style="width:50%; background:var(--yellow)"></div>
      </div>
      <div class="rsi-markers"><span>0</span><span>30</span><span>50</span><span>72</span><span>100</span></div>
      <div class="ind-ctx" id="rsi-ctx" style="color:var(--muted)">--</div>
    </div>
    <div class="ind-item">
      <div class="ind-name">Fear & Greed</div>
      <div class="ind-value" id="fng-val">--</div>
      <div class="fng-bar"><div class="fng-pointer" id="fng-ptr" style="left:50%"></div></div>
      <div class="ind-ctx" id="fng-ctx" style="color:var(--muted); margin-top:10px">--</div>
    </div>
    <div class="ind-item">
      <div class="ind-name">ADA precio</div>
      <div class="ind-value atom" id="ada-precio">$-.----</div>
      <div class="ind-ctx" id="ada-mxn" style="color:var(--muted)">--</div>
    </div>
    <div class="ind-item">
      <div class="ind-name">Mercado</div>
      <div class="ind-value" id="mercado-val" style="font-size:18px">--</div>
      <div class="ind-ctx" id="supertrend-val" style="color:var(--muted)">ST: --</div>
    </div>
  </div>
</div>

<!-- Historial trades -->
<div class="card">
  <div class="card-header">
    <span class="card-icon">📋</span>
    <span class="card-title">Historial Trades</span>
  </div>
  <div id="historial-list">
    <div style="text-align:center; color:var(--muted); padding:20px; font-size:14px">
      Sin trades aún — el sistema está en paper trading
    </div>
  </div>
</div>

<div class="refresh-bar">
  <span class="spin">⟳</span> Actualizando cada 10 segundos
</div>

<script>
async function actualizar() {
  try {
    const r = await fetch('/api');
    const d = await r.json();
    const atom = d.atom;
    const trading = d.trading;
    const hist = d.historial;

    // Header timestamp
    document.getElementById('ts').textContent = atom.ts;

    // ATOM precio
    document.getElementById('precio-usd').textContent = `$${atom.precio_usd.toFixed(4)}`;
    document.getElementById('precio-mxn').textContent = `$${atom.precio_mxn.toFixed(2)} MXN`;
    document.getElementById('tc').textContent = `$${atom.tc.toFixed(2)}`;

    const cambioEl = document.getElementById('cambio-ref');
    const c = atom.cambio_ref;
    cambioEl.textContent = `${c>=0?'+':''}${c.toFixed(2)}% vs ref`;
    cambioEl.className = `cambio ${c>0.5?'pos':c<-0.5?'neg':'neu'}`;

    // Cartera
    document.getElementById('disponible').textContent = `${atom.disponible.toFixed(4)} ATOM`;
    document.getElementById('staking').textContent = `${atom.staking.toFixed(2)} ATOM`;
    document.getElementById('rewards').textContent = `${atom.rewards.toFixed(4)} ATOM`;
    document.getElementById('total-atom').textContent = `${atom.total.toFixed(4)} ATOM`;
    document.getElementById('valor-mxn').textContent = `$${atom.valor_mxn.toLocaleString('es-MX', {minimumFractionDigits:2, maximumFractionDigits:2})} MXN`;

    // Stats
    const diaMxn = atom.staking * 0.15 / 365 * atom.precio_usd * atom.tc;
    document.getElementById('dia-mxn').textContent = `$${diaMxn.toFixed(2)}`;
    document.getElementById('mes-mxn').textContent = `$${atom.mes_mxn.toFixed(2)}`;

    // Trading modo
    const badge = document.getElementById('mode-badge');
    if (trading.en_trade && trading.trade_actual) {
      const tipo = trading.trade_actual.tipo;
      const emojis = {long:'📈',short:'📉',scalping:'⚡'};
      badge.textContent = `${emojis[tipo]||'🥷'} MODO NINJA — ${tipo.toUpperCase()}`;
      badge.className = `mode-badge mode-ninja-${tipo}`;
    } else {
      badge.textContent = '🔍 MODO VIGILANCIA — buscando señales';
      badge.className = 'mode-badge mode-vigilancia';
    }

    // P&L activo
    const pnlPct = document.getElementById('pnl-pct');
    const pnlMxn = document.getElementById('pnl-mxn');
    const pnl = trading.pnl_actual;
    const gmxn = trading.gmxn_actual;
    pnlPct.textContent = `${pnl>=0?'+':''}${pnl.toFixed(2)}%`;
    pnlPct.className = `pnl-big ${pnl>0?'pos':pnl<0?'neg':'neu'}`;
    pnlMxn.textContent = `${gmxn>=0?'+':''}$${Math.round(gmxn).toLocaleString()} MXN`;
    pnlMxn.style.color = pnl>0?'var(--green)':pnl<0?'var(--red)':'var(--muted)';

    // Balance acumulado
    const bal = trading.balance;
    const balEl = document.getElementById('balance');
    balEl.textContent = `${bal>=0?'+':''}$${Math.round(bal).toLocaleString()}`;
    balEl.className = `pnl-big ${bal>0?'pos':bal<0?'neg':'neu'}`;
    document.getElementById('wr-total').textContent =
      `WR: ${trading.wr.toFixed(0)}% | ${trading.total_trades} trades`;

    // Indicadores ADA (desde estado trading si existe)
    const tr = d.trading;
    if (tr.trade_actual) {
      const pe = tr.trade_actual.precio_entrada || 0;
      document.getElementById('ada-precio').textContent = `$${pe.toFixed(4)}`;
    }

    // Historial
    const histEl = document.getElementById('historial-list');
    if (hist && hist.length > 0) {
      histEl.innerHTML = [...hist].reverse().map(t => {
        const emoji = t.ganador ? '✅' : '🔴';
        const tipo = t.tipo || '?';
        const pnl = t.pnl_pct || 0;
        const gmxn = t.ganancia_mxn || 0;
        const fecha = (t.fecha_entrada||'').substring(0,10);
        return `<div class="hist-item">
          <span class="hist-emoji">${emoji}</span>
          <span class="hist-tipo hist-${tipo}">${tipo.toUpperCase()}</span>
          <span class="hist-fecha">${fecha}</span>
          <span class="hist-pnl" style="color:${pnl>=0?'var(--green)':'var(--red)'}">${pnl>=0?'+':''}${pnl.toFixed(2)}%</span>
          <span class="hist-mxn">${gmxn>=0?'+':''}$${Math.round(gmxn).toLocaleString()}</span>
        </div>`;
      }).join('');
    }

  } catch(e) {
    console.error('Error actualizando:', e);
  }
}

actualizar();
setInterval(actualizar, 10000);

// Actualizar RSI y F&G desde /api/señal cada 60s
async function actualizarSenal() {
  try {
    const r = await fetch('/api/senal');
    const d = await r.json();

    // RSI
    const rsi = d.rsi || 50;
    document.getElementById('rsi-val').textContent = rsi.toFixed(1);
    const rsiColor = rsi >= 72 ? 'var(--red)' : rsi <= 30 ? 'var(--green)' : 'var(--yellow)';
    document.getElementById('rsi-fill').style.width = rsi + '%';
    document.getElementById('rsi-fill').style.background = rsiColor;
    document.getElementById('rsi-val').style.color = rsiColor;

    let rsiCtx = '';
    if (rsi >= 72) rsiCtx = '🔴 Sobrecomprado → SHORT';
    else if (rsi >= 60) rsiCtx = '🟡 Alto → esperar >72';
    else if (rsi <= 30) rsiCtx = '🟢 Sobreventa → LONG';
    else if (rsi <= 40) rsiCtx = '🟡 Bajo → cerca de LONG';
    else rsiCtx = '⚪ Neutral';
    document.getElementById('rsi-ctx').textContent = rsiCtx;
    document.getElementById('rsi-ctx').style.color = rsiColor;

    // F&G
    const fng = d.fng || 50;
    document.getElementById('fng-val').textContent = fng;
    document.getElementById('fng-ptr').style.left = fng + '%';
    const fngLabels = ['Extreme Fear','Fear','Neutral','Greed','Extreme Greed'];
    const fngColors = ['var(--red)','var(--yellow)','var(--muted)','var(--green)','var(--green)'];
    const fi = fng < 25 ? 0 : fng < 45 ? 1 : fng < 55 ? 2 : fng < 75 ? 3 : 4;
    document.getElementById('fng-ctx').textContent = fngLabels[fi] + ` (${fng})`;
    document.getElementById('fng-ctx').style.color = fngColors[fi];
    document.getElementById('fng-val').style.color = fngColors[fi];

    // ADA precio
    if (d.ada_precio) {
      document.getElementById('ada-precio').textContent = `$${d.ada_precio.toFixed(4)}`;
      document.getElementById('ada-mxn').textContent = `$${(d.ada_precio * (d.tc||17.5)).toFixed(4)} MXN`;
    }

    // Mercado
    const mkEl = document.getElementById('mercado-val');
    const mk = d.mercado || '--';
    const mkEmoji = {alcista:'🚀',lateral:'➡️',bajista:'📉',neutral:'⚪'}[mk] || '⚪';
    mkEl.textContent = mkEmoji + ' ' + mk.toUpperCase();
    mkEl.style.color = mk==='alcista'?'var(--green)':mk==='bajista'?'var(--red)':'var(--muted)';
    document.getElementById('supertrend-val').textContent = `ST: ${d.supertrend||'--'}`;

  } catch(e) { console.log('Sin datos señal:', e.message); }
}

actualizarSenal();
setInterval(actualizarSenal, 60000);
</script>
</body>
</html>"""

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML.encode())

        elif self.path == '/api':
            datos = api_datos()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(datos).encode())

        elif self.path == '/api/senal':
            # Leer último snapshot del estado
            estado = cargar_json(ESTADO_FILE, {})
            trading = cargar_json(TRADING_FILE, {})
            tc = estado.get('tc', 17.5)
            # Intentar leer indicadores del estado guardado
            senal = {
                'rsi':        50,
                'fng':        estado.get('trading', {}).get('ultima_señal', {}).get('fng', 50),
                'mercado':    'neutral',
                'supertrend': 'bajista',
                'ada_precio': 0,
                'tc':         tc,
            }
            # Si hay trade activo, usar sus datos de entrada
            trade = trading.get('trade_actual')
            if trade:
                senal['rsi'] = trade.get('rsi_entrada', 50)
                senal['fng'] = trade.get('fng_entrada', 50)
                senal['mercado'] = trade.get('mercado', 'neutral')
                senal['ada_precio'] = trade.get('precio_entrada', 0)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(senal).encode())

        else:
            self.send_response(404)
            self.end_headers()

def run():
    server = http.server.HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"[Dashboard] Puerto {PORT} — http://192.168.0.10:{PORT}")
    server.serve_forever()

if __name__ == "__main__":
    run()
