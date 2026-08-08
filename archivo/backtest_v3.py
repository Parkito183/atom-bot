#!/usr/bin/env python3
"""
backtest_v3.py — Estrategia Adaptativa por Régimen de Mercado
Siempre opera en la dirección de la tendencia. Nunca contra ella.
"""
import urllib.request
import json
import time
import os
from datetime import datetime
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    'symbol': 'ADAUSDT',
    'timeframe': '4h',
    'start_date': '2023-01-01',
    'end_date': None,
    'capital_mxn': 10000,
    'tc': 17.5,
}

# ═══════════════════════════════════════════════════════════════
# ESTRATEGIA ADAPTATIVA
# ═══════════════════════════════════════════════════════════════
ESTRATEGIA = {
    'nombre': 'Adaptive Trend Following',
    'apalancamiento': 3,
    'comision': 0.0005,
    
    # Detección de régimen (usando EMA 50 vs precio)
    'ema_regimen': 50,
    'tendencia_min_bars': 5,  # Mínimo velas confirmando tendencia
    
    # Entrada (Supertrend + EMA9/21 + RSI filtro)
    'rsi_long_min': 35,
    'rsi_long_max': 75,
    'rsi_short_min': 25,
    'rsi_short_max': 65,
    
    # Gestión de riesgo
    'stop_atr_mult': 1.5,
    'objetivo_atr_mult': 3.0,   # R:R 1:2
    'trailing': True,
    'trailing_atr_mult': 1.0,
    'max_bars': 24,
    
    # Filtro: solo operar si ATR > mínimo (evitar mercado plano)
    'atr_min_pct': 0.5,  # ATR debe ser > 0.5% del precio
}

# ═══════════════════════════════════════════════════════════════
# DESCARGA Y INDICADORES (mismos que v2)
# ═══════════════════════════════════════════════════════════════
def descargar_velas_historicas(symbol, interval, start_str, end_str=None):
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_str, '%Y-%m-%d').timestamp() * 1000) if end_str else int(datetime.now().timestamp() * 1000)
    all_velas = []
    current_ts = start_ts
    print(f"📥 Descargando {symbol} {interval}...")
    while current_ts < end_ts:
        url = f"{url_base}?symbol={symbol}&interval={interval}&startTime={current_ts}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data: break
                for v in data:
                    all_velas.append({'ts': int(v[0]), 'open': float(v[1]), 'high': float(v[2]), 'low': float(v[3]), 'close': float(v[4]), 'vol': float(v[5])})
                current_ts = data[-1][0] + 1
                print(f"  ↳ {len(all_velas)} velas...")
                time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(2)
    print(f"✅ Total: {len(all_velas)} velas")
    return all_velas

def _ema(vals, span):
    k = 2 / (span + 1)
    e = [vals[0]]
    for v in vals[1:]:
        e.append(v * k + e[-1] * (1 - k))
    return e

def calc_rsi(velas, periodo=14):
    closes = [v['close'] for v in velas]
    diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    if len(diffs) < periodo:
        return velas
    gains = [max(x, 0) for x in diffs]
    losses = [max(-x, 0) for x in diffs]
    avg_gain = sum(gains[:periodo]) / periodo
    avg_loss = sum(losses[:periodo]) / periodo
    rsi_values = [None] * (periodo + 1)
    for i in range(periodo, len(diffs)):
        avg_gain = (avg_gain * (periodo - 1) + gains[i]) / periodo
        avg_loss = (avg_loss * (periodo - 1) + losses[i]) / periodo
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rsi_values.append(100 - (100 / (1 + avg_gain / avg_loss)))
    for i, v in enumerate(velas):
        v['rsi'] = rsi_values[i] if i < len(rsi_values) else None
    return velas

def calc_ema(velas, span, nombre):
    closes = [v['close'] for v in velas]
    ema_vals = _ema(closes, span)
    for i, v in enumerate(velas):
        v[nombre] = ema_vals[i]
    return velas

