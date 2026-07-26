#!/usr/bin/env python3
"""
backtest.py — Backtesting ATOM Bot v2
Descarga datos históricos de Binance Futures y simula estrategias.
"""
import urllib.request
import json
import time
import os
from datetime import datetime, timedelta
from collections import defaultdict

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    'symbol': 'ADAUSDT',
    'timeframe': '4h',          # 15m, 1h, 4h
    'start_date': '2023-01-01', # Desde cuándo descargar
    'end_date': None,           # None = hasta hoy
    'capital_mxn': 10000,
    'tc': 17.5,                 # Tipo de cambio USD/MXN
    'fng_simulado': True,       # True = simula F&G, False = usa API real
}

# Estrategias configurables (para optimización)
ESTRATEGIAS = {
    'long': {
        'rsi_umbral': 30,
        'rsi_cruce': True,      # True = espera cruce hacia arriba
        'objetivo_pct': 5.0,
        'stop_pct': 7.0,
        'max_bars': 36,         # Máximo velas en trade (4h=6días)
        'trailing': True,
        'trailing_pct': 2.0,
        'apalancamiento': 8,
        'comision': 0.001,
        'fng_min': 25,
        'fng_max': 100,
        'btc_filtro': False,    # True = requiere condición BTC
    },
    'short': {
        'rsi_min': 72,
        'objetivo_pct': 5.0,
        'stop_pct': 4.0,
        'max_bars': 36,
        'trailing': True,
        'trailing_pct': 1.5,
        'apalancamiento': 8,
        'comision': 0.0005,
        'fng_min': 40,
        'fng_max': 100,
    },
    'scalping': {
        'rsi_umbral': 30,
        'rsi_cruce': True,
        'objetivo_pct': 1.0,
        'stop_pct': 2.0,
        'max_bars': 4,          # 4 velas = 1 hora en 15m, 16h en 4h
        'trailing': False,
        'apalancamiento': 4,
        'comision': 0.001,
        'fng_min': 15,
        'fng_max': 100,
        'vwap_salida': True,
        'wr_salida': True,
        'wr_umbral': -20,
    }
}

# ═══════════════════════════════════════════════════════════════
# DESCARGA DE DATOS (Binance Futures)
# ═══════════════════════════════════════════════════════════════
def descargar_velas_historicas(symbol, interval, start_str, end_str=None):
    """
    Descarga velas históricas de Binance Futures en chunks de 1000.
    Retorna lista de dicts con: ts, open, high, low, close, vol
    """
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    
    # Convertir fechas a timestamps
    start_ts = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp() * 1000)
    if end_str:
        end_ts = int(datetime.strptime(end_str, '%Y-%m-%d').timestamp() * 1000)
    else:
        end_ts = int(datetime.now().timestamp() * 1000)
    
    all_velas = []
    current_ts = start_ts
    
    print(f"📥 Descargando {symbol} {interval} desde {start_str}...")
    
    while current_ts < end_ts:
        url = f"{url_base}?symbol={symbol}&interval={interval}&startTime={current_ts}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data:
                    break
                
                for v in data:
                    all_velas.append({
                        'ts': int(v[0]),
                        'open': float(v[1]),
                        'high': float(v[2]),
                        'low': float(v[3]),
                        'close': float(v[4]),
                        'vol': float(v[5]),
                    })
                
                current_ts = data[-1][0] + 1  # Siguiente vela
                print(f"  ↳ {len(all_velas)} velas descargadas...")
                time.sleep(0.2)  # Rate limit friendly
                
        except Exception as e:
            print(f"⚠️ Error descargando: {e}")
            time.sleep(2)
            continue
    
    print(f"✅ Total descargado: {len(all_velas)} velas")
    return all_velas

# ═══════════════════════════════════════════════════════════════
# INDICADORES TÉCNICOS (CORREGIDOS)
# ═══════════════════════════════════════════════════════════════
def _ema(vals, span):
    k = 2 / (span + 1)
    e = [vals[0]]
    for v in vals[1:]:
        e.append(v * k + e[-1] * (1 - k))
    return e

def calc_rsi(velas, periodo=14):
    """RSI corregido — usa el periodo pasado como parámetro."""
    closes = [v['close'] for v in velas]
    diffs = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    
    if len(diffs) < periodo:
        return [None] * len(velas)
    
    # Wilder's smoothing (RMA)
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
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))
    
    # Rellenar velas con RSI
    for i, v in enumerate(velas):
        v['rsi'] = rsi_values[i] if i < len(rsi_values) else None
        v['rsi_prev'] = rsi_values[i-1] if i > 0 and i-1 < len(rsi_values) else None
    
    return velas

