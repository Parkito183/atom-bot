"""
gestor.py — Selector automático de estrategia
Decide qué estrategia usar según el contexto del mercado
"""
from .estrategias import señal_long, señal_short, señal_scalping, CFG, FNG_PANICO

def elegir_estrategia(snap) -> str | None:
    """
    Evalúa el snapshot del mercado y retorna:
    'long', 'short', 'scalping', o None (no operar)
    
    Prioridad:
    1. Pánico extremo (F&G < 15) → ninguna
    2. SHORT (sobrecompra RSI>72) → mayor prioridad
    3. LONG (RSI cruce + condiciones ideales)
    4. SCALPING (RSI cruce + mercado bajista leve)
    """
    fng = snap.get('fng', 50)

    # Pánico extremo — no operar nada
    if fng < FNG_PANICO:
        return None

    # Prioridad 1: SHORT (funciona en cualquier mercado)
    if señal_short(snap):
        return 'short'

    # Prioridad 2: LONG (condiciones ideales)
    if señal_long(snap):
        return 'long'

    # Prioridad 3: SCALPING (mercado bajista leve, F&G 15-25)
    if señal_scalping(snap):
        return 'scalping'

    return None

def contexto_mercado(snap) -> dict:
    """Retorna un resumen del contexto actual del mercado."""
    fng  = snap.get('fng', 50)
    rsi  = snap.get('rsi', 50)
    mk   = snap.get('mercado', 'neutral')
    st   = snap.get('supertrend', 'bajista')

    if fng < 15:
        estado = "🔴 PÁNICO EXTREMO — sin trading"
    elif fng < 25:
        estado = "🟠 MIEDO EXTREMO — solo scalping"
    elif fng < 45:
        estado = "🟡 MIEDO — trading selectivo"
    elif fng < 55:
        estado = "🟢 NEUTRAL — todas las estrategias"
    elif fng < 75:
        estado = "🚀 CODICIA — long + short activos"
    else:
        estado = "⚠️ CODICIA EXTREMA — cuidado"

    estrategia_actual = elegir_estrategia(snap)
    estrategia_str = {
        'long':     "📈 LONG — rebote detectado",
        'short':    "📉 SHORT — sobrecompra detectada",
        'scalping': "⚡ SCALPING — objetivo rápido",
        None:       "⏳ ESPERANDO — sin señal",
    }.get(estrategia_actual, "⏳ ESPERANDO")

    return {
        'fng':              fng,
        'rsi':              rsi,
        'mercado':          mk,
        'supertrend':       st,
        'estado_mercado':   estado,
        'estrategia':       estrategia_actual,
        'estrategia_str':   estrategia_str,
        'btc_ok':           snap.get('btc_ok_long', True),
        'diff_btc':         snap.get('diff_btc', 0),
    }

def descripcion_señal(snap) -> str:
    """Genera descripción textual de la señal actual para Telegram."""
    ctx    = contexto_mercado(snap)
    SEP    = "━━━━━━━━━━━━━━━━━━━"
    rsi    = snap['rsi']
    fng    = snap['fng']
    tc     = snap.get('tc', 17.5)
    btc_mxn = snap['btc_precio'] * tc

    # Contexto RSI — qué estamos esperando
    if rsi >= 72:
        rsi_ctx = f"*{rsi:.1f}* 🔴 Sobrecomprado → señal SHORT activa"
    elif rsi >= 60:
        rsi_ctx = f"*{rsi:.1f}* 🟡 Alto → esperamos >72 para SHORT"
    elif rsi >= 45:
        rsi_ctx = f"*{rsi:.1f}* 🟢 Neutral → esperamos cruce <30 para LONG"
    elif rsi >= 30:
        rsi_ctx = f"*{rsi:.1f}* 🟡 Bajando → cerca del cruce <30 para LONG"
    else:
        rsi_ctx = f"*{rsi:.1f}* 🔴 Sobreventa → esperando cruce >30 para LONG"

    # Contexto F&G — qué necesitamos
    if fng < 15:
        fng_ctx = "necesitamos >15 para cualquier trade"
    elif fng < 25:
        fng_ctx = "necesitamos >25 para LONG, >40 para SHORT"
    elif fng < 40:
        fng_ctx = "LONG disponible, necesitamos >40 para SHORT"
    else:
        fng_ctx = "todas las estrategias disponibles"

    # Contexto correlación BTC
    diff = ctx['diff_btc']
    if diff >= 2.0:
        diff_ctx = f"*{diff:+.2f}%* 🔴 ADA sube fuerte vs BTC → señal SHORT"
    elif diff >= 0:
        diff_ctx = f"*{diff:+.2f}%* 🟡 ADA sube vs BTC → vigilar"
    else:
        diff_ctx = f"*{diff:+.2f}%* 🟢 ADA débil vs BTC → vigilar LONG"

    lineas = [
        "🔍 *ANÁLISIS DE MERCADO*",
        SEP,
        f"💹 ADA: *${snap['ada_precio']:.4f}* USD (*${snap['ada_precio_mxn']:.2f}* MXN)",
        f"₿ BTC: *${btc_mxn:,.0f}* MXN",
        SEP,
        f"📊 RSI(14): {rsi_ctx}",
        f"🌡️ Fear & Greed: *{fng}* — {_fng_label(fng)}",
        f"   └ {fng_ctx}",
        f"📈 Mercado: *{ctx['mercado'].upper()}*",
        f"🎯 Supertrend: *{ctx['supertrend']}*",
        f"🔗 ADA vs BTC (3v): {diff_ctx}",
        SEP,
        f"Estado: {ctx['estado_mercado']}",
        f"Señal: *{ctx['estrategia_str']}*",
    ]
    return "\n".join(lineas)

def _fng_label(v):
    if v < 15:   return "Extreme Fear 🔴"
    if v < 25:   return "Extreme Fear 🟠"
    if v < 45:   return "Fear 🟡"
    if v < 55:   return "Neutral 🟢"
    if v < 75:   return "Greed 🚀"
    return "Extreme Greed ⚠️"