def calc_atr(velas, periodo=14):
    n = len(velas)
    if n < 2:
        return velas
    tr = [velas[0]['high'] - velas[0]['low']]
    for i in range(1, n):
        h, l, pc = velas[i]['high'], velas[i]['low'], velas[i-1]['close']
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_vals = _ema(tr, periodo)
    for i, v in enumerate(velas):
        v['atr'] = atr_vals[i]
    return velas

def calc_supertrend(velas, periodo=10, mult=3.0):
    n = len(velas)
    if n < 2:
        return velas
    tr = [velas[0]['high'] - velas[0]['low']]
    for i in range(1, n):
        h, l, pc = velas[i]['high'], velas[i]['low'], velas[i-1]['close']
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = _ema(tr, periodo)
    upper = [((velas[i]['high'] + velas[i]['low']) / 2) + mult * atr[i] for i in range(n)]
    lower = [((velas[i]['high'] + velas[i]['low']) / 2) - mult * atr[i] for i in range(n)]
    st = ['bajista'] * n
    stl = [upper[0]] * n
    for i in range(1, n):
        c = velas[i]['close']
        if st[i-1] == 'alcista':
            lower[i] = max(lower[i], stl[i-1])
            st[i] = 'bajista' if c < stl[i-1] else 'alcista'
            stl[i] = upper[i] if st[i] == 'bajista' else lower[i]
        else:
            upper[i] = min(upper[i], stl[i-1])
            st[i] = 'alcista' if c > stl[i-1] else 'bajista'
            stl[i] = lower[i] if st[i] == 'alcista' else upper[i]
    for i in range(n):
        velas[i]['supertrend'] = st[i]
    return velas

def calc_todos(velas):
    calc_rsi(velas)
    calc_ema(velas, 9, 'ema9')
    calc_ema(velas, 21, 'ema21')
    calc_ema(velas, 50, 'ema50')
    calc_atr(velas)
    calc_supertrend(velas)
    return velas

# ═══════════════════════════════════════════════════════════════
# DETECCIÓN DE RÉGIMEN DE MERCADO
# ═══════════════════════════════════════════════════════════════
def detectar_regimen(velas, i, c):
    """
    Detecta si el mercado está en tendencia alcista, bajista o lateral.
    Retorna: 'alcista', 'bajista', o 'lateral'
    """
    v = velas[i]
    precio = v['close']
    ema50 = v.get('ema50')
    
    if ema50 is None:
        return 'lateral'
    
    # Distancia del precio a EMA50
    distancia = abs(precio - ema50) / ema50 * 100
    
    # Si está muy cerca de la EMA50 = lateral
    if distancia < 2.0:
        return 'lateral'
    
    # Contar velas consecutivas arriba/abajo de EMA50
    alcistas = 0
    bajistas = 0
    for j in range(max(0, i - c['tendencia_min_bars'] + 1), i + 1):
        if velas[j]['close'] > velas[j].get('ema50', 0):
            alcistas += 1
        else:
            bajistas += 1
    
    if alcistas >= c['tendencia_min_bars']:
        return 'alcista'
    if bajistas >= c['tendencia_min_bars']:
        return 'bajista'
    
    return 'lateral'

