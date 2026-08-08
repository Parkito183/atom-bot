#!/usr/bin/env python3
"""
backtest_v5.py — VALIDACION de parametros ganadores del Optimizer (+385.8%)
Basado en backtest_v4.py con parametros optimizados.
"""
import urllib.request
import json
import time
import os
from datetime import datetime
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# CONFIGURACION
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    'symbol_ada': 'ADAUSDT',
    'symbol_btc': 'BTCUSDT',
    'timeframe': '4h',
    'start_date': '2023-01-01',
    'end_date': None,
    'capital_mxn': 10000,
    'tc': 17.5,
}

# ═══════════════════════════════════════════════════════════════
# PARAMETROS GANADORES DEL OPTIMIZER (+385.8% ROI)
# ═══════════════════════════════════════════════════════════════
ESTRATEGIA = {
    'nombre': 'Optimizer Winner Validation',
    'apalancamiento': 5,           # ← 5x (vs 3x en V4)
    'comision': 0.0005,

    'btc_confirmacion': True,
    'btc_emergencia': True,

    'rsi_long_min': 30,            # ← 30 (vs 35)
    'rsi_long_max': 70,            # ← 70 (vs 75)
    'rsi_short_min': 25,
    'rsi_short_max': 65,

    'stop_atr_mult': 2.0,          # ← 2.0x (vs 1.5x)
    'objetivo_atr_mult': 4.0,      # ← 4.0x (vs 3.0x)
    'trailing': True,
    'trailing_atr_mult': 1.0,
    'max_bars': 36,                # ← 36 (vs 24)
    'atr_min_pct': 0.3,            # ← 0.3 (vs 0.5, mas permisivo)

    # NUEVO: Early Exit (del optimizer)
    'early_exit': False,
    'early_exit_bars': 4,
    'early_exit_min_advance': 0.5,
}

# ═══════════════════════════════════════════════════════════════
# DESCARGA
# ═══════════════════════════════════════════════════════════════
def descargar_velas(symbol, interval, start_str, end_str=None):
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
                print(f"  ↳ {symbol}: {len(all_velas)} velas...")
                time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ Error {symbol}: {e}")
            time.sleep(2)
    print(f"✅ {symbol}: {len(all_velas)} velas")
    return all_velas

# ═══════════════════════════════════════════════════════════════
# INDICADORES
# ═══════════════════════════════════════════════════════════════
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
# REGIMEN BTC
# ═══════════════════════════════════════════════════════════════
def detectar_regimen_btc(velas, i):
    v = velas[i]
    precio = v['close']
    ema50 = v.get('ema50')
    st = v.get('supertrend')
    if ema50 is None or st is None:
        return 'lateral'
    distancia = abs(precio - ema50) / ema50 * 100
    if distancia < 1.5:
        return 'lateral'
    if st == 'alcista' and precio > ema50:
        return 'alcista'
    if st == 'bajista' and precio < ema50:
        return 'bajista'
    return 'lateral'

# ═══════════════════════════════════════════════════════════════
# ESTRATEGIA CON PARAMETROS GANADORES
# ═══════════════════════════════════════════════════════════════
def buscar_entrada(ada_velas, btc_velas, i, c):
    v = ada_velas[i]
    v_prev = ada_velas[i-1]
    if v.get('rsi') is None or v_prev.get('rsi') is None:
        return None
    precio = v['close']
    atr = v.get('atr', precio * 0.02)
    rsi = v['rsi']
    st_now = v.get('supertrend')
    st_prev = v_prev.get('supertrend')
    if atr / precio * 100 < c['atr_min_pct']:
        return None
    btc_regimen = detectar_regimen_btc(btc_velas, i)

    # === LONG ===
    if st_prev == 'bajista' and st_now == 'alcista':
        if c['rsi_long_min'] <= rsi <= c['rsi_long_max']:
            if c['btc_confirmacion'] and btc_regimen == 'bajista':
                return None
            stop = precio - atr * c['stop_atr_mult']
            objetivo = precio + atr * c['objetivo_atr_mult']
            riesgo = precio - stop
            recompensa = objetivo - precio
            if recompensa / riesgo >= 2.0:
                return 'long', stop, objetivo, btc_regimen

    # === SHORT ===
    if st_prev == 'alcista' and st_now == 'bajista':
        if c['rsi_short_min'] <= rsi <= c['rsi_short_max']:
            if c['btc_confirmacion'] and btc_regimen == 'alcista':
                return None
            stop = precio + atr * c['stop_atr_mult']
            objetivo = precio - atr * c['objetivo_atr_mult']
            riesgo = stop - precio
            recompensa = precio - objetivo
            if recompensa / riesgo >= 2.0:
                return 'short', stop, objetivo, btc_regimen
    return None

def evaluar_salida(trade, ada_velas, btc_velas, i, c):
    v = ada_velas[i]
    precio = v['close']
    tipo = trade['tipo']
    pe = trade['precio_entrada']
    stop = trade['stop']
    objetivo = trade['objetivo']
    atr = v.get('atr', pe * 0.02)
    bars = i - trade['idx_entrada']

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

    # NUEVO: Early Exit
    if c.get('early_exit') and bars == c['early_exit_bars']:
        if tipo == 'long':
            avance = (precio - pe) / pe * 100
            if avance < c['early_exit_min_advance']:
                return True, "early_exit"
        else:
            avance = (pe - precio) / pe * 100
            if avance < c['early_exit_min_advance']:
                return True, "early_exit"

    # Trailing
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

    # Emergencia BTC
    if c.get('btc_emergencia'):
        btc_regimen_actual = detectar_regimen_btc(btc_velas, i)
        btc_regimen_entrada = trade.get('btc_regimen', 'neutral')
        if tipo == 'long' and btc_regimen_actual == 'bajista' and btc_regimen_entrada != 'bajista':
            return True, "btc_emergencia"
        if tipo == 'short' and btc_regimen_actual == 'alcista' and btc_regimen_entrada != 'alcista':
            return True, "btc_emergencia"

    # Tiempo maximo
    if bars >= c['max_bars']:
        return True, "tiempo_maximo"

    return False, None