def calc_vwap(velas):
    cpv = cv = 0
    for v in velas:
        tp = (v['high'] + v['low'] + v['close']) / 3
        cpv += tp * v['vol']
        cv += v['vol']
        v['vwap'] = cpv / cv if cv > 0 else v['close']
    return velas

def calc_williams_r(velas, periodo=14):
    n = len(velas)
    for i in range(n):
        if i < periodo - 1:
            velas[i]['wr'] = None
            continue
        h = max(v['high'] for v in velas[i-periodo+1:i+1])
        l = min(v['low'] for v in velas[i-periodo+1:i+1])
        c = velas[i]['close']
        velas[i]['wr'] = -100 * (h - c) / (h - l) if h != l else -50
    return velas

def calc_volma(velas, periodo=20):
    vols = [v['vol'] for v in velas]
    for i in range(len(velas)):
        velas[i]['volma'] = sum(vols[max(0, i-periodo+1):i+1]) / min(periodo, i+1)
    return velas

def calc_supertrend(velas, periodo=7, mult=2.0):
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
    calc_rsi(velas, periodo=14)  # ← CORREGIDO: usa 14, no 27
    calc_vwap(velas)
    calc_williams_r(velas)
    calc_volma(velas)
    calc_supertrend(velas)
    return velas

# ═══════════════════════════════════════════════════════════════
# SIMULADOR F&G (si no hay API real)
# ═══════════════════════════════════════════════════════════════
def simular_fng(velas, idx):
    """
    Simula Fear & Greed basado en RSI y tendencia reciente.
    No es perfecto, pero permite backtesting histórico.
    """
    v = velas[idx]
    rsi = v.get('rsi', 50)
    
    # Calcular tendencia de 20 velas
    if idx >= 20:
        cambio = (v['close'] - velas[idx-20]['close']) / velas[idx-20]['close'] * 100
    else:
        cambio = 0
    
    # F&G simulado: 0-100
    fng = 50
    fng += (rsi - 50) * 0.8        # RSI influye
    fng += cambio * 2               # Tendencia influye
    
    # Ajustar por volatilidad reciente
    if idx >= 10:
        highs = [velas[i]['high'] for i in range(idx-10, idx+1)]
        lows = [velas[i]['low'] for i in range(idx-10, idx+1)]
        volat = (max(highs) - min(lows)) / min(lows) * 100
        if volat > 15:
            fng -= 10  # Miedo en alta volatilidad
    
    return max(0, min(100, int(fng)))

# ═══════════════════════════════════════════════════════════════
# ESTRATEGIAS
# ═══════════════════════════════════════════════════════════════
def señal_entrada(tipo, velas, idx, cfg_override=None):
    """Evalúa si hay señal de entrada en la vela idx."""
    c = cfg_override or ESTRATEGIAS[tipo]
    v = velas[idx]
    v_prev = velas[idx-1] if idx > 0 else v
    
    # Simular F&G
    fng = simular_fng(velas, idx)
    
    # Filtros globales
    if fng < c.get('fng_min', 0):
        return False
    if fng > c.get('fng_max', 100):
        return False
    
    rsi = v.get('rsi', 50)
    rsi_prev = v_prev.get('rsi', 50)
    
    if tipo == 'long':
        if c.get('rsi_cruce', True):
            return rsi_prev < c['rsi_umbral'] and rsi >= c['rsi_umbral']
        else:
            return rsi < c['rsi_umbral']
    
    elif tipo == 'short':
        return rsi >= c['rsi_min']
    
    elif tipo == 'scalping':
        if v.get('supertrend') == 'bajista':
            return False
        if c.get('rsi_cruce', True):
            return rsi_prev < c['rsi_umbral'] and rsi >= c['rsi_umbral']
        else:
            return rsi < c['rsi_umbral']
    
    return False