# ═══════════════════════════════════════════════════════════════
# ESTRATEGIA ADAPTATIVA
# ═══════════════════════════════════════════════════════════════
def buscar_entrada(velas, i, c):
    """
    Busca señal de entrada SOLO en la dirección de la tendencia.
    Nunca opera contra la tendencia.
    """
    v = velas[i]
    v_prev = velas[i-1]
    
    if v.get('rsi') is None or v_prev.get('rsi') is None:
        return None
    
    precio = v['close']
    atr = v.get('atr', precio * 0.02)
    rsi = v['rsi']
    st_now = v.get('supertrend')
    st_prev = v_prev.get('supertrend')
    
    # Filtro: ATR mínimo (evitar mercado plano)
    if atr / precio * 100 < c['atr_min_pct']:
        return None
    
    # Detectar régimen
    regimen = detectar_regimen(velas, i, c)
    
    # === SOLO LONG en tendencia alcista ===
    if regimen == 'alcista':
        # Supertrend cambia a alcista + RSI en zona saludable
        if st_prev == 'bajista' and st_now == 'alcista':
            if c['rsi_long_min'] <= rsi <= c['rsi_long_max']:
                stop = precio - atr * c['stop_atr_mult']
                objetivo = precio + atr * c['objetivo_atr_mult']
                riesgo = precio - stop
                recompensa = objetivo - precio
                if recompensa / riesgo >= 2.0:
                    return 'long', stop, objetivo
    
    # === SOLO SHORT en tendencia bajista ===
    elif regimen == 'bajista':
        # Supertrend cambia a bajista + RSI en zona saludable
        if st_prev == 'alcista' and st_now == 'bajista':
            if c['rsi_short_min'] <= rsi <= c['rsi_short_max']:
                stop = precio + atr * c['stop_atr_mult']
                objetivo = precio - atr * c['objetivo_atr_mult']
                riesgo = stop - precio
                recompensa = precio - objetivo
                if recompensa / riesgo >= 2.0:
                    return 'short', stop, objetivo
    
    # === LATERAL: No operar ===
    return None

def evaluar_salida(trade, velas, i, c):
    v = velas[i]
    precio = v['close']
    tipo = trade['tipo']
    pe = trade['precio_entrada']
    stop = trade['stop']
    objetivo = trade['objetivo']
    atr = v.get('atr', pe * 0.02)
    
    trade['precio_max'] = max(trade.get('precio_max', pe), precio)
    trade['precio_min'] = min(trade.get('precio_min', pe), precio)
    
    # Stop loss
    if tipo == 'long' and precio <= stop:
        return True, "stop_loss"
    if tipo == 'short' and precio >= stop:
        return True, "stop_loss"
    
    # Objetivo
    if tipo == 'long' and precio >= objetivo:
        return True, "objetivo"
    if tipo == 'short' and precio <= objetivo:
        return True, "objetivo"
    
    # Trailing stop
    if c.get('trailing'):
        if tipo == 'long':
            umbral = pe + (objetivo - pe) * 0.5
            if precio >= umbral:
                trail = trade['precio_max'] - atr * c['trailing_atr_mult']
                if precio <= trail:
                    return True, "trailing"
        else:
            umbral = pe - (pe - objetivo) * 0.5
            if precio <= umbral:
                trail = trade['precio_min'] + atr * c['trailing_atr_mult']
                if precio >= trail:
                    return True, "trailing"
    
    # Tiempo máximo
    if i - trade['idx_entrada'] >= c['max_bars']:
        return True, "tiempo_maximo"
    
    return False, None

# ═══════════════════════════════════════════════════════════════
# MOTOR DE BACKTEST
# ═══════════════════════════════════════════════════════════════
def ejecutar_backtest(velas):
    capital_mxn = CONFIG['capital_mxn']
    tc = CONFIG['tc']
    c = ESTRATEGIA
    
    trades = []
    en_trade = False
    trade = None
    regimen_actual = 'lateral'
    
    for i in range(50, len(velas)):
        v = velas[i]
        
        # Actualizar régimen para logs
        regimen = detectar_regimen(velas, i, c)
        if regimen != regimen_actual:
            regimen_actual = regimen
            print(f"  [{datetime.fromtimestamp(v['ts']/1000).strftime('%Y-%m-%d')}] Régimen: {regimen.upper()}")
        
        if en_trade and trade:
            debe_salir, razon = evaluar_salida(trade, velas, i, c)
            if debe_salir:
                precio_salida = v['close']
                pe = trade['precio_entrada']
                tipo = trade['tipo']
                
                if tipo == 'long':
                    pnl_bruto = (precio_salida - pe) / pe * 100
                else:
                    pnl_bruto = (pe - precio_salida) / pe * 100
                
                pnl_neto = pnl_bruto - c['comision'] * 2 * 100
                cap_ef_usd = capital_mxn / tc * c['apalancamiento']
                ganancia_mxn = cap_ef_usd * pnl_neto / 100 * tc
                
                trades.append({
                    'tipo': tipo,
                    'entrada': pe,
                    'salida': precio_salida,
                    'pnl_pct': pnl_neto,
                    'ganancia_mxn': ganancia_mxn,
                    'ganador': pnl_neto > 0,
                    'razon': razon,
                    'bars': i - trade['idx_entrada'],
                    'regimen': trade['regimen'],
                })
                
                en_trade = False
                trade = None
        
        if not en_trade:
            senal = buscar_entrada(velas, i, c)
            if senal:
                tipo, stop, objetivo = senal
                trade = {
                    'tipo': tipo,
                    'precio_entrada': v['close'],
                    'stop': stop,
                    'objetivo': objetivo,
                    'idx_entrada': i,
                    'regimen': regimen_actual,
                }
                en_trade = True
    
    return trades

