#!/usr/bin/env python3
"""
validador.py — Valida la estrategia ganadora del optimizer
Prueba fuera de muestra (últimos meses) + racha + drawdown
No confía en el ROI total, confía en que se sostenga en el tiempo.
"""
import urllib.request, json, time, os
from datetime import datetime

CONFIG = {
    'symbol_ada': 'ADAUSDT', 'symbol_btc': 'BTCUSDT',
    'timeframe': '4h', 'start_date': '2023-01-01',
    'capital_mxn': 10000, 'tc': 17.5,
}
CACHE_DIR = '/mnt/Datos/Script/DOT_Bot/logs/cache'

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN GANADORA A VALIDAR (del optimizer TOP #1)
# ═══════════════════════════════════════════════════════════════
GANADORA = {
    'stop_atr_mult': 2.0, 'objetivo_atr_mult': 4.0,
    'rsi_long_min': 30, 'rsi_long_max': 70,
    'rsi_short_min': 25, 'rsi_short_max': 60,
    'max_bars': 36, 'trailing': True, 'trailing_atr_mult': 1.0,
    'btc_confirmacion': True, 'btc_emergencia': True,
    'early_exit': False, 'early_exit_bars': 4, 'early_exit_min_advance': 0.5,
    'supertrend_mult': 2.5, 'apalancamiento': 5,
}

def descargar_con_cache(symbol, interval, start_str):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{start_str}.json")
    if os.path.exists(cache_file):
        with open(cache_file, 'r') as f: return json.load(f)
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str,'%Y-%m-%d').timestamp()*1000)
    end_ts = int(datetime.now().timestamp()*1000)
    all_velas=[]; current_ts=start_ts
    while current_ts < end_ts:
        url=f"{url_base}?symbol={symbol}&interval={interval}&startTime={current_ts}&limit=1000"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req,timeout=30) as r:
                data=json.loads(r.read())
                if not data: break
                for v in data:
                    all_velas.append({'ts':int(v[0]),'open':float(v[1]),'high':float(v[2]),
                                      'low':float(v[3]),'close':float(v[4]),'vol':float(v[5])})
                current_ts=data[-1][0]+1; time.sleep(0.15)
        except: time.sleep(2)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_file,'w') as f: json.dump(all_velas,f)
    return all_velas

def _ema(vals, span):
    k=2/(span+1); e=[vals[0]]
    for v in vals[1:]: e.append(v*k+e[-1]*(1-k))
    return e

def calc_rsi(velas, periodo=14):
    closes=[v['close'] for v in velas]
    diffs=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    if len(diffs)<periodo: return
    gains=[max(x,0) for x in diffs]; losses=[max(-x,0) for x in diffs]
    ag=sum(gains[:periodo])/periodo; al=sum(losses[:periodo])/periodo
    rsi=[None]*(periodo+1)
    for i in range(periodo,len(diffs)):
        ag=(ag*(periodo-1)+gains[i])/periodo; al=(al*(periodo-1)+losses[i])/periodo
        rsi.append(100 if al==0 else 100-(100/(1+ag/al)))
    for i,v in enumerate(velas): v['rsi']=rsi[i] if i<len(rsi) else None

def calc_ema(velas, span, nombre):
    vals=_ema([v['close'] for v in velas], span)
    for i,v in enumerate(velas): v[nombre]=vals[i]

def calc_atr(velas, periodo=14):
    n=len(velas)
    if n<2: return
    tr=[velas[0]['high']-velas[0]['low']]
    for i in range(1,n):
        h,l,pc=velas[i]['high'],velas[i]['low'],velas[i-1]['close']
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr=_ema(tr,periodo)
    for i,v in enumerate(velas): v['atr']=atr[i]

def calc_supertrend(velas, periodo=10, mult=3.0):
    n=len(velas)
    if n<2: return
    tr=[velas[0]['high']-velas[0]['low']]
    for i in range(1,n):
        h,l,pc=velas[i]['high'],velas[i]['low'],velas[i-1]['close']
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr=_ema(tr,periodo)
    upper=[((velas[i]['high']+velas[i]['low'])/2)+mult*atr[i] for i in range(n)]
    lower=[((velas[i]['high']+velas[i]['low'])/2)-mult*atr[i] for i in range(n)]
    st=['bajista']*n; stl=[upper[0]]*n
    for i in range(1,n):
        c=velas[i]['close']
        if st[i-1]=='alcista':
            lower[i]=max(lower[i],stl[i-1])
            st[i]='bajista' if c<stl[i-1] else 'alcista'
            stl[i]=upper[i] if st[i]=='bajista' else lower[i]
        else:
            upper[i]=min(upper[i],stl[i-1])
            st[i]='alcista' if c>stl[i-1] else 'bajista'
            stl[i]=lower[i] if st[i]=='alcista' else upper[i]
    for i in range(n): velas[i]['supertrend']=st[i]

def calc_todos_base(velas):
    calc_rsi(velas); calc_ema(velas,9,'ema9'); calc_ema(velas,21,'ema21')
    calc_ema(velas,50,'ema50'); calc_atr(velas)