def evaluar_salida(tipo, trade, velas, idx, c):
    """Evalúa si debe salir del trade. Retorna (debe_salir, razon)."""
    v = velas[idx]
    pe = trade['precio_entrada']
    precio = v['close']
    
    # Calcular P&L actual
    if tipo in ('long', 'scalping'):
        pnl = (precio - pe) / pe * 100
    else:
        pnl = (pe - precio) / pe * 100
    
    # Actualizar max/min
    trade['precio_max'] = max(trade.get('precio_max', pe), precio)
    trade['precio_min'] = min(trade.get('precio_min', pe), precio)
    pmax = trade['precio_max']
    pmin = trade['precio_min']
    
    # Stop loss
    if tipo in ('long', 'scalping'):
        if precio <= pe * (1 - c['stop_pct']/100):
            return True, "stop_loss"
    else:
        if precio >= pe * (1 + c['stop_pct']/100):
            return True, "stop_loss"
    
    # Objetivo sin trailing
    if not c.get('trailing', False):
        if tipo in ('long', 'scalping'):
            if precio >= pe * (1 + c['objetivo_pct']/100):
                return True, "objetivo"
        else:
            if precio <= pe * (1 - c['objetivo_pct']/100):
                return True, "objetivo"
    
    # Trailing stop
    if c.get('trailing', False):
        if tipo in ('long', 'scalping'):
            if pmax >= pe * (1 + c['objetivo_pct']/100):
                if (pmax - precio) / pmax * 100 >= c['trailing_pct']:
                    return True, "trailing"
        else:
            if pmin <= pe * (1 - c['objetivo_pct']/100):
                if (precio - pmin) / pmin * 100 >= c['trailing_pct']:
                    return True, "trailing"
    
    # Salidas inteligentes scalping
    if tipo == 'scalping' and pnl > 0.2:
        if c.get('vwap_salida') and v.get('vwap') and precio < v['vwap']:
            return True, "vwap"
        if c.get('wr_salida') and v.get('wr') and v['wr'] > c['wr_umbral']:
            return True, "williams_r"
    
    # Tiempo máximo
    bars_en_trade = idx - trade['idx_entrada']
    if bars_en_trade >= c['max_bars']:
        return True, "tiempo_maximo"
    
    return False, None

# ═══════════════════════════════════════════════════════════════
# MOTOR DE BACKTESTING
# ═══════════════════════════════════════════════════════════════
def ejecutar_backtest(velas, estrategias_a_probar=None):
    """
    Ejecuta backtest sobre las velas históricas.
    Retorna dict con resultados detallados.
    """
    if estrategias_a_probar is None:
        estrategias_a_probar = ['long', 'short', 'scalping']
    
    capital_mxn = CONFIG['capital_mxn']
    tc = CONFIG['tc']
    
    resultados = {
        'trades': [],
        'por_tipo': defaultdict(lambda: {'trades': 0, 'ganados': 0, 'ganancia_mxn': 0}),
    }
    
    en_trade = False
    trade_actual = None
    tipo_actual = None
    cfg_actual = None
    
    # Empezar desde la vela 50 para tener indicadores válidos
    for i in range(50, len(velas)):
        v = velas[i]
        
        # Si estamos en trade, evaluar salida
        if en_trade and trade_actual:
            debe_salir, razon = evaluar_salida(tipo_actual, trade_actual, velas, i, cfg_actual)
            
            if debe_salir:
                precio_salida = v['close']
                pe = trade_actual['precio_entrada']
                
                # Calcular P&L bruto
                if tipo_actual in ('long', 'scalping'):
                    pnl_bruto = (precio_salida - pe) / pe * 100
                else:
                    pnl_bruto = (pe - precio_salida) / pe * 100
                
                # Aplicar comisiones (entrada + salida)
                comision_total = cfg_actual['comision'] * 2 * 100
                pnl_neto = pnl_bruto - comision_total
                
                # Calcular ganancia en MXN
                cap_ef_usd = capital_mxn / tc * cfg_actual['apalancamiento']
                ganancia_usd = cap_ef_usd * pnl_neto / 100
                ganancia_mxn = ganancia_usd * tc
                
                trade_result = {
                    'tipo': tipo_actual,
                    'precio_entrada': pe,
                    'precio_salida': precio_salida,
                    'fecha_entrada': trade_actual['fecha_entrada'],
                    'fecha_salida': datetime.fromtimestamp(v['ts']/1000).isoformat(),
                    'razon_salida': razon,
                    'pnl_pct': pnl_neto,
                    'ganancia_mxn': ganancia_mxn,
                    'ganador': pnl_neto > 0,
                    'bars': i - trade_actual['idx_entrada'],
                    'apalancamiento': cfg_actual['apalancamiento'],
                }
                
                resultados['trades'].append(trade_result)
                resultados['por_tipo'][tipo_actual]['trades'] += 1
                resultados['por_tipo'][tipo_actual]['ganancia_mxn'] += ganancia_mxn
                if pnl_neto > 0:
                    resultados['por_tipo'][tipo_actual]['ganados'] += 1
                
                en_trade = False
                trade_actual = None
                tipo_actual = None
                cfg_actual = None
        
        # Si no estamos en trade, buscar entrada
        if not en_trade:
            for tipo in estrategias_a_probar:
                c = ESTRATEGIAS[tipo]
                if señal_entrada(tipo, velas, i, c):
                    trade_actual = {
                        'precio_entrada': v['close'],
                        'precio_max': v['close'],
                        'precio_min': v['close'],
                        'fecha_entrada': datetime.fromtimestamp(v['ts']/1000).isoformat(),
                        'idx_entrada': i,
                    }
                    tipo_actual = tipo
                    cfg_actual = c
                    en_trade = True
                    break  # Solo una entrada por vela
    
    return resultados