# ═══════════════════════════════════════════════════════════════
# REPORTE
# ═══════════════════════════════════════════════════════════════
def imprimir_reporte(trades):
    print("\n" + "="*70)
    print(f"📊 BACKTEST V3 — {ESTRATEGIA['nombre']}")
    print("="*70)
    
    n = len(trades)
    if n == 0:
        print("❌ Sin trades")
        return
    
    ganados = sum(1 for t in trades if t['ganador'])
    perdidos = n - ganados
    wr = ganados / n * 100
    pnl_total = sum(t['ganancia_mxn'] for t in trades)
    
    ganancias = [t['ganancia_mxn'] for t in trades]
    
    # Por régimen
    por_regimen = defaultdict(lambda: {'trades': 0, 'ganados': 0, 'pnl': 0})
    for t in trades:
        r = t['regimen']
        por_regimen[r]['trades'] += 1
        por_regimen[r]['pnl'] += t['ganancia_mxn']
        if t['ganador']:
            por_regimen[r]['ganados'] += 1
    
    print(f"\n📈 Trades totales:     {n}")
    print(f"✅ Ganados:            {ganados} ({wr:.1f}%)")
    print(f"🔴 Perdidos:           {perdidos}")
    print(f"💰 P&L Total:          ${pnl_total:,.2f} MXN")
    print(f"📊 ROI:                {pnl_total/CONFIG['capital_mxn']*100:+.2f}%")
    print(f"🚀 Mejor trade:        ${max(ganancias):,.2f} MXN")
    print(f"💥 Peor trade:         ${min(ganancias):,.2f} MXN")
    print(f"💵 Promedio:           ${sum(ganancias)/n:,.2f} MXN")
    
    print(f"\n📋 Por régimen de mercado:")
    for r, d in por_regimen.items():
        wr_r = d['ganados']/d['trades']*100 if d['trades'] > 0 else 0
        print(f"  {r.upper():10} | Trades: {d['trades']:3} | WR: {wr_r:5.1f}% | P&L: ${d['pnl']:,.2f}")
    
    print("="*70)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    velas = descargar_velas_historicas(CONFIG['symbol'], CONFIG['timeframe'], CONFIG['start_date'], CONFIG['end_date'])
    if not velas:
        exit(1)
    
    print("🔧 Calculando indicadores...")
    velas = calc_todos(velas)
    
    print("🧪 Ejecutando backtest V3 (Adaptive)...")
    trades = ejecutar_backtest(velas)
    imprimir_reporte(trades)
    
    import json
    with open('/mnt/Datos/Script/DOT_Bot/logs/backtest_v3_resultados.json', 'w') as f:
        json.dump({'trades': trades, 'config': CONFIG, 'estrategia': ESTRATEGIA}, f, indent=2, default=str)
    print("\n💾 Guardado en logs/backtest_v3_resultados.json")