# ═══════════════════════════════════════════════════════════════
# MOTOR
# ═══════════════════════════════════════════════════════════════
def ejecutar_backtest(ada_velas, btc_velas):
    capital_mxn = CONFIG['capital_mxn']
    tc = CONFIG['tc']
    c = ESTRATEGIA

    trades = []
    en_trade = False
    trade = None

    for i in range(50, len(ada_velas)):
        if en_trade and trade:
            debe_salir, razon = evaluar_salida(trade, ada_velas, btc_velas, i, c)
            if debe_salir:
                precio_salida = ada_velas[i]['close']
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
                    'fecha_entrada': datetime.fromtimestamp(ada_velas[trade['idx_entrada']]['ts']/1000).isoformat(),
                    'fecha_salida': datetime.fromtimestamp(ada_velas[i]['ts']/1000).isoformat(),
                    'pnl_pct': pnl_neto,
                    'ganancia_mxn': ganancia_mxn,
                    'ganador': pnl_neto > 0,
                    'razon': razon,
                    'bars': i - trade['idx_entrada'],
                    'btc_regimen': trade.get('btc_regimen'),
                })

                en_trade = False
                trade = None

        if not en_trade:
            senal = buscar_entrada(ada_velas, btc_velas, i, c)
            if senal:
                tipo, stop, objetivo, btc_reg = senal
                trade = {
                    'tipo': tipo,
                    'precio_entrada': ada_velas[i]['close'],
                    'stop': stop,
                    'objetivo': objetivo,
                    'idx_entrada': i,
                    'btc_regimen': btc_reg,
                }
                en_trade = True

    return trades

# ═══════════════════════════════════════════════════════════════
# REPORTE
# ═══════════════════════════════════════════════════════════════
def imprimir_reporte(trades):
    print("\n" + "="*70)
    print(f"📊 BACKTEST V5 — VALIDACION Optimizer Winner (+385.8%)")
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

    por_btc = defaultdict(lambda: {'trades': 0, 'ganados': 0, 'pnl': 0})
    for t in trades:
        r = t['btc_regimen']
        por_btc[r]['trades'] += 1
        por_btc[r]['pnl'] += t['ganancia_mxn']
        if t['ganador']:
            por_btc[r]['ganados'] += 1

    por_razon = defaultdict(lambda: {'count': 0, 'pnl': 0})
    for t in trades:
        por_razon[t['razon']]['count'] += 1
        por_razon[t['razon']]['pnl'] += t['ganancia_mxn']

    print(f"\n📈 Trades totales:     {n}")
    print(f"✅ Ganados:            {ganados} ({wr:.1f}%)")
    print(f"🔴 Perdidos:           {perdidos}")
    print(f"💰 P&L Total:          ${pnl_total:,.2f} MXN")
    print(f"📊 ROI:                {pnl_total/CONFIG['capital_mxn']*100:+.2f}%")
    print(f"🚀 Mejor trade:        ${max(ganancias):,.2f} MXN")
    print(f"💥 Peor trade:         ${min(ganancias):,.2f} MXN")
    print(f"💵 Promedio:           ${sum(ganancias)/n:,.2f} MXN")

    print(f"\n📋 Por régimen BTC al entrar:")
    for r, d in por_btc.items():
        wr_r = d['ganados']/d['trades']*100 if d['trades'] > 0 else 0
        print(f"  BTC {r.upper():8} | Trades: {d['trades']:3} | WR: {wr_r:5.1f}% | P&L: ${d['pnl']:,.2f}")

    print(f"\n📋 Por razón de salida:")
    for r, d in por_razon.items():
        print(f"  {r:20} | Count: {d['count']:3} | P&L: ${d['pnl']:,.2f}")

    print("="*70)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    ada_velas = descargar_velas(CONFIG['symbol_ada'], CONFIG['timeframe'], CONFIG['start_date'], CONFIG['end_date'])
    btc_velas = descargar_velas(CONFIG['symbol_btc'], CONFIG['timeframe'], CONFIG['start_date'], CONFIG['end_date'])

    if not ada_velas or not btc_velas:
        exit(1)

    ts_ada = {v['ts'] for v in ada_velas}
    ts_btc = {v['ts'] for v in btc_velas}
    ts_comunes = sorted(ts_ada & ts_btc)

    ada_velas = [v for v in ada_velas if v['ts'] in ts_comunes]
    btc_velas = [v for v in btc_velas if v['ts'] in ts_comunes]

    print(f"🔗 Velas alineadas: {len(ada_velas)}")

    print("🔧 Calculando indicadores ADA...")
    ada_velas = calc_todos(ada_velas)
    print("🔧 Calculando indicadores BTC...")
    btc_velas = calc_todos(btc_velas)

    print("🧪 Ejecutando VALIDACION V5...")
    trades = ejecutar_backtest(ada_velas, btc_velas)
    imprimir_reporte(trades)

    import json
    with open('/mnt/Datos/Script/DOT_Bot/logs/backtest_v5_validation.json', 'w') as f:
        json.dump({'trades': trades, 'config': CONFIG, 'estrategia': ESTRATEGIA}, f, indent=2, default=str)
    print("\n💾 Guardado en logs/backtest_v5_validation.json")
