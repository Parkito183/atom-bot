#!/usr/bin/env python3
"""
optimizer.py — Grid Search Automático + Push a GitHub
Prueba combinaciones de parametros y sube resultados a GitHub automaticamente.
"""
import urllib.request
import json
import time
import os
import subprocess
from datetime import datetime
from itertools import product
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

CACHE_DIR = '/mnt/Datos/Script/DOT_Bot/logs/cache'
os.makedirs(CACHE_DIR, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# GRID REDUCIDO (~5 minutos de ejecucion)
# ═══════════════════════════════════════════════════════════════
PARAM_GRID = {
    'stop_atr_mult':        [2.0, 2.5, 3.0],
    'objetivo_atr_mult':    [3.0, 3.5, 4.0],
    'rsi_long_min':         [30, 35],
    'rsi_long_max':         [70, 75],
    'rsi_short_min':        [25, 30],
    'rsi_short_max':        [60, 65],
    'max_bars':             [18, 24, 36],
    'trailing':             [True],
    'trailing_atr_mult':    [1.0, 1.5],
    'btc_confirmacion':     [True, False],
    'btc_emergencia':       [True],
    'early_exit':           [True, False],
    'early_exit_bars':      [4, 6],
    'early_exit_min_advance': [0.5, 1.0],
    'supertrend_mult':      [2.5, 3.0],
    'apalancamiento':       [3, 5],
}

# ═══════════════════════════════════════════════════════════════
# DESCARGA CON CACHE
# ═══════════════════════════════════════════════════════════════
def descargar_con_cache(symbol, interval, start_str, end_str=None):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{start_str}.json")
    if os.path.exists(cache_file):
        print(f"  💾 Cache: {symbol}")
        with open(cache_file, 'r') as f:
            return json.load(f)
    
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.strptime(end_str, '%Y-%m-%d').timestamp() * 1000) if end_str else int(datetime.now().timestamp() * 1000)
    all_velas = []
    current_ts = start_ts
    print(f"  📥 Descargando {symbol}...")
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
                time.sleep(0.15)
        except Exception as e:
            time.sleep(2)
    with open(cache_file, 'w') as f:
        json.dump(all_velas, f)
    print(f"  ✅ {symbol}: {len(all_velas)} velas")
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
    if len(diffs) < periodo: return
    gains = [max(x, 0) for x in diffs]
    losses = [max(-x, 0) for x in diffs]
    avg_gain = sum(gains[:periodo]) / periodo
    avg_loss = sum(losses[:periodo]) / periodo
    rsi_values = [None] * (periodo + 1)
    for i in range(periodo, len(diffs)):
        avg_gain = (avg_gain * (periodo - 1) + gains[i]) / periodo
        avg_loss = (avg_loss * (periodo - 1) + losses[i]) / periodo
        rsi_values.append(100 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss)))
    for i, v in enumerate(velas):
        v['rsi'] = rsi_values[i] if i < len(rsi_values) else None

def calc_ema(velas, span, nombre):
    ema_vals = _ema([v['close'] for v in velas], span)
    for i, v in enumerate(velas):
        v[nombre] = ema_vals[i]

def calc_atr(velas, periodo=14):
    n = len(velas)
    if n < 2: return
    tr = [velas[0]['high'] - velas[0]['low']]
    for i in range(1, n):
        h, l, pc = velas[i]['high'], velas[i]['low'], velas[i-1]['close']
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr_vals = _ema(tr, periodo)
    for i, v in enumerate(velas):
        v['atr'] = atr_vals[i]

def calc_supertrend(velas, periodo=10, mult=3.0):
    n = len(velas)
    if n < 2: return
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

def calc_todos_base(velas):
    calc_rsi(velas)
    calc_ema(velas, 9, 'ema9')
    calc_ema(velas, 21, 'ema21')
    calc_ema(velas, 50, 'ema50')
    calc_atr(velas)

