#!/usr/bin/env python3
"""
scalping_v2.py — 3 estrategias reales de scalpers profesionales, en 15M
1) EMA 9/21 cruce (momentum puro)
2) VWAP bounce + RSI confluencia (objetivo pequeño 0.25-0.5%)
3) Liquidity sweep (mecha rompe máx/mín reciente y regresa — reversión)
Descarga en vivo, sin cache. Train/val obligatorio.
"""
import urllib.request, json, time, random
from datetime import datetime

CONFIG = {'symbol':'ADAUSDT','timeframe':'15m','dias_historia':365,
          'capital_mxn':10000,'tc':17.5}
SPLIT_PCT = 0.70
MAX_COMBOS_POR_ESTRATEGIA = 1500

def descargar_vivo(symbol, interval, dias):
    ms_totales = dias*24*3600*1000
    end_ts = int(datetime.now().timestamp()*1000); start_ts = end_ts-ms_totales
    velas=[]; current=start_ts
    while current < end_ts:
        url=f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&startTime={current}&limit=1000"
        req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req,timeout=30) as r:
                data=json.loads(r.read())
                if not data: break
                for v in data:
                    velas.append({'ts':int(v[0]),'open':float(v[1]),'high':float(v[2]),
                                  'low':float(v[3]),'close':float(v[4]),'vol':float(v[5])})
                current=data[-1][0]+1; time.sleep(0.15)
        except Exception as e:
            print(f"⚠️ {e}"); time.sleep(2)
    return velas

def _ema(vals,span):
    k=2/(span+1); e=[vals[0]]
    for v in vals[1:]: e.append(v*k+e[-1]*(1-k))
    return e

def calc_ema_field(velas, span, nombre):
    vals=_ema([v['close'] for v in velas], span)
    for i,v in enumerate(velas): v[nombre]=vals[i]

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

def calc_vwap_rolling(velas, ventana=96):
    for i in range(len(velas)):
        ini=max(0,i-ventana); sub=velas[ini:i+1]
        cpv=sum(((v['high']+v['low']+v['close'])/3)*v['vol'] for v in sub)
        cv=sum(v['vol'] for v in sub)
        velas[i]['vwap']=cpv/cv if cv>0 else velas[i]['close']

def calc_vol_ma(velas, periodo=20):
    for i in range(len(velas)):
        if i<periodo: velas[i]['volma']=None; continue
        velas[i]['volma']=sum(v['vol'] for v in velas[i-periodo:i])/periodo

def racha_max(trades):
    mx=r=0
    for t in trades:
        if not t['ganador']: r+=1; mx=max(mx,r)
        else: r=0
    return mx

def drawdown_pct(trades, cap_ef):
    equity=cap_ef; pico=equity; dd=0; liq=False
    for t in trades:
        equity+=t['gmxn']
        if equity<=0: liq=True; equity=0.01
        pico=max(pico,equity); dd=max(dd,(pico-equity)/pico*100 if pico>0 else 100)
    return dd, liq

def evaluar(trades, capital_mxn, apal):
    n=len(trades)
    if n==0: return None
    ganados=sum(1 for t in trades if t['ganador'])
    pnl=sum(t['gmxn'] for t in trades)
    dd,liq=drawdown_pct(trades, capital_mxn*apal)
    return {'trades':n,'wr':ganados/n*100,'pnl':pnl,'roi':pnl/capital_mxn*100,
            'racha':racha_max(trades),'dd':dd,'liquidado':liq}

def score(train,val):
    if not train or not val: return -1e9
    if train.get('liquidado') or val.get('liquidado'): return -1e9
    if val['trades']<10: return -1e9
    if val['roi']<=0: return -1e9
    if val['wr']<40: return -1e9
    if val['dd']>50: return -1e9
    s = val['roi']*3 + val['wr']*2 - val['dd']*1.5 - val['racha']*10 + min(val['trades'],40)*2
    consist = max(0.2, min(val['roi']/train['roi'] if train['roi']>0 else 0.3, 1.3))
    return s*consist

def cerrar(trades, tipo, precio, pe, capital_mxn, tc, apal, razon):
    pnl=(precio-pe)/pe*100 if tipo=='long' else (pe-precio)/pe*100
    pnl-=0.001*2*100
    cap_ef=capital_mxn/tc*apal
    gmxn=cap_ef*pnl/100*tc
    trades.append({'tipo':tipo,'pnl':pnl,'gmxn':gmxn,'ganador':pnl>0,'razon':razon})

