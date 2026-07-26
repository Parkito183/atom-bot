"""
gestor.py — v3
Selector: LONG/SHORT vía Supertrend cross (motor ATR validado). Sin SCALPING.
"""
from .estrategias import señal_long, señal_short, CFG, detectar_regimen_btc

FNG_PANICO = 15

def elegir_estrategia(snap):
    """Retorna 'long', 'short', o None."""
    if snap.get('fng', 50) < FNG_PANICO:
        return None
    if señal_short(snap):
        return 'short'
    if señal_long(snap):
        return 'long'
    return None

def contexto_mercado(snap):
    fng = snap.get('fng', 50)
    rsi = snap.get('rsi', 50)
    mk  = snap.get('mercado', 'neutral')
    st  = snap.get('supertrend', 'bajista')
    btc_reg = detectar_regimen_btc(snap)

    if fng < 15:   estado = "🔴 PÁNICO EXTREMO — sin trading"
    elif fng < 25: estado = "🟠 MIEDO EXTREMO"
    elif fng < 45: estado = "🟡 MIEDO"
    elif fng < 55: estado = "🟢 NEUTRAL"
    elif fng < 75: estado = "🚀 CODICIA"
    else:          estado = "⚠️ CODICIA EXTREMA"

    estrategia = elegir_estrategia(snap)
    estrategia_str = {
        'long':  "📈 LONG — Supertrend volteó alcista",
        'short': "📉 SHORT — Supertrend volteó bajista",
        None:    "⏳ ESPERANDO — sin cruce de Supertrend",
    }.get(estrategia, "⏳ ESPERANDO")

    return {
        'fng': fng, 'rsi': rsi, 'mercado': mk, 'supertrend': st,
        'btc_regimen': btc_reg, 'estado_mercado': estado,
        'estrategia': estrategia, 'estrategia_str': estrategia_str,
    }

def _fng_label(v):
    if v<15: return "Extreme Fear 🔴"
    if v<25: return "Extreme Fear 🟠"
    if v<45: return "Fear 🟡"
    if v<55: return "Neutral 🟢"
    if v<75: return "Greed 🚀"
    return "Extreme Greed ⚠️"

def descripcion_señal(snap):
    ctx = contexto_mercado(snap)
    SEP = "━━━━━━━━━━━━━━━━━━━"
    rsi = snap['rsi']; tc = snap.get('tc',17.5)
    btc_mxn = snap['btc_precio']*tc

    if CFG['rsi_long_min']<=rsi<=CFG['rsi_long_max']:
        rsi_ctx = f"*{rsi:.1f}* 🟢 en rango LONG ({CFG['rsi_long_min']}-{CFG['rsi_long_max']})"
    elif CFG['rsi_short_min']<=rsi<=CFG['rsi_short_max']:
        rsi_ctx = f"*{rsi:.1f}* 🟡 en rango SHORT ({CFG['rsi_short_min']}-{CFG['rsi_short_max']})"
    else:
        rsi_ctx = f"*{rsi:.1f}* fuera de ambos rangos"

    lineas = [
        "🔍 *ANÁLISIS DE MERCADO*", SEP,
        f"💹 ADA: *${snap['ada_precio']:.4f}* USD (*${snap['ada_precio_mxn']:.2f}* MXN)",
        f"₿ BTC: *${btc_mxn:,.0f}* MXN",
        SEP,
        f"📊 RSI({CFG['rsi_periodo']}): {rsi_ctx}",
        f"🌡️ Fear & Greed: *{snap['fng']}* — {_fng_label(snap['fng'])}",
        f"📈 Mercado ADA: *{ctx['mercado'].upper()}*",
        f"🎯 Supertrend ADA: *{ctx['supertrend']}*",
        f"₿ Régimen BTC: *{ctx['btc_regimen']}*",
        f"📏 ATR: *{snap.get('atr_pct',0):.2f}%* del precio",
        SEP,
        f"Estado: {ctx['estado_mercado']}",
        f"Señal: *{ctx['estrategia_str']}*",
    ]
    return "\n".join(lineas)
