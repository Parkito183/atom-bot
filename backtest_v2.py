#!/usr/bin/env python3
"""
backtest_v2.py — Backtesting con estrategias optimizadas
Basado en Supertrend + RSI filtro, EMA Crossover, y VWAP Reversion
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
# ESTRATEGIAS OPTIMIZADAS (apalan. reducido para backtest realista)
# ═══════════════════════════════════════════════════════════════
ESTRATEGIAS = {
    'supertrend_rsi': {
        'nombre': 'Supertrend + RSI',
        'apalancamiento': 3,  # Reducido — primero validar sin quemar capital
        'comision': 0.0005,
        'rr_minimo': 2.0,     # Solo entra si R:R >= 1:2
        # Entrada
        'rsi_long_min': 40,
        'rsi_long_max': 70,
        'rsi_short_min': 30,
        'rsi_short_max': 60,
        # Salida
        'stop_atr_mult': 1.5,
        'objetivo_atr_mult': 3.0,  # 2× el riesgo
        'trailing': True,
        'trailing_atr_mult': 1.0,
        'max_bars': 24,
    },
    'ema_cross': {
        'nombre': 'EMA 9/21 Crossover',
        'apalancamiento': 3,
        'comision': 0.0005,
        'rr_minimo': 1.5,
        'ema_rapida': 9,
        'ema_lenta': 21,
        'vol_min_ratio': 1.2,  # Volumen actual > 1.2× VolMA
        'stop_atr_mult': 2.0,
        'objetivo_atr_mult': 4.0,
        'trailing': True,
        'trailing_atr_mult': 1.5,
        'max_bars': 30,
    },
    'vwap_scalp': {
        'nombre': 'VWAP Reversion',
        'apalancamiento': 2,  # Scalping = bajo apalancamiento
        'comision': 0.001,
        'rr_minimo': 1.5,
        'rsi_long_max': 40,
        'rsi_short_min': 60,
        'distancia_vwap_pct': 2.0,  # Precio debe estar 2% lejos de VWAP
        'stop_pct': 1.5,
        'objetivo_pct': 3.0,
        'max_bars': 6,
    }
}

# ═══════════════════════════════════════════════════════════════
# DESCARGA DE DATOS
# ═══════════════════════════════════════════════════════════════
def descargar_velas_historicas(symbol, interval, start_str, end_str=None):
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_str, '%Y-%m-%d').timestamp() * 1000) if end_str else int(datetime.now().timestamp() * 1000)
    
    all_velas = []
    current_ts = start_ts
    
    print(f"📥 Descargando {symbol} {interval} desde {start_str}...")
    while current_ts < end_ts:
        url = f"{url_base}?symbol={symbol}&interval={interval}&startTime={current_ts}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data: break
                for v in data:
                    all_velas.append({
                        'ts': int(v[0]), 'open': float(v[1]), 'high': float(v[2]),
                        'low': float(v[3]), 'close': float(v[4]), 'vol': float(v[5]),
                    })
                current_ts = data[-1][0] + 1
                print(f"  ↳ {len(all_velas)} velas...")
                time.sleep(0.2)
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(2)
    print(f"✅ Total: {len(all_velas)} velas")
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

def calc_vwap(velas):
    cpv = cv = 0
    for v in velas:
        tp = (v['high'] + v['low'] + v['close']) / 3
        cpv += tp * v['vol']
        cv += v['vol']
        v['vwap'] = cpv / cv if cv > 0 else v['close']
    return velas

def calc_volma(velas, periodo=20):
    vols = [v['vol'] for v in velas]
    for i, v in enumerate(velas):
        v['volma'] = sum(vols[max(0, i-periodo+1):i+1]) / min(periodo, i+1)
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
        velas[i]['supertrend_line'] = stl[i]
    return velas

def calc_todos(velas):
    calc_rsi(velas)
    calc_ema(velas, 9, 'ema9')
    calc_ema(velas, 21, 'ema21')
    calc_vwap(velas)
    calc_volma(velas)
    calc_atr(velas)
    calc_supertrend(velas)
    return velas

# ═══════════════════════════════════════════════════════════════
# ESTRATEGIAS
# ═══════════════════════════════════════════════════════════════
def señal_supertrend_rsi(velas, i, c):
    v = velas[i]
    v_prev = velas[i-1]
    if v.get('rsi') is None or v_prev.get('rsi') is None:
        return None
    
    st_now = v.get('supertrend')
    st_prev = v_prev.get('supertrend')
    rsi = v['rsi']
    atr = v.get('atr', v['close'] * 0.02)
    precio = v['close']
    
    # LONG: Supertrend cambia a alcista + RSI en zona saludable
    if st_prev == 'bajista' and st_now == 'alcista':
        if c['rsi_long_min'] <= rsi <= c['rsi_long_max']:
            stop = precio - atr * c['stop_atr_mult']
            objetivo = precio + atr * c['objetivo_atr_mult']
            riesgo = precio - stop
            recompensa = objetivo - precio
            if recompensa / riesgo >= c['rr_minimo']:
                return 'long', stop, objetivo
    
    # SHORT: Supertrend cambia a bajista + RSI en zona saludable
    if st_prev == 'alcista' and st_now == 'bajista':
        if c['rsi_short_min'] <= rsi <= c['rsi_short_max']:
            stop = precio + atr * c['stop_atr_mult']
            objetivo = precio - atr * c['objetivo_atr_mult']
            riesgo = stop - precio
            recompensa = precio - objetivo
            if recompensa / riesgo >= c['rr_minimo']:
                return 'short', stop, objetivo
    
    return None

def señal_ema_cross(velas, i, c):
    v = velas[i]
    v_prev = velas[i-1]
    if v.get('ema9') is None or v.get('ema21') is None:
        return None
    
    e9 = v['ema9']
    e21 = v['ema21']
    e9_prev = v_prev['ema9']
    e21_prev = v_prev['ema21']
    atr = v.get('atr', v['close'] * 0.02)
    precio = v['close']
    vol_ratio = v.get('vol', 1) / max(v.get('volma', 1), 0.001)
    
    if vol_ratio < c['vol_min_ratio']:
        return None
    
    # LONG: EMA9 cruza arriba de EMA21
    if e9_prev <= e21_prev and e9 > e21:
        stop = precio - atr * c['stop_atr_mult']
        objetivo = precio + atr * c['objetivo_atr_mult']
        riesgo = precio - stop
        recompensa = objetivo - precio
        if recompensa / riesgo >= c['rr_minimo']:
            return 'long', stop, objetivo
    
    # SHORT: EMA9 cruza abajo de EMA21
    if e9_prev >= e21_prev and e9 < e21:
        stop = precio + atr * c['stop_atr_mult']
        objetivo = precio - atr * c['objetivo_atr_mult']
        riesgo = stop - precio
        recompensa = precio - objetivo
        if recompensa / riesgo >= c['rr_minimo']:
            return 'short', stop, objetivo
    
    return None

def señal_vwap_scalp(velas, i, c):
    v = velas[i]
    if v.get('rsi') is None or v.get('vwap') is None:
        return None
    
    precio = v['close']
    vwap = v['vwap']
    rsi = v['rsi']
    distancia = abs(precio - vwap) / vwap * 100
    
    if distancia < c['distancia_vwap_pct']:
        return None
    
    # LONG: Precio debajo de VWAP + RSI sobreventa
    if precio < vwap and rsi <= c['rsi_long_max']:
        stop = precio * (1 - c['stop_pct']/100)
        objetivo = vwap  # Objetivo = regresar a VWAP
        riesgo = precio - stop
        recompensa = objetivo - precio
        if recompensa / riesgo >= c['rr_minimo']:
            return 'long', stop, objetivo
    
    # SHORT: Precio arriba de VWAP + RSI sobrecompra
    if precio > vwap and rsi >= c['rsi_short_min']:
        stop = precio * (1 + c['stop_pct']/100)
        objetivo = vwap
        riesgo = stop - precio
        recompensa = precio - objetivo
        if recompensa / riesgo >= c['rr_minimo']:
            return 'short', stop, objetivo
    
    return None

def evaluar_salida(trade, velas, i, c):
    v = velas[i]
    precio = v['close']
    tipo = trade['tipo']
    pe = trade['precio_entrada']
    stop = trade['stop']
    objetivo = trade['objetivo']
    atr = v.get('atr', pe * 0.02)
    
    # Actualizar max/min
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
    
    # Trailing stop (solo si ya ganó más del 50% del objetivo)
    if c.get('trailing'):
        if tipo == 'long':
            umbral_trailing = pe + (objetivo - pe) * 0.5
            if precio >= umbral_trailing:
                trail_stop = trade['precio_max'] - atr * c['trailing_atr_mult']
                if precio <= trail_stop:
                    return True, "trailing"
        else:
            umbral_trailing = pe - (pe - objetivo) * 0.5
            if precio <= umbral_trailing:
                trail_stop = trade['precio_min'] + atr * c['trailing_atr_mult']
                if precio >= trail_stop:
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
    
    resultados = defaultdict(lambda: {'trades': [], 'ganados': 0, 'perdidos': 0, 'pnl_total': 0})
    
    for estrategia_nombre, c in ESTRATEGIAS.items():
        en_trade = False
        trade = None
        
        for i in range(50, len(velas)):
            v = velas[i]
            
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
                    
                    t_result = {
                        'tipo': tipo,
                        'estrategia': estrategia_nombre,
                        'entrada': pe,
                        'salida': precio_salida,
                        'pnl_pct': pnl_neto,
                        'ganancia_mxn': ganancia_mxn,
                        'ganador': pnl_neto > 0,
                        'razon': razon,
                        'bars': i - trade['idx_entrada'],
                    }
                    
                    resultados[estrategia_nombre]['trades'].append(t_result)
                    resultados[estrategia_nombre]['pnl_total'] += ganancia_mxn
                    if pnl_neto > 0:
                        resultados[estrategia_nombre]['ganados'] += 1
                    else:
                        resultados[estrategia_nombre]['perdidos'] += 1
                    
                    en_trade = False
                    trade = None
            
            if not en_trade:
                # Probar cada estrategia
                senal = None
                if estrategia_nombre == 'supertrend_rsi':
                    senal = señal_supertrend_rsi(velas, i, c)
                elif estrategia_nombre == 'ema_cross':
                    senal = señal_ema_cross(velas, i, c)
                elif estrategia_nombre == 'vwap_scalp':
                    senal = señal_vwap_scalp(velas, i, c)
                
                if senal:
                    tipo, stop, objetivo = senal
                    trade = {
                        'tipo': tipo,
                        'precio_entrada': v['close'],
                        'stop': stop,
                        'objetivo': objetivo,
                        'idx_entrada': i,
                    }
                    en_trade = True
    
    return resultados

# ═══════════════════════════════════════════════════════════════
# REPORTE
# ═══════════════════════════════════════════════════════════════
def imprimir_reporte(resultados):
    print("\n" + "="*70)
    print("📊 RESULTADOS BACKTEST V2 — Estrategias Optimizadas")
    print("="*70)
    
    total_global = 0
    for nombre, data in resultados.items():
        trades = data['trades']
        n = len(trades)
        if n == 0:
            print(f"\n🔹 {nombre.upper()}: Sin trades")
            continue
        
        ganados = data['ganados']
        wr = ganados / n * 100 if n > 0 else 0
        pnl = data['pnl_total']
        
        ganancias = [t['ganancia_mxn'] for t in trades]
        mejor = max(ganancias)
        peor = min(ganancias)
        
        print(f"\n{'='*70}")
        print(f"🔹 {ESTRATEGIAS[nombre]['nombre'].upper()}")
        print(f"   Trades: {n} | WR: {wr:.1f}% | P&L: ${pnl:,.2f} MXN")
        print(f"   Mejor: ${mejor:,.2f} | Peor: ${peor:,.2f}")
        print(f"   Apalancamiento: {ESTRATEGIAS[nombre]['apalancamiento']}x")
        
        total_global += pnl
    
    print(f"\n{'='*70}")
    print(f"💰 P&L TOTAL COMBINADO: ${total_global:,.2f} MXN")
    print(f"📊 ROI: {total_global/CONFIG['capital_mxn']*100:+.2f}%")
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
    
    print("🧪 Ejecutando backtest V2...")
    resultados = ejecutar_backtest(velas)
    imprimir_reporte(resultados)
    
    # Guardar
    import json
    with open('/mnt/Datos/Script/DOT_Bot/logs/backtest_v2_resultados.json', 'w') as f:
        json.dump({k: {'trades': v['trades'], 'pnl_total': v['pnl_total']} for k,v in resultados.items()}, f, indent=2, default=str)
    print("\n💾 Guardado en logs/backtest_v2_resultados.json")
