"""
estrategias.py — Lógica de cada estrategia de trading
LONG, SHORT, SCALPING — señales de entrada y salida
"""

# ── Configuración de estrategias ───────────────────────────────
CFG = {
    # LONG — rebote desde sobreventa
    'long': {
        'rsi_umbral':    30,
        'objetivo_pct':   5.0,
        'stop_pct':       7.0,
        'max_dias':       6,
        'trailing':       True,
        'trailing_pct':   2.0,
        'plan_b_rsi':     25,
        'plan_b_stop':   15.0,
        'plan_b_dias':   20,
        'fng_min':       25,
        'apalancamiento': 8,
        'comision':       0.001,
    },
    # SHORT — venta en sobrecompra
    'short': {
        'rsi_min':       72,
        'diff_btc_min':   2.0,
        'ada_sube_min':   0.5,
        'objetivo_pct':   5.0,
        'stop_pct':       4.0,
        'max_dias':       6,
        'trailing':       True,
        'trailing_pct':   1.5,
        'fng_min':       40,
        'apalancamiento': 8,
        'comision':       0.0005,
    },
    # SCALPING — salida rápida con VWAP
    'scalping': {
        'rsi_umbral':    30,
        'objetivo_pct':   1.0,
        'stop_pct':       2.0,
        'max_dias':       1,
        'trailing':       False,
        'fng_min':       15,
        'apalancamiento': 4,
        'comision':       0.001,
        'vwap_salida':   True,
        'wr_salida':     True,
        'wr_umbral':    -20,
    },
}

FNG_PANICO = 15   # por debajo → no operar nada

def señal_long(snap):
    """Retorna True si hay señal de entrada LONG."""
    c = CFG['long']
    if snap['fng'] < FNG_PANICO:            return False
    if snap['fng'] < c['fng_min']:          return False
    if not snap['btc_ok_long']:             return False
    if snap['mercado'] == 'bajista' and snap['fng'] < 30: return False
    rsi   = snap['rsi']
    rsi_p = snap['rsi_prev']
    # RSI cruce hacia arriba desde sobreventa
    return rsi_p is not None and rsi_p < c['rsi_umbral'] and rsi >= c['rsi_umbral']

def señal_short(snap):
    """Retorna True si hay señal de entrada SHORT."""
    c = CFG['short']
    if snap['fng'] < FNG_PANICO:            return False
    if snap['fng'] < c['fng_min']:          return False
    rsi   = snap['rsi']
    diff  = snap['diff_btc']
    av    = snap['ada_vela_pct']
    # RSI sobrecomprado + ADA sube más que BTC
    return rsi >= c['rsi_min'] and diff >= c['diff_btc_min'] and av >= c['ada_sube_min']

def señal_scalping(snap):
    """Retorna True si hay señal de entrada SCALPING."""
    c = CFG['scalping']
    if snap['fng'] < FNG_PANICO:            return False
    if snap['fng'] < c['fng_min']:          return False
    if snap['mercado'] == 'bajista':        return False
    rsi   = snap['rsi']
    rsi_p = snap['rsi_prev']
    return rsi_p is not None and rsi_p < c['rsi_umbral'] and rsi >= c['rsi_umbral']

def señal_salida_long(precio_actual, trade, snap):
    """Evalúa si debe salir del trade LONG. Retorna (debe_salir, razon)."""
    c     = CFG['long']
    pe    = trade['precio_entrada']
    pmax  = trade.get('precio_max', pe)
    pnl   = (precio_actual - pe) / pe * 100
    en_pb = trade.get('plan_b', False)

    if precio_actual > pmax:
        trade['precio_max'] = precio_actual
        pmax = precio_actual

    if not en_pb:
        # Stop loss normal
        if precio_actual <= pe*(1-c['stop_pct']/100):
            rsi = snap.get('rsi') or 50
            if rsi <= c['plan_b_rsi']:
                trade['plan_b'] = True
                return False, "plan_b_activado"
            return True, "stop_loss"
        # Trailing
        if c['trailing'] and pmax >= pe*(1+c['objetivo_pct']/100):
            if (pmax-precio_actual)/pmax*100 >= c['trailing_pct']:
                return True, "trailing"
        # Objetivo sin trailing
        if not c['trailing'] and precio_actual >= pe*(1+c['objetivo_pct']/100):
            return True, "objetivo"
        # VWAP salida inteligente (solo si hay ganancia)
        if pnl > 0.3 and snap.get('vwap') and precio_actual < snap['vwap']:
            return True, "vwap"
        if pnl > 0.3 and snap.get('wr') and snap['wr'] > -20:
            return True, "williams_r"
    else:
        # Plan B activo — stop ampliado
        if precio_actual <= pe*(1-c['plan_b_stop']/100):
            return True, "stop_plan_b"
        if pnl >= c['objetivo_pct']:
            return True, "objetivo_plan_b"

    return False, None

def señal_salida_short(precio_actual, trade, snap):
    """Evalúa si debe salir del trade SHORT."""
    c    = CFG['short']
    pe   = trade['precio_entrada']
    pmin = trade.get('precio_min', pe)
    pnl  = (pe - precio_actual) / pe * 100

    if precio_actual < pmin:
        trade['precio_min'] = precio_actual
        pmin = precio_actual

    # Stop loss: precio sube
    if precio_actual >= pe*(1+c['stop_pct']/100):
        return True, "stop_loss"
    # Trailing desde objetivo
    if c['trailing'] and pmin <= pe*(1-c['objetivo_pct']/100):
        if (precio_actual-pmin)/pmin*100 >= c['trailing_pct']:
            return True, "trailing"
    if not c['trailing'] and precio_actual <= pe*(1-c['objetivo_pct']/100):
        return True, "objetivo"

    return False, None

def señal_salida_scalping(precio_actual, trade, snap):
    """Evalúa si debe salir del trade SCALPING."""
    c   = CFG['scalping']
    pe  = trade['precio_entrada']
    pnl = (precio_actual - pe) / pe * 100

    if precio_actual <= pe*(1-c['stop_pct']/100):
        return True, "stop_loss"
    if precio_actual >= pe*(1+c['objetivo_pct']/100):
        return True, "objetivo"
    # Salida inteligente
    if pnl > 0.2:
        if c['vwap_salida'] and snap.get('vwap') and precio_actual < snap['vwap']:
            return True, "vwap"
        if c['wr_salida'] and snap.get('wr') and snap['wr'] > c['wr_umbral']:
            return True, "williams_r"

    return False, None

def pnl_neto(tipo, precio_entrada, precio_salida):
    """Calcula P&L neto descontando comisiones."""
    c = CFG[tipo]
    if tipo in ('long', 'scalping'):
        pnl = (precio_salida - precio_entrada) / precio_entrada * 100
    else:  # short
        pnl = (precio_entrada - precio_salida) / precio_entrada * 100
    return pnl - c['comision'] * 2 * 100

def capital_efectivo_usd(tipo, capital_mxn=10_000, tc=17.5):
    return capital_mxn / tc * CFG[tipo]['apalancamiento']

def ganancia_mxn(tipo, pnl_pct, capital_mxn=10_000, tc=17.5):
    cap = capital_efectivo_usd(tipo, capital_mxn, tc)
    return cap * pnl_pct / 100 * tc
