"""
estrategias.py — v3
Motor único ATR + Supertrend, validado train/val (WR mejora en reciente: 45%→67%)
Reemplaza el RSI-cruce-exacto (casi nunca disparaba) y elimina SCALPING (no viable en 4H)
"""

CFG = {
    'stop_atr_mult':      3.0,
    'objetivo_atr_mult':  4.5,
    'min_rr':             1.5,
    'rsi_periodo':        21,
    'rsi_long_min':       40, 'rsi_long_max': 80,
    'rsi_short_min':      30, 'rsi_short_max': 75,
    'max_bars':           48,      # 8 días en 4H
    'atr_min_pct':        0.5,
    'trailing':           False,
    'btc_confirmacion':   False,   # validado: sin este filtro funciona mejor
    'btc_emergencia':     True,    # sí sale si BTC voltea en contra
    'supertrend_periodo': 10,
    'supertrend_mult':    2.0,
    'apalancamiento':     6,       # bajado de 8x a 6x para el primer mes en vivo
    'fng_min':            15,      # solo bloquea pánico extremo
    'comision':           0.0005,
}

def detectar_regimen_btc(snap):
    ema50 = snap.get('btc_ema50'); st = snap.get('btc_supertrend')
    precio = snap.get('btc_precio')
    if not ema50 or not st or not precio: return 'lateral'
    dist = abs(precio-ema50)/ema50*100
    if dist < 1.5: return 'lateral'
    if st=='alcista' and precio>ema50: return 'alcista'
    if st=='bajista' and precio<ema50: return 'bajista'
    return 'lateral'

def señal_long(snap):
    """Supertrend ADA voltea bajista→alcista + RSI en rango + BTC no bloquea (emergencia sí aplica en salida)."""
    if snap['fng'] < CFG['fng_min']: return False
    if snap.get('st_prev')!='bajista' or snap.get('supertrend')!='alcista': return False
    rsi = snap['rsi']
    if not (CFG['rsi_long_min'] <= rsi <= CFG['rsi_long_max']): return False
    if snap.get('atr_pct', 1) < CFG['atr_min_pct']: return False
    if CFG['btc_confirmacion'] and detectar_regimen_btc(snap)=='bajista': return False
    # ratio riesgo:recompensa mínimo lo valida el sizing, no aquí
    return True

def señal_short(snap):
    """Supertrend ADA voltea alcista→bajista + RSI en rango."""
    if snap['fng'] < CFG['fng_min']: return False
    if snap.get('st_prev')!='alcista' or snap.get('supertrend')!='bajista': return False
    rsi = snap['rsi']
    if not (CFG['rsi_short_min'] <= rsi <= CFG['rsi_short_max']): return False
    if snap.get('atr_pct', 1) < CFG['atr_min_pct']: return False
    if CFG['btc_confirmacion'] and detectar_regimen_btc(snap)=='alcista': return False
    return True

def calcular_niveles(tipo, precio, atr):
    if tipo=='long':
        stop = precio - atr*CFG['stop_atr_mult']
        obj  = precio + atr*CFG['objetivo_atr_mult']
    else:
        stop = precio + atr*CFG['stop_atr_mult']
        obj  = precio - atr*CFG['objetivo_atr_mult']
    return stop, obj

def señal_salida(tipo, precio_actual, trade, snap):
    """Evalúa salida: stop, objetivo, tiempo máximo, o emergencia BTC."""
    stop = trade['stop']; obj = trade['objetivo']
    bars = trade.get('bars_transcurridas', 0)

    if tipo=='long' and precio_actual<=stop: return True, 'stop'
    if tipo=='short' and precio_actual>=stop: return True, 'stop'
    if tipo=='long' and precio_actual>=obj: return True, 'objetivo'
    if tipo=='short' and precio_actual<=obj: return True, 'objetivo'

    if CFG['btc_emergencia']:
        reg_ahora = detectar_regimen_btc(snap)
        reg_entrada = trade.get('btc_regimen','lateral')
        if tipo=='long' and reg_ahora=='bajista' and reg_entrada!='bajista':
            return True, 'btc_emergencia'
        if tipo=='short' and reg_ahora=='alcista' and reg_entrada!='alcista':
            return True, 'btc_emergencia'

    if bars >= CFG['max_bars']: return True, 'tiempo'
    return False, None

def pnl_neto(tipo, precio_entrada, precio_salida):
    pnl = (precio_salida-precio_entrada)/precio_entrada*100 if tipo=='long' \
          else (precio_entrada-precio_salida)/precio_entrada*100
    return pnl - CFG['comision']*2*100

def capital_efectivo_usd(capital_mxn=10_000, tc=17.5):
    return capital_mxn/tc*CFG['apalancamiento']

def ganancia_mxn(pnl_pct, capital_mxn=10_000, tc=17.5):
    return capital_efectivo_usd(capital_mxn, tc) * pnl_pct/100 * tc