# ═══════════════════════════════════════════════════════════════
# REGIMEN BTC
# ═══════════════════════════════════════════════════════════════
def detectar_regimen_btc(velas, i):
    v = velas[i]
    ema50 = v.get('ema50')
    st = v.get('supertrend')
    if ema50 is None or st is None: return 'lateral'
    dist = abs(v['close'] - ema50) / ema50 * 100
    if dist < 1.5: return 'lateral'
    if st == 'alcista' and v['close'] > ema50: return 'alcista'
    if st == 'bajista' and v['close'] < ema50: return 'bajista'
    return 'lateral'

# ═══════════════════════════════════════════════════════════════
# MOTOR DE BACKTEST RAPIDO
# ═══════════════════════════════════════════════════════════════
def ejecutar_backtest_rapido(ada_velas, btc_velas, c):
    capital_mxn = CONFIG['capital_mxn']
    tc = CONFIG['tc']
    trades = []
    en_trade = False
    trade = None
    
    for i in range(50, len(ada_velas)):
        if en_trade and trade:
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
            
            debe_salir, razon = False, None
            
            if tipo == 'long' and precio <= stop: debe_salir, razon = True, "stop_loss"
            elif tipo == 'short' and precio >= stop: debe_salir, razon = True, "stop_loss"
            elif tipo == 'long' and precio >= objetivo: debe_salir, razon = True, "objetivo"
            elif tipo == 'short' and precio <= objetivo: debe_salir, razon = True, "objetivo"
            elif c['early_exit'] and bars == c['early_exit_bars']:
                avance = (precio - pe) / pe * 100 if tipo == 'long' else (pe - precio) / pe * 100
                if avance < c['early_exit_min_advance']: debe_salir, razon = True, "early_exit"
            
            if not debe_salir and c['trailing']:
                if tipo == 'long':
                    umbral = pe + (objetivo - pe) * 0.5
                    if precio >= umbral and precio <= trade['precio_max'] - atr * c['trailing_atr_mult']:
                        debe_salir, razon = True, "trailing"
                else:
                    umbral = pe - (pe - objetivo) * 0.5
                    if precio <= umbral and precio >= trade['precio_min'] + atr * c['trailing_atr_mult']:
                        debe_salir, razon = True, "trailing"
            
            if not debe_salir and c['btc_emergencia']:
                btc_reg = detectar_regimen_btc(btc_velas, i)
                btc_entrada = trade.get('btc_regimen', 'neutral')
                if tipo == 'long' and btc_reg == 'bajista' and btc_entrada != 'bajista': debe_salir, razon = True, "btc_emergencia"
                elif tipo == 'short' and btc_reg == 'alcista' and btc_entrada != 'alcista': debe_salir, razon = True, "btc_emergencia"
            
            if not debe_salir and bars >= c['max_bars']: debe_salir, razon = True, "tiempo_maximo"
            
            if debe_salir:
                pnl_bruto = (precio - pe) / pe * 100 if tipo == 'long' else (pe - precio) / pe * 100
                pnl_neto = pnl_bruto - 0.0005 * 2 * 100
                cap_ef_usd = capital_mxn / tc * c['apalancamiento']
                ganancia_mxn = cap_ef_usd * pnl_neto / 100 * tc
                trades.append({'tipo': tipo, 'pnl_pct': pnl_neto, 'ganancia_mxn': ganancia_mxn, 'ganador': pnl_neto > 0, 'razon': razon})
                en_trade = False
                trade = None
        
        if not en_trade:
            v = ada_velas[i]
            v_prev = ada_velas[i-1]
            if v.get('rsi') is None or v_prev.get('rsi') is None: continue
            precio = v['close']
            atr = v.get('atr', precio * 0.02)
            rsi = v['rsi']
            st_now = v.get('supertrend')
            st_prev = v_prev.get('supertrend')
            if atr / precio * 100 < 0.3: continue
            
            btc_regimen = detectar_regimen_btc(btc_velas, i)
            
            if st_prev == 'bajista' and st_now == 'alcista':
                if c['rsi_long_min'] <= rsi <= c['rsi_long_max']:
                    if not (c['btc_confirmacion'] and btc_regimen == 'bajista'):
                        stop = precio - atr * c['stop_atr_mult']
                        objetivo = precio + atr * c['objetivo_atr_mult']
                        if (objetivo - precio) / (precio - stop) >= 2.0:
                            trade = {'tipo': 'long', 'precio_entrada': precio, 'stop': stop, 'objetivo': objetivo, 'idx_entrada': i, 'btc_regimen': btc_regimen}
                            en_trade = True
                            continue
            
            if st_prev == 'alcista' and st_now == 'bajista':
                if c['rsi_short_min'] <= rsi <= c['rsi_short_max']:
                    if not (c['btc_confirmacion'] and btc_regimen == 'alcista'):
                        stop = precio + atr * c['stop_atr_mult']
                        objetivo = precio - atr * c['objetivo_atr_mult']
                        if (precio - objetivo) / (stop - precio) >= 2.0:
                            trade = {'tipo': 'short', 'precio_entrada': precio, 'stop': stop, 'objetivo': objetivo, 'idx_entrada': i, 'btc_regimen': btc_regimen}
                            en_trade = True
    
    n = len(trades)
    if n == 0:
        return {'trades': 0, 'wr': 0, 'roi': -100, 'pnl_total': -CONFIG['capital_mxn'], 'profit_factor': 0, 'stops': 0, 'stop_ratio': 0}
    
    ganados = sum(1 for t in trades if t['ganador'])
    pnl_total = sum(t['ganancia_mxn'] for t in trades)
    gan_pos = [t['ganancia_mxn'] for t in trades if t['ganancia_mxn'] > 0]
    gan_neg = [t['ganancia_mxn'] for t in trades if t['ganancia_mxn'] <= 0]
    pf = abs(sum(gan_pos) / sum(gan_neg)) if gan_neg else 999
    stops = sum(1 for t in trades if t['razon'] == 'stop_loss')
    
    return {
        'trades': n, 'wr': ganados / n * 100, 'roi': pnl_total / CONFIG['capital_mxn'] * 100,
        'pnl_total': pnl_total, 'profit_factor': pf, 'stops': stops, 'stop_ratio': stops / n * 100,
    }

