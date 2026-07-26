#!/usr/bin/env python3
"""
analisis_correlacion.py — Mide correlación BTC vs ADA con diferentes lags
"""
import urllib.request
import json
import time
from datetime import datetime
import numpy as np

def descargar_velas(symbol, interval, limit=500):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return [{'ts': int(v[0]), 'close': float(v[4])} for v in data]

def calcular_correlacion(btc_velas, ada_velas, max_lag=10):
    """
    Calcula correlación de retornos BTC vs ADA con diferentes lags.
    lag=0: mismo tiempo
    lag=1: BTC t-1 predice ADA t
    lag=2: BTC t-2 predice ADA t
    """
    # Alinear por timestamp
    btc_map = {v['ts']: v['close'] for v in btc_velas}
    ada_map = {v['ts']: v['close'] for v in ada_velas}
    
    ts_comunes = sorted(set(btc_map.keys()) & set(ada_map.keys()))
    
    btc_rets = []
    ada_rets = []
    for i in range(1, len(ts_comunes)):
        btc_rets.append((btc_map[ts_comunes[i]] - btc_map[ts_comunes[i-1]]) / btc_map[ts_comunes[i-1]])
        ada_rets.append((ada_map[ts_comunes[i]] - ada_map[ts_comunes[i-1]]) / ada_map[ts_comunes[i-1]])
    
    print(f"\n📊 Análisis de correlación BTC → ADA ({len(btc_rets)} velas)")
    print("="*60)
    
    mejor_lag = 0
    mejor_corr = 0
    
    for lag in range(max_lag + 1):
        if lag == 0:
            btc_lagged = btc_rets
            ada_target = ada_rets
        else:
            btc_lagged = btc_rets[:-lag]
            ada_target = ada_rets[lag:]
        
        n = min(len(btc_lagged), len(ada_target))
        if n < 10:
            continue
        
        # Correlación de Pearson
        btc_slice = btc_lagged[-n:]
        ada_slice = ada_target[-n:]
        
        corr = np.corrcoef(btc_slice, ada_slice)[0, 1]
        
        # Dirección correcta (BTC sube → ADA sube)
        aciertos = sum(1 for i in range(n) if (btc_slice[i] > 0) == (ada_slice[i] > 0))
        accuracy = aciertos / n * 100
        
        arrow = "🎯" if lag == 0 else "⏱️"
        print(f"{arrow} Lag {lag}: Corr={corr:.3f} | Dirección correcta: {accuracy:.1f}%")
        
        if abs(corr) > abs(mejor_corr):
            mejor_corr = corr
            mejor_lag = lag
    
    print(f"\n🏆 Mejor lag: {mejor_lag} velas (corr={mejor_corr:.3f})")
    return mejor_lag, mejor_corr

if __name__ == "__main__":
    print("📥 Descargando datos de BTC y ADA (4h)...")
    btc = descargar_velas("BTCUSDT", "4h", 500)
    ada = descargar_velas("ADAUSDT", "4h", 500)
    
    calcular_correlacion(btc, ada, max_lag=5)