# ═══════════════════════════════════════════════════ ESTRATEGIA 1: EMA 9/21
def backtest_ema(velas, c, idx_ini, idx_fin, capital_mxn, tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
        if en_trade and trade:
            v=velas[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; obj=trade['objetivo']
            bars=i-trade['idx_entrada']; salir,razon=False,None
            if tipo=='long' and precio<=stop: salir,razon=True,'stop'
            elif tipo=='short' and precio>=stop: salir,razon=True,'stop'
            elif tipo=='long' and precio>=obj: salir,razon=True,'objetivo'
            elif tipo=='short' and precio<=obj: salir,razon=True,'objetivo'
            elif bars>=c['max_bars']: salir,razon=True,'tiempo'
            if salir:
                cerrar(trades, tipo, precio, pe, capital_mxn, tc, c['apalancamiento'], razon)
                en_trade=False; trade=None
        if not en_trade and i>=30:
            v=velas[i]; v_prev=velas[i-1]
            ef,es=v.get(f"ema{c['ema_fast']}"),v.get(f"ema{c['ema_slow']}")
            efp,esp=v_prev.get(f"ema{c['ema_fast']}"),v_prev.get(f"ema{c['ema_slow']}")
            if None in (ef,es,efp,esp): continue
            precio=v['close']
            if efp<=esp and ef>es:  # cruce alcista
                stop=precio*(1-c['stop_pct']/100); obj=precio*(1+c['objetivo_pct']/100)
                trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True; continue
            if efp>=esp and ef<es:  # cruce bajista
                stop=precio*(1+c['stop_pct']/100); obj=precio*(1-c['objetivo_pct']/100)
                trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True
    return trades

# ═══════════════════════════════════════════════════ ESTRATEGIA 2: VWAP bounce
def backtest_vwap(velas, c, idx_ini, idx_fin, capital_mxn, tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
        if en_trade and trade:
            v=velas[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; obj=trade['objetivo']
            bars=i-trade['idx_entrada']; salir,razon=False,None
            if tipo=='long' and precio<=stop: salir,razon=True,'stop'
            elif tipo=='short' and precio>=stop: salir,razon=True,'stop'
            elif tipo=='long' and precio>=obj: salir,razon=True,'objetivo'
            elif tipo=='short' and precio<=obj: salir,razon=True,'objetivo'
            elif bars>=c['max_bars']: salir,razon=True,'tiempo'
            if salir:
                cerrar(trades, tipo, precio, pe, capital_mxn, tc, c['apalancamiento'], razon)
                en_trade=False; trade=None
        if not en_trade and i>=30:
            v=velas[i]; v_prev=velas[i-1]
            vwap=v.get('vwap'); rsi=v.get('rsi'); rsi_prev=v_prev.get('rsi')
            if vwap is None or rsi is None: continue
            precio=v['close']; precio_prev=v_prev['close']; vwap_prev=v_prev.get('vwap',vwap)
            dist_pct=(precio-vwap)/vwap*100
            # bounce alcista: precio estaba bajo VWAP, cruza hacia arriba + RSI bajo
            if precio_prev<vwap_prev and precio>=vwap and rsi<c['rsi_max']:
                stop=precio*(1-c['stop_pct']/100); obj=precio*(1+c['objetivo_pct']/100)
                trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True; continue
            if precio_prev>vwap_prev and precio<=vwap and rsi>c['rsi_min']:
                stop=precio*(1+c['stop_pct']/100); obj=precio*(1-c['objetivo_pct']/100)
                trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True
    return trades

# ═══════════════════════════════════════════════════ ESTRATEGIA 3: Liquidity sweep
def backtest_sweep(velas, c, idx_ini, idx_fin, capital_mxn, tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
        if en_trade and trade:
            v=velas[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; obj=trade['objetivo']
            bars=i-trade['idx_entrada']; salir,razon=False,None
            if tipo=='long' and precio<=stop: salir,razon=True,'stop'
            elif tipo=='short' and precio>=stop: salir,razon=True,'stop'
            elif tipo=='long' and precio>=obj: salir,razon=True,'objetivo'
            elif tipo=='short' and precio<=obj: salir,razon=True,'objetivo'
            elif bars>=c['max_bars']: salir,razon=True,'tiempo'
            if salir:
                cerrar(trades, tipo, precio, pe, capital_mxn, tc, c['apalancamiento'], razon)
                en_trade=False; trade=None
        if not en_trade and i>=c['lookback']+2:
            v=velas[i]; ventana=velas[i-c['lookback']:i]
            min_reciente=min(x['low'] for x in ventana)
            max_reciente=max(x['high'] for x in ventana)
            cuerpo=abs(v['close']-v['open']); rango=v['high']-v['low']
            if rango<=0: continue
            mecha_inf=(min(v['open'],v['close'])-v['low'])
            mecha_sup=(v['high']-max(v['open'],v['close']))
            vol_ok = v.get('volma') is None or v['vol']>=v['volma']*c['vol_mult']
            # Sweep alcista: mecha rompe mínimo reciente y cierra recuperando (rechazo)
            if v['low']<min_reciente and mecha_inf>=cuerpo*c['mecha_ratio'] and v['close']>v['open'] and vol_ok:
                precio=v['close']
                stop=v['low']*(1-0.05/100)  # justo bajo la mecha
                riesgo=precio-stop
                obj=precio+riesgo*c['rr']
                trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True; continue
            if v['high']>max_reciente and mecha_sup>=cuerpo*c['mecha_ratio'] and v['close']<v['open'] and vol_ok:
                precio=v['close']
                stop=v['high']*(1+0.05/100)
                riesgo=stop-precio
                obj=precio-riesgo*c['rr']
                trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True
    return trades

def generar_combos(grid, n, seed):
    random.seed(seed); keys=list(grid.keys()); vistos=set(); combos=[]; intentos=0
    while len(combos)<n and intentos<n*5:
        intentos+=1
        combo=tuple(random.choice(grid[k]) for k in keys)
        if combo in vistos: continue
        vistos.add(combo); combos.append(dict(zip(keys,combo)))
    return combos

def correr_estrategia(nombre, backtest_fn, grid, velas, idx_split, n, capital_mxn, tc, seed):
    print(f"\n{'='*70}\n⚡ {nombre}\n{'='*70}")
    combos = generar_combos(grid, MAX_COMBOS_POR_ESTRATEGIA, seed)
    resultados=[]
    for c in combos:
        try:
            t_train=backtest_fn(velas, c, 30, idx_split, capital_mxn, tc)
            t_val=backtest_fn(velas, c, idx_split, n, capital_mxn, tc)
            ev_t=evaluar(t_train, capital_mxn, c['apalancamiento'])
            ev_v=evaluar(t_val, capital_mxn, c['apalancamiento'])
            sc=score(ev_t, ev_v)
            if sc>-1e9: resultados.append({'params':c,'score':sc,'train':ev_t,'val':ev_v})
        except Exception: pass
    resultados.sort(key=lambda x:x['score'], reverse=True)
    print(f"Válidas: {len(resultados)} de {len(combos)}")
    for i,r in enumerate(resultados[:5],1):
        p=r['params']; t=r['train']; v=r['val']
        print(f"\n#{i} Score:{r['score']:.0f}")
        print(f"  TRAIN: {t['trades']}tr WR:{t['wr']:.0f}% ROI:{t['roi']:+.0f}% Racha:{t['racha']} DD:{t['dd']:.0f}%")
        print(f"  VAL:   {v['trades']}tr WR:{v['wr']:.0f}% ROI:{v['roi']:+.0f}% Racha:{v['racha']} DD:{v['dd']:.0f}%")
        print(f"  Params: {p}")
    return resultados

# ══ MAIN ══
print("📥 Descargando datos (1 año, en vivo, se reutiliza para las 3 estrategias)...")
velas = descargar_vivo(CONFIG['symbol'], CONFIG['timeframe'], CONFIG['dias_historia'])
print(f"✅ {len(velas)} velas")

print("🔧 Indicadores base...")
calc_vwap_rolling(velas)
calc_rsi(velas, 14)
calc_vol_ma(velas, 20)
for span in [9,21,50]: calc_ema_field(velas, span, f'ema{span}')

n=len(velas); idx_split=int(n*SPLIT_PCT)
print(f"📊 Train: {(velas[idx_split]['ts']-velas[0]['ts'])/(1000*3600*24):.0f}d | "
      f"Val: {(velas[-1]['ts']-velas[idx_split]['ts'])/(1000*3600*24):.0f}d\n")

GRID_EMA = {
    'ema_fast':[9], 'ema_slow':[21,50],
    'objetivo_pct':[0.3,0.5,0.8,1.0], 'stop_pct':[0.3,0.5,0.8],
    'max_bars':[4,8,16,24], 'apalancamiento':[2,3,4,5],
}
GRID_VWAP = {
    'rsi_max':[35,40,45], 'rsi_min':[55,60,65],
    'objetivo_pct':[0.25,0.4,0.5,0.8], 'stop_pct':[0.3,0.5,0.8],
    'max_bars':[4,8,12,16], 'apalancamiento':[2,3,4,5],
}
GRID_SWEEP = {
    'lookback':[8,12,16,24], 'mecha_ratio':[1.0,1.5,2.0],
    'vol_mult':[1.0,1.3,1.5], 'rr':[1.5,2.0,2.5,3.0],
    'max_bars':[6,10,16], 'apalancamiento':[2,3,4,5],
}

r1 = correr_estrategia("1) EMA 9/21 CRUCE (momentum)", backtest_ema, GRID_EMA, velas, idx_split, n, CONFIG['capital_mxn'], CONFIG['tc'], 11)
r2 = correr_estrategia("2) VWAP BOUNCE + RSI", backtest_vwap, GRID_VWAP, velas, idx_split, n, CONFIG['capital_mxn'], CONFIG['tc'], 22)
r3 = correr_estrategia("3) LIQUIDITY SWEEP (mecha + reversión)", backtest_sweep, GRID_SWEEP, velas, idx_split, n, CONFIG['capital_mxn'], CONFIG['tc'], 33)

print(f"\n{'='*70}\n💡 Nada se guardó en disco. Compara los TOP 5 de cada estrategia arriba.")
print(f"{'='*70}")
