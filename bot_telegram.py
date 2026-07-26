"""
bot_telegram.py — ATOM Bot v2 — Comandos Telegram
Teclado: /atom /trade /posicion /historial /modo /alertas
"""
import urllib.request, json, os, time
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_env_path = os.path.join(_BASE_DIR, "config.env")
if os.path.exists(_env_path):
    for _l in open(_env_path).readlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.split("#")[0].strip())

TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
COMPRAS_FILE     = os.path.join(_BASE_DIR, "compras_atom.json")
LOGS_DIR         = os.path.join(_BASE_DIR, "logs")
SEP = "━━━━━━━━━━━━━━━━━━━"

TECLADO = {
    "keyboard": [
        [{"text": "🌌 Atom"},     {"text": "📊 Trade"},    {"text": "💼 Posición"}],
        [{"text": "📋 Historial"},{"text": "🤖 Modo"},     {"text": "🔔 Alertas"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

_ultimo_update_id = None

def enviar(msg: str, silencioso: bool = False):
    url     = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id":              TELEGRAM_CHAT_ID,
        "text":                 msg[:4096],
        "parse_mode":           "Markdown",
        "reply_markup":         TECLADO,
        "disable_notification": silencioso,
    }
    try:
        data = json.dumps(payload).encode()
        req  = urllib.request.Request(url, data=data,
                                       headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"⚠️ Telegram error: {e}")

def escuchar() -> list:
    global _ultimo_update_id
    comandos = []
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates?timeout=5"
    if _ultimo_update_id:
        url += f"&offset={_ultimo_update_id + 1}"
    try:
        with urllib.request.urlopen(url, timeout=12) as r:
            data = json.loads(r.read())
            for u in data.get("result", []):
                _ultimo_update_id = u["update_id"]
                msg     = u.get("message", {})
                chat_id = str(msg.get("chat", {}).get("id", ""))
                txt     = msg.get("text", "").strip()
                if chat_id == str(TELEGRAM_CHAT_ID) and txt:
                    comandos.append(txt)
    except Exception as e:
        print(f"⚠️ Error escuchando: {e}")
    return comandos

def cargar_compras() -> list:
    try:    return json.load(open(COMPRAS_FILE))
    except: return []

# ── Mensajes ATOM (blockchain) ─────────────────────────────────
def msg_bienvenida() -> str:
    return "\n".join([
        "🌌 *ATOM Bot v2 — Online*",
        SEP,
        "📈 Trading: LONG / SHORT / SCALPING",
        "🔍 Modo: VIGILANCIA cada 15 min",
        "🥷 En trade: NINJA cada 2 min",
        SEP,
        "*/atom*     → Cartera ATOM completa",
        "*/trade*    → Análisis y señal actual",
        "*/posicion* → P&L del trade activo",
        "*/historial*→ Últimos 10 trades",
        "*/modo*     → Estado del bot",
        "*/alertas*  → Configuración alertas",
    ])

def msg_atom_completo(saldos: dict, precio_usd: float, tc: float,
                       compras: list) -> str:
    if not precio_usd: return "⚠️ Sin precio disponible"
    if not isinstance(saldos, dict): saldos = {}
    disponible  = saldos.get("disponible", 0)
    staking     = saldos.get("staking", 0)
    rewards     = saldos.get("rewards", 0)
    unbonding   = saldos.get("unbonding", 0)
    validadores = saldos.get("validadores", [])
    total       = disponible + staking + rewards + unbonding
    valor_usd   = total * precio_usd
    valor_mxn   = valor_usd * tc
    APR         = 0.15
    dia_atom    = staking * APR / 365
    mes_atom    = staking * APR / 12
    dia_mxn     = dia_atom * precio_usd * tc
    mes_mxn     = mes_atom * precio_usd * tc
    # Validador principal
    val_nombre  = validadores[0].get("nombre","Everstake") if validadores and isinstance(validadores[0], dict) else (validadores[0] if validadores else "Everstake")
    # Wallet corta
    wallet      = saldos.get("wallet","cosmos10a7...lxln4")
    wallet_corta= wallet[:12]+"..."+wallet[-4:] if len(wallet)>16 else wallet
    lineas = [
        "🌌 *REPORTE ATOM*",
        SEP,
        f"Libre:   *{disponible:.4f}* ATOM",
        f"Staking: *{staking:.4f}* ATOM",
        f"Rewards: *{rewards:.6f}* ATOM",
    ]
    if unbonding > 0:
        lineas.append(f"⏳ Unbonding: *{unbonding:.4f}* ATOM")
    lineas += [
        SEP,
        "✅ Staking activo",
        f"🏛 Validador: *{val_nombre}*",
        SEP,
        f"📊 Total: *{total:.4f}* ATOM",
        f"💵 Precio: *${precio_usd:.4f}* USD (${precio_usd*tc:.2f} MXN)",
        f"💰 Valor: *${valor_mxn:,.2f}* MXN (${valor_usd:,.2f} USD)",
        SEP,
        f"🏛 Staking ~15% APR:",
        f"Diario:  *{dia_atom:.4f}* ATOM (${dia_mxn:.2f} MXN)",
        f"Mensual: *{mes_atom:.4f}* ATOM (${mes_mxn:.2f} MXN)",
        f"📍 Wallet: `{wallet_corta}`",
    ]
    return "\n".join(lineas)

# ── Mensajes Trading ───────────────────────────────────────────
def msg_trade_actual(snap: dict, estado_t: dict) -> str:
    """Análisis de mercado y señal actual."""
    from trading.gestor import descripcion_señal, contexto_mercado
    return descripcion_señal(snap)

def msg_posicion(precio_usd: float, tc: float, estado_t: dict) -> str:
    """P&L del trade activo en tiempo real."""
    from trading.simulador import estado_trade_actual
    trade = estado_trade_actual(precio_usd, tc)
    if not trade:
        return "\n".join([
            "⏳ *SIN POSICIÓN ACTIVA*",
            SEP,
            "El bot está en modo VIGILANCIA",
            "Evaluando señales cada 15 minutos",
        ])
    tipo  = trade['tipo']
    pnl   = trade['pnl_pct']
    gmxn  = trade['ganancia_mxn']
    pe    = trade['precio_entrada']
    emoji = "📈" if tipo=="long" else "📉" if tipo=="short" else "⚡"
    ganancia_str = f"{'✅ +' if gmxn>=0 else '🔴 '}{gmxn:,.0f} MXN"
    return "\n".join([
        f"{emoji} *POSICIÓN ACTIVA — {tipo.upper()}*",
        SEP,
        f"Entrada: *${pe:.6f}* USD",
        f"Actual:  *${precio_usd:.6f}* USD",
        f"P&L: *{pnl:+.2f}%*  →  {ganancia_str}",
        f"Capital: *${trade['capital_mxn']:,}* × {trade['apalancamiento']}x",
        f"Desde: {trade['fecha_entrada'][:16].replace('T',' ')}",
        f"Modo: 🥷 *NINJA* — monitoreo cada 2 min",
    ])

def msg_historial(resumen: dict, tc: float) -> str:
    """Últimos 10 trades."""
    hist = resumen.get('historial', [])
    if not hist:
        return "📋 *Sin historial de trades aún*"
    lineas = [
        "📋 *HISTORIAL — Últimos trades*",
        SEP,
        f"Total: {resumen['total_trades']} | WR: {resumen['win_rate']:.0f}% | "
        f"Balance: {'+'if resumen['balance_mxn']>=0 else ''}{resumen['balance_mxn']:,.0f} MXN",
        SEP,
    ]
    for t in reversed(hist[-10:]):
        emoji = "✅" if t.get('ganador') else "🔴"
        tipo  = t.get('tipo','?').upper()[:5]
        pnl   = t.get('pnl_pct', 0)
        gmxn  = t.get('ganancia_mxn', 0)
        fecha = t.get('fecha_entrada','')[:10]
        lineas.append(f"{emoji} [{tipo}] {fecha}: {pnl:+.2f}% → {'+' if gmxn>=0 else ''}{gmxn:,.0f} MXN")
    # Por estrategia
    lineas.append(SEP)
    for tipo, datos in resumen.get('por_tipo', {}).items():
        lineas.append(f"{'📈' if tipo=='long' else '📉' if tipo=='short' else '⚡'} "
                      f"{tipo.upper()}: {datos['trades']} trades | "
                      f"WR:{datos['wr']:.0f}% | {'+' if datos['ganancia_mxn']>=0 else ''}"
                      f"{datos['ganancia_mxn']:,.0f} MXN")
    return "\n".join(lineas)

def msg_modo(estado_t: dict, tc: float) -> str:
    """Estado actual del bot."""
    from trading.simulador import resumen_completo
    en_trade = estado_t.get('en_trade', False)
    trade    = estado_t.get('trade_actual')
    if en_trade and trade:
        tipo = trade.get('tipo','?').upper()
        emoji = "🥷"
        modo_str = f"NINJA — en trade {tipo}"
        detalle = f"Entrada: ${trade.get('precio_entrada',0):.6f} USD"
    else:
        emoji = "🔍"
        modo_str = "VIGILANCIA — buscando señales"
        detalle = "Evaluando cada 15 minutos"
    from trading.simulador import CAPITAL_MXN
    res  = resumen_completo(tc)
    bal  = res['balance_mxn']
    if en_trade and trade:
        apala   = {'long':8,'short':8,'scalping':4}.get(trade.get('tipo','long'), 8)
        cap_str = f"Capital operando: *${CAPITAL_MXN*apala:,}* MXN ({apala}x)"
    else:
        c8 = CAPITAL_MXN * 8
        c4 = CAPITAL_MXN * 4
        cap_str = f"Capital base: *${CAPITAL_MXN:,}* MXN\n  LONG/SHORT: *${c8:,}* MXN (8x)\n  SCALPING: *${c4:,}* MXN (4x)"
    signo = '+' if bal >= 0 else ''
    return "\n".join([
        f"{emoji} *MODO: {modo_str}*",
        SEP,
        detalle,
        cap_str,
        SEP,
        f"Trades: {res['total_trades']} | WR: {res['win_rate']:.0f}%",
        f"P&L acumulado: *{signo}{bal:,.0f}* MXN",
        f"_Actualizado: {datetime.now().strftime('%H:%M:%S')}_",
    ])

def msg_alertas(precio_ref: float, tc: float, cfg: dict) -> str:
    return "\n".join([
        "🔔 *ALERTAS CONFIGURADAS*",
        SEP,
        f"Precio referencia: *${precio_ref:.4f}* USD (${precio_ref*tc:.2f} MXN)" if precio_ref else "Sin precio ref",
        SEP,
        f"📉 Baja 1: -{cfg.get('baja_1',5):.0f}%",
        f"📉 Baja 2: -{cfg.get('baja_2',10):.0f}%",
        f"📉 Baja 3: -{cfg.get('baja_3',15):.0f}%",
        f"📈 Suba 1: +{cfg.get('suba_1',5):.0f}%",
        f"📈 Suba 2: +{cfg.get('suba_2',10):.0f}%",
        f"📈 Suba 3: +{cfg.get('suba_3',15):.0f}%",
    ])

# ── Procesador principal de comandos ───────────────────────────
def procesar(txt: str, saldos: dict, precio_usd: float, tc: float,
             precio_ref: float, alertas_cfg: dict, estado_t: dict, resumen: dict):
    cmd = txt.lower().strip()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Cmd: {txt}")

    if cmd in ("/atom", "/start", "🌌 atom"):
        compras = cargar_compras()
        # Si no hay datos en memoria, cargar del estado guardado
        _saldos = saldos if isinstance(saldos, dict) and saldos else {}
        _precio = precio_usd
        _tc     = tc
        if not _saldos or not _precio:
            try:
                import json, os
                _estado = json.load(open(os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "logs", "estado_atom.json")))
                if not _saldos: _saldos = _estado.get("saldos") or {}
                if not _precio: _precio = _estado.get("precio_actual") or 0
                if not _tc:     _tc     = _estado.get("tc") or 17.5
            except: pass
        enviar(msg_atom_completo(_saldos, _precio, _tc, compras))

    elif cmd in ("/trade", "📊 trade"):
        try:
            from trading.señales import snapshot_actual
            snap = snapshot_actual(tc)
            if snap:
                enviar(msg_trade_actual(snap, estado_t))
            else:
                enviar("⚠️ Sin datos de mercado en este momento")
        except Exception as e:
            enviar(f"⚠️ Error obteniendo señal: {e}")

    elif cmd in ("/posicion", "💼 posición", "💼 posicion"):
        enviar(msg_posicion(precio_usd, tc, estado_t))

    elif cmd in ("/historial", "📋 historial"):
        enviar(msg_historial(resumen, tc))

    elif cmd in ("/modo", "🤖 modo"):
        enviar(msg_modo(estado_t, tc))

    elif cmd in ("/alertas", "🔔 alertas"):
        enviar(msg_alertas(precio_ref, tc, alertas_cfg))

    elif cmd in ("/ayuda", "/help"):
        enviar(msg_bienvenida())

    else:
        enviar(f"❓ Comando no reconocido: `{txt}`\nUsa /ayuda para ver los disponibles.")