# ═══════════════════════════════════════════════════════════════
# GRID SEARCH
# ═══════════════════════════════════════════════════════════════
def run_optimizer():
    print("="*70)
    print("🤖 OPTIMIZADOR AUTOMATICO — Grid Reducido + BTC + GitHub Push")
    print("="*70)
    
    # 1. Datos
    print("\n📥 Cargando datos...")
    ada_raw = descargar_con_cache(CONFIG['symbol_ada'], CONFIG['timeframe'], CONFIG['start_date'], CONFIG['end_date'])
    btc_raw = descargar_con_cache(CONFIG['symbol_btc'], CONFIG['timeframe'], CONFIG['start_date'], CONFIG['end_date'])
    
    ts_comunes = sorted({v['ts'] for v in ada_raw} & {v['ts'] for v in btc_raw})
    ada_base = [dict(v) for v in ada_raw if v['ts'] in ts_comunes]
    btc_base = [dict(v) for v in btc_raw if v['ts'] in ts_comunes]
    print(f"🔗 Alineadas: {len(ada_base)} velas")
    
    # Precalcular indicadores base
    print("🔧 Precalculando indicadores base...")
    calc_todos_base(ada_base)
    calc_todos_base(btc_base)
    
    # 2. Combinaciones
    keys = list(PARAM_GRID.keys())
    combos = list(product(*PARAM_GRID.values()))
    total = len(combos)
    print(f"\n🔬 Combinaciones a probar: {total}")
    print("⏱️  Estimado: ~5-10 minutos\n")
    
    resultados = []
    inicio = time.time()
    
    for idx, combo in enumerate(combos, 1):
        params = dict(zip(keys, combo))
        
        # Copiar y recalcular supertrend con el mult correspondiente
        ada_copy = [dict(v) for v in ada_base]
        btc_copy = [dict(v) for v in btc_base]
        calc_supertrend(ada_copy, mult=params['supertrend_mult'])
        calc_supertrend(btc_copy, mult=params['supertrend_mult'])
        
        metricas = ejecutar_backtest_rapido(ada_copy, btc_copy, params)
        resultados.append({'rank': 0, 'params': params, **metricas})
        
        if idx % 20 == 0 or idx == 1:
            elapsed = time.time() - inicio
            pct = idx / total * 100
            eta = (elapsed / idx) * (total - idx)
            mejor_roi = max(r['roi'] for r in resultados)
            print(f"  [{idx:3}/{total}] {pct:5.1f}% | ETA: {eta/60:4.1f}min | Mejor ROI: {mejor_roi:+.1f}%")
    
    # Ordenar
    resultados.sort(key=lambda x: x['roi'], reverse=True)
    for i, r in enumerate(resultados, 1):
        r['rank'] = i
    
    # Guardar JSON
    output_file = f'/mnt/Datos/Script/DOT_Bot/logs/optimizer_results_{CONFIG["timeframe"]}.json'
    with open(output_file, 'w') as f:
        json.dump({
            'config': CONFIG, 'param_grid': {k: list(v) for k, v in PARAM_GRID.items()},
            'total_tested': len(resultados), 'top_50': resultados[:50], 'all_results': resultados,
        }, f, indent=2, default=str)
    
    # Guardar TXT legible
    txt_file = f'/mnt/Datos/Script/DOT_Bot/logs/optimizer_results_{CONFIG["timeframe"]}.txt'
    with open(txt_file, 'w') as f:
        f.write("="*70 + "\n")
        f.write("🏆 TOP 20 CONFIGURACIONES\n")
        f.write("="*70 + "\n\n")
        for r in resultados[:20]:
            p = r['params']
            f.write(f"RANK #{r['rank']} | ROI: {r['roi']:+.1f}% | P&L: ${r['pnl_total']:,.0f}\n")
            f.write(f"  Trades: {r['trades']} | WR: {r['wr']:.1f}% | PF: {r['profit_factor']:.2f} | Stops: {r['stop_ratio']:.0f}%\n")
            f.write(f"  stop={p['stop_atr_mult']}x | obj={p['objetivo_atr_mult']}x | RSI_L={p['rsi_long_min']}-{p['rsi_long_max']}\n")
            f.write(f"  max_bars={p['max_bars']} | btc_conf={p['btc_confirmacion']} | apal={p['apalancamiento']}x | st={p['supertrend_mult']}\n")
            f.write(f"  early_exit={p['early_exit']} | trailing={p['trailing']}\n\n")
    
    # Mostrar en pantalla
    print("\n" + "="*70)
    print("🏆 TOP 10 CONFIGURACIONES")
    print("="*70)
    for r in resultados[:10]:
        p = r['params']
        print(f"\n🥇 #{r['rank']} | ROI: {r['roi']:+.1f}% | ${r['pnl_total']:,.0f} | {r['trades']} trades | WR {r['wr']:.1f}%")
        print(f"   stop={p['stop_atr_mult']}x obj={p['objetivo_atr_mult']}x RSI={p['rsi_long_min']}-{p['rsi_long_max']} bars={p['max_bars']} btc={p['btc_confirmacion']} apal={p['apalancamiento']}x")
    
    print(f"\n💾 JSON: {output_file}")
    print(f"💾 TXT:  {txt_file}")
    print(f"⏱️  Tiempo: {(time.time()-inicio)/60:.1f} min")
    
    # ═══════════════════════════════════════════════════════════════
    # PUSH AUTOMATICO A GITHUB
    # ═══════════════════════════════════════════════════════════════
    print("\n🚀 Subiendo resultados a GitHub...")
    try:
        os.chdir('/mnt/Datos/Script/DOT_Bot')
        subprocess.run(['git', 'add', 'logs/optimizer_results_*.json', 'logs/optimizer_results_*.txt'], check=True)
        subprocess.run(['git', 'commit', '-m', f'Optimizer results {CONFIG["timeframe"]} {datetime.now().isoformat()}'], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print("✅ Subido a GitHub exitosamente!")
        print(f"   Ver en: https://github.com/Parkito183/atom-bot/tree/main/logs")
    except subprocess.CalledProcessError as e:
        print(f"⚠️  Error en git push: {e}")
        print("   Posible solucion: ejecuta 'git pull origin main' primero")

if __name__ == "__main__":
    run_optimizer()