def detectar_regimen_btc(velas, i):
    v=velas[i]; ema50=v.get('ema50'); st=v.get('supertrend')
    if ema50 is None or st is None: return 'lateral'
    dist=abs(v['close']-ema50)/ema50*100
    if dist<1.5: return 'lateral'
    if st=='alcista' and v['close']>ema50: return 'alcista'
    if st=='bajista' and v['close']<ema50: return 'bajista'
    return 'lateral'

def ejecutar_backtest(ada_velas, btc_velas, c, idx_ini, idx_fin, capital_mxn, tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
        if en_trade and trade:
            v=ada_velas[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; objetivo=trade['objetivo']
            atr=v.get('atr',pe*0.02); bars=i-trade['idx_entrada']
            trade['precio_max']=max(trade.get('precio_max',pe),precio)
            trade['precio_min']=min(trade.get('precio_min',pe),precio)
            debe_salir,razon=False,None
            if tipo=='long' and precio<=stop: debe_salir,razon=True,"stop_loss"
            elif tipo=='short' and precio>=stop: debe_salir,razon=True,"stop_loss"
            elif tipo=='long' and precio>=objetivo: debe_salir,razon=True,"objetivo"
            elif tipo=='short' and precio<=objetivo: debe_salir,razon=True,"objetivo"
            elif c['early_exit'] and bars==c['early_exit_bars']:
                avance=(precio-pe)/pe*100 if tipo=='long' else (pe-precio)/pe*100
                if avance<c['early_exit_min_advance']: debe_salir,razon=True,"early_exit"
            if not debe_salir and c['trailing']:
                if tipo=='long':
                    umbral=pe+(objetivo-pe)*0.5
                    if precio>=umbral and precio<=trade['precio_max']-atr*c['trailing_atr_mult']:
                        debe_salir,razon=True,"trailing"
                else:
                    umbral=pe-(pe-objetivo)*0.5
                    if precio<=umbral and precio>=trade['precio_min']+atr*c['trailing_atr_mult']:
                        debe_salir,razon=True,"trailing"
            if not debe_salir and c['btc_emergencia']:
                btc_reg=detectar_regimen_btc(btc_velas,i)
                btc_entrada=trade.get('btc_regimen','neutral')
                if tipo=='long' and btc_reg=='bajista' and btc_entrada!='bajista': debe_salir,razon=True,"btc_emergencia"
                elif tipo=='short' and btc_reg=='alcista' and btc_entrada!='alcista': debe_salir,razon=True,"btc_emergencia"
            if not debe_salir and bars>=c['max_bars']: debe_salir,razon=True,"tiempo_maximo"
            if debe_salir:
                pnl_bruto=(precio-pe)/pe*100 if tipo=='long' else (pe-precio)/pe*100
                pnl_neto=pnl_bruto-0.0005*2*100
                cap_ef_usd=capital_mxn/tc*c['apalancamiento']
                ganancia_mxn=cap_ef_usd*pnl_neto/100*tc
                trades.append({'ts':v['ts'],'tipo':tipo,'pnl_pct':pnl_neto,
                               'ganancia_mxn':ganancia_mxn,'ganador':pnl_neto>0,'razon':razon})
                en_trade=False; trade=None
        if not en_trade and i>=50:
            v=ada_velas[i]; v_prev=ada_velas[i-1]
            if v.get('rsi') is None or v_prev.get('rsi') is None: continue
            precio=v['close']; atr=v.get('atr',precio*0.02); rsi=v['rsi']
            st_now=v.get('supertrend'); st_prev=v_prev.get('supertrend')
            if atr/precio*100<0.3: continue
            btc_regimen=detectar_regimen_btc(btc_velas,i)
            if st_prev=='bajista' and st_now=='alcista':
                if c['rsi_long_min']<=rsi<=c['rsi_long_max']:
                    if not (c['btc_confirmacion'] and btc_regimen=='bajista'):
                        stop=precio-atr*c['stop_atr_mult']; objetivo=precio+atr*c['objetivo_atr_mult']
                        if (objetivo-precio)/(precio-stop)>=2.0:
                            trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':objetivo,
                                   'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True; continue
            if st_prev=='alcista' and st_now=='bajista':
                if c['rsi_short_min']<=rsi<=c['rsi_short_max']:
                    if not (c['btc_confirmacion'] and btc_regimen=='alcista'):
                        stop=precio+atr*c['stop_atr_mult']; objetivo=precio-atr*c['objetivo_atr_mult']
                        if (precio-objetivo)/(stop-precio)>=2.0:
                            trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':objetivo,
                                   'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True
    return trades

def racha_max_perdidas(trades):
    mx=r=0
    for t in trades:
        if not t['ganador']: r+=1; mx=max(mx,r)
        else: r=0
    return mx

def drawdown_max(trades):
    bal=0; pico=0; dd_max=0; dd_pct_max=0
    for t in trades:
        bal += t['ganancia_mxn']
        pico = max(pico, bal)
        dd = pico - bal
        dd_max = max(dd_max, dd)
        if pico > 0:
            dd_pct_max = max(dd_pct_max, dd/pico*100 if pico>0 else 0)
    return dd_max, dd_pct_max

def reporte(trades, nombre, capital_mxn):
    print(f"\n{'─'*60}")
    print(f"📊 {nombre}")
    print(f"{'─'*60}")
    n=len(trades)
    if n==0:
        print("❌ Sin trades en este período")
        return None
    ganados=sum(1 for t in trades if t['ganador'])
    wr=ganados/n*100
    pnl_total=sum(t['ganancia_mxn'] for t in trades)
    racha=racha_max_perdidas(trades)
    dd_mxn, dd_pct=drawdown_max(trades)
    gan_pos=[t['ganancia_mxn'] for t in trades if t['ganancia_mxn']>0]
    gan_neg=[t['ganancia_mxn'] for t in trades if t['ganancia_mxn']<=0]
    pf=abs(sum(gan_pos)/sum(gan_neg)) if gan_neg else 999

    print(f"Trades:              {n}")
    print(f"Win Rate:            {wr:.1f}%")
    print(f"P&L Total:           ${pnl_total:,.0f} MXN")
    print(f"ROI:                 {pnl_total/capital_mxn*100:+.1f}%")
    print(f"Profit Factor:       {pf:.2f}")
    print(f"Racha máx pérdidas:  {racha} seguidas")
    print(f"Drawdown máximo:     ${dd_mxn:,.0f} MXN ({dd_pct:.1f}% del pico)")

    # Alertas
    if racha >= 6:
        print(f"⚠️  ALERTA: racha de {racha} pérdidas seguidas — riesgo psicológico/margen alto")
    if dd_pct >= 40:
        print(f"⚠️  ALERTA: drawdown de {dd_pct:.0f}% — pudiste haber perdido casi la mitad del balance en el camino")
    if wr < 40:
        print(f"⚠️  ALERTA: WR {wr:.0f}% — pierdes más de 6 de cada 10 trades")

    return {'trades':n,'wr':wr,'pnl_total':pnl_total,'racha':racha,'dd_pct':dd_pct,'pf':pf}

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
print("="*60)
print("🔍 VALIDADOR — Estrategia Ganadora del Optimizer")
print("="*60)
print(f"\nConfiguración a validar:")
for k,v in GANADORA.items(): print(f"   {k}: {v}")

print("\n📥 Cargando datos...")
ada_raw = descargar_con_cache(CONFIG['symbol_ada'], CONFIG['timeframe'], CONFIG['start_date'])
btc_raw = descargar_con_cache(CONFIG['symbol_btc'], CONFIG['timeframe'], CONFIG['start_date'])
ts_comunes = sorted({v['ts'] for v in ada_raw} & {v['ts'] for v in btc_raw})
ada = [dict(v) for v in ada_raw if v['ts'] in ts_comunes]
btc = [dict(v) for v in btc_raw if v['ts'] in ts_comunes]
print(f"✅ {len(ada)} velas alineadas")

calc_todos_base(ada); calc_todos_base(btc)
calc_supertrend(ada, mult=GANADORA['supertrend_mult'])
calc_supertrend(btc, mult=GANADORA['supertrend_mult'])

n = len(ada)
capital_mxn = CONFIG['capital_mxn']
tc = CONFIG['tc']

# 1) TODO EL HISTÓRICO (lo que ya sabíamos)
trades_completo = ejecutar_backtest(ada, btc, GANADORA, 50, n, capital_mxn, tc)
reporte(trades_completo, "PERÍODO COMPLETO (2023-hoy) — lo que ya conocíamos", capital_mxn)

# 2) SOLO ÚLTIMOS 6 MESES (fuera de muestra — el grid no lo "vio" de forma especial)
seis_meses_ms = 6*30*24*3600*1000
ts_corte = ada[-1]['ts'] - seis_meses_ms
idx_corte = next((i for i,v in enumerate(ada) if v['ts']>=ts_corte), n-500)
trades_reciente = ejecutar_backtest(ada, btc, GANADORA, idx_corte, n, capital_mxn, tc)
reporte(trades_reciente, "ÚLTIMOS 6 MESES — validación fuera de muestra", capital_mxn)

# 3) SOLO ÚLTIMOS 3 MESES (más estricto aún)
tres_meses_ms = 3*30*24*3600*1000
ts_corte3 = ada[-1]['ts'] - tres_meses_ms
idx_corte3 = next((i for i,v in enumerate(ada) if v['ts']>=ts_corte3), n-250)
trades_3m = ejecutar_backtest(ada, btc, GANADORA, idx_corte3, n, capital_mxn, tc)
reporte(trades_3m, "ÚLTIMOS 3 MESES — el período más reciente", capital_mxn)

print(f"\n{'='*60}")
print("💡 CONCLUSIÓN")
print(f"{'='*60}")
print("Si el WR y ROI de los últimos 3-6 meses son similares")
print("(o mejores) que el histórico completo → la estrategia")
print("es robusta, no es solo suerte del pasado.")
print("")
print("Si los últimos meses muestran WR mucho más bajo o")
print("pérdidas → el optimizer encontró algo que funcionó")
print("por coincidencia en 2023-2024 pero no se sostiene.")
print(f"{'='*60}")