# ═══════════════════════════════════════════════════════════════
# MÉTRICAS Y REPORTE
# ═══════════════════════════════════════════════════════════════
def calcular_metricas(resultados, capital_inicial=10000):
    trades = resultados['trades']
    n = len(trades)
    
    if n == 0:
        return {"error": "No se ejecutaron trades"}
    
    ganancias = [t['ganancia_mxn'] for t in trades]
    ganancias_pos = [g for g in ganancias if g > 0]
    ganancias_neg = [g for g in ganancias if g <= 0]
    
    # Balance acumulado
    balance = capital_inicial
    balances = [capital_inicial]
    for g in ganancias:
        balance += g
        balances.append(balance)
    
    # Drawdown
    max_balance = capital_inicial
    max_drawdown = 0
    for b in balances:
        if b > max_balance:
            max_balance = b
        dd = (max_balance - b) / max_balance * 100
        if dd > max_drawdown:
            max_drawdown = dd
    
    # Métricas
    ganados = sum(1 for t in trades if t['ganador'])
    perdidos = n - ganados
    
    profit_factor = abs(sum(ganancias_pos) / sum(ganancias_neg)) if ganancias_neg else float('inf')
    
    return {
        'total_trades': n,
        'ganados': ganados,
        'perdidos': perdidos,
        'win_rate': ganados / n * 100,
        'profit_factor': profit_factor,
        'ganancia_total_mxn': sum(ganancias),
        'balance_final': balance,
        'roi_pct': (balance - capital_inicial) / capital_inicial * 100,
        'max_drawdown_pct': max_drawdown,
        'ganancia_promedio_mxn': sum(ganancias) / n,
        'ganancia_maxima_mxn': max(ganancias) if ganancias else 0,
        'perdida_maxima_mxn': min(ganancias) if ganancias else 0,
        'por_tipo': dict(resultados['por_tipo']),
    }

def imprimir_reporte(metricas):
    print("\n" + "="*60)
    print("📊 RESULTADOS DEL BACKTEST")
    print("="*60)
    
    if 'error' in metricas:
        print(f"❌ {metricas['error']}")
        return
    
    print(f"\n📈 Trades totales:     {metricas['total_trades']}")
    print(f"✅ Ganados:            {metricas['ganados']} ({metricas['win_rate']:.1f}%)")
    print(f"🔴 Perdidos:           {metricas['perdidos']}")
    print(f"💰 Ganancia total:     ${metricas['ganancia_total_mxn']:,.2f} MXN")
    print(f"📊 Balance final:      ${metricas['balance_final']:,.2f} MXN")
    print(f"📈 ROI:                {metricas['roi_pct']:+.2f}%")
    print(f"📉 Max Drawdown:       {metricas['max_drawdown_pct']:.2f}%")
    print(f"⚖️ Profit Factor:      {metricas['profit_factor']:.2f}")
    print(f"💵 Ganancia promedio:  ${metricas['ganancia_promedio_mxn']:,.2f} MXN")
    print(f"🚀 Mejor trade:        ${metricas['ganancia_maxima_mxn']:,.2f} MXN")
    print(f"💥 Peor trade:         ${metricas['perdida_maxima_mxn']:,.2f} MXN")
    
    print(f"\n📋 Por estrategia:")
    for tipo, data in metricas['por_tipo'].items():
        wr = data['ganados']/data['trades']*100 if data['trades'] > 0 else 0
        print(f"  {tipo.upper():10} | Trades: {data['trades']:3} | WR: {wr:5.1f}% | P&L: ${data['ganancia_mxn']:,.2f}")
    
    print("="*60)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Descargar datos
    velas = descargar_velas_historicas(
        CONFIG['symbol'],
        CONFIG['timeframe'],
        CONFIG['start_date'],
        CONFIG['end_date']
    )
    
    if not velas:
        print("❌ No se pudieron descargar datos")
        exit(1)
    
    # Calcular indicadores
    print("🔧 Calculando indicadores...")
    velas = calc_todos(velas)
    
    # Ejecutar backtest
    print("🧪 Ejecutando backtest...")
    resultados = ejecutar_backtest(velas)
    
    # Métricas
    metricas = calcular_metricas(resultados, CONFIG['capital_mxn'])
    imprimir_reporte(metricas)
    
    # Guardar trades a JSON
    import json
    with open('/mnt/Datos/Script/DOT_Bot/logs/backtest_resultados.json', 'w') as f:
        json.dump({
            'config': CONFIG,
            'estrategias': ESTRATEGIAS,
            'metricas': metricas,
            'trades': resultados['trades'],
        }, f, indent=2, default=str)
    
    print("\n💾 Resultados guardados en logs/backtest_resultados.json")
