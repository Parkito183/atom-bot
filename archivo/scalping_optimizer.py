#!/usr/bin/env python3
"""
scalping_optimizer.py — Motor SCALPING 15M: RSI + Bollinger Bands + VWAP
Descarga en vivo (sin cache). Train/val split obligatorio. Objetivos pequeños (0.5-1.5%).
"""
import urllib.request, json, time, random
from datetime import datetime

CONFIG = {'symbol':'ADAUSDT','timeframe':'15m','dias_historia':365,
          'capital_mxn':10000,'tc':17.5}
SPLIT_PCT = 0.70
MAX_COMBOS = 4000

GRID = {
    'bb_periodo':      [14, 20, 26],
    'bb_mult':         [1.5, 2.0, 2.5],
    'rsi_periodo':     [7, 14, 21],
    'rsi_long_max':    [30, 35, 40],      # entra si RSI sube y estaba bajo esto
    'rsi_short_min':   [60, 65, 70],
    'objetivo_pct':    [0.8, 1.0, 1.5, 2.0],
    'stop_pct':        [0.4, 0.5, 0.6, 0.8],
    'max_bars':        [8, 16, 24, 32],   # velas de 15m: 2h, 4h, 6h, 8h
    'usar_vwap':       [True, False],
    'apalancamiento':  [2, 3, 4, 5],
}

def descargar_vivo(symbol, interval, dias):
    """Descarga en vivo, sin guardar cache — siempre datos frescos."""
    ms_totales = dias*24*3600*1000
    end_ts = int(datetime.now().timestamp()*1000)
    start_ts = end_ts - ms_totales
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

def calc_rsi(velas, periodo):
    closes=[v['close'] for v in velas]
    diffs=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    if len(diffs)<periodo: return
    gains=[max(x,0) for x in diffs]; losses=[max(-x,0) for x in diffs]
    ag=sum(gains[:periodo])/periodo; al=sum(losses[:periodo])/periodo
    rsi=[None]*(periodo+1)
    for i in range(periodo,len(diffs)):
        ag=(ag*(periodo-1)+gains[i])/periodo; al=(al*(periodo-1)+losses[i])/periodo
        rsi.append(100 if al==0 else 100-(100/(1+ag/al)))
    for i,v in enumerate(velas): v[f'rsi_{periodo}']=rsi[i] if i<len(rsi) else None

def calc_bollinger(velas, periodo, mult):
    closes=[v['close'] for v in velas]
    for i in range(len(velas)):
        if i<periodo:
            velas[i][f'bb_up_{periodo}_{mult}']=None
            velas[i][f'bb_lo_{periodo}_{mult}']=None
            continue
        ventana=closes[i-periodo:i]
        media=sum(ventana)/periodo
        var=sum((x-media)**2 for x in ventana)/periodo
        std=var**0.5
        velas[i][f'bb_up_{periodo}_{mult}']=media+mult*std
        velas[i][f'bb_lo_{periodo}_{mult}']=media-mult*std

def calc_vwap_rolling(velas, ventana=96):  # 96 velas de 15m = 24h
    for i in range(len(velas)):
        ini=max(0,i-ventana)
        sub=velas[ini:i+1]
        cpv=sum(((v['high']+v['low']+v['close'])/3)*v['vol'] for v in sub)
        cv=sum(v['vol'] for v in sub)
        velas[i]['vwap']=cpv/cv if cv>0 else velas[i]['close']

def backtest(velas, c, idx_ini, idx_fin, capital_mxn, tc):
    bb_up_k=f"bb_up_{c['bb_periodo']}_{c['bb_mult']}"
    bb_lo_k=f"bb_lo_{c['bb_periodo']}_{c['bb_mult']}"
    rsi_k=f"rsi_{c['rsi_periodo']}"
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
        if en_trade and trade:
            v=velas[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; obj=trade['objetivo']
            bars=i-trade['idx_entrada']
            salir,razon=False,None
            if tipo=='long' and precio<=stop: salir,razon=True,'stop'
            elif tipo=='short' and precio>=stop: salir,razon=True,'stop'
            elif tipo=='long' and precio>=obj: salir,razon=True,'objetivo'
            elif tipo=='short' and precio<=obj: salir,razon=True,'objetivo'
            elif bars>=c['max_bars']: salir,razon=True,'tiempo'
            if salir:
                pnl=(precio-pe)/pe*100 if tipo=='long' else (pe-precio)/pe*100
                pnl-=0.001*2*100  # spot: 0.1%+0.1%
                cap_ef=capital_mxn/tc*c['apalancamiento']
                gmxn=cap_ef*pnl/100*tc
                trades.append({'tipo':tipo,'pnl':pnl,'gmxn':gmxn,'ganador':pnl>0,'razon':razon})
                en_trade=False; trade=None
        if not en_trade and i>=max(c['bb_periodo'],c['rsi_periodo'])+2:
            v=velas[i]; v_prev=velas[i-1]
            rsi=v.get(rsi_k); rsi_prev=v_prev.get(rsi_k)
            bb_lo=v.get(bb_lo_k); bb_up=v.get(bb_up_k)
            if rsi is None or bb_lo is None: continue
            precio=v['close']
            vwap_ok_long = (not c['usar_vwap']) or precio>=v.get('vwap',precio)
            vwap_ok_short = (not c['usar_vwap']) or precio<=v.get('vwap',precio)

            # LONG: precio toca/rompe banda inferior + RSI subiendo desde bajo
            if precio<=bb_lo and rsi_prev is not None and rsi>rsi_prev and rsi<c['rsi_long_max'] and vwap_ok_long:
                stop=precio*(1-c['stop_pct']/100); obj=precio*(1+c['objetivo_pct']/100)
                trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True; continue
            # SHORT: precio toca/rompe banda superior + RSI bajando desde alto
            if precio>=bb_up and rsi_prev is not None and rsi<rsi_prev and rsi>c['rsi_short_min'] and vwap_ok_short:
                stop=precio*(1+c['stop_pct']/100); obj=precio*(1-c['objetivo_pct']/100)
                trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':obj,'idx_entrada':i}
                en_trade=True
    return trades

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

def generar_combos(grid, n, seed=7):
    random.seed(seed); keys=list(grid.keys()); vistos=set(); combos=[]; intentos=0
    while len(combos)<n and intentos<n*5:
        intentos+=1
        combo=tuple(random.choice(grid[k]) for k in keys)
        if combo in vistos: continue
        vistos.add(combo); combos.append(dict(zip(keys,combo)))
    return combos

print("="*70)
print("⚡ SCALPING OPTIMIZER — RSI + Bollinger + VWAP — 15M — sin cache")
print("="*70)
print(f"\n📥 Descargando {CONFIG['symbol']} {CONFIG['timeframe']} ({CONFIG['dias_historia']} días, en vivo)...")
velas = descargar_vivo(CONFIG['symbol'], CONFIG['timeframe'], CONFIG['dias_historia'])
print(f"✅ {len(velas)} velas descargadas")

print("🔧 Calculando indicadores base...")
calc_vwap_rolling(velas)
periodos_rsi = set(GRID['rsi_periodo'])
for p in periodos_rsi: calc_rsi(velas, p)
for p in GRID['bb_periodo']:
    for m in GRID['bb_mult']: calc_bollinger(velas, p, m)

n=len(velas)
idx_split=int(n*SPLIT_PCT)
horas_train=(velas[idx_split]['ts']-velas[0]['ts'])/(1000*3600)
horas_val=(velas[-1]['ts']-velas[idx_split]['ts'])/(1000*3600)
print(f"📊 Train: {horas_train/24:.1f} días | Validación: {horas_val/24:.1f} días (más reciente)")

combos = generar_combos(GRID, MAX_COMBOS)
print(f"\n🎲 Probando {len(combos)} combinaciones...")

resultados=[]; inicio=time.time()
for idx, c in enumerate(combos):
    try:
        t_train=backtest(velas, c, 30, idx_split, CONFIG['capital_mxn'], CONFIG['tc'])
        t_val=backtest(velas, c, idx_split, n, CONFIG['capital_mxn'], CONFIG['tc'])
        ev_t=evaluar(t_train, CONFIG['capital_mxn'], c['apalancamiento'])
        ev_v=evaluar(t_val, CONFIG['capital_mxn'], c['apalancamiento'])
        sc=score(ev_t, ev_v)
        if sc>-1e9: resultados.append({'params':c,'score':sc,'train':ev_t,'val':ev_v})
    except Exception: pass
    if (idx+1)%200==0:
        eta=(time.time()-inicio)/(idx+1)*(len(combos)-idx-1)
        print(f"  [{idx+1}/{len(combos)}] válidas:{len(resultados)} ETA:{eta/60:.1f}min")

resultados.sort(key=lambda x:x['score'], reverse=True)
print(f"\n{'='*70}\n🏆 TOP 10 SCALPING ({len(resultados)} válidas de {len(combos)})\n{'='*70}")
for i,r in enumerate(resultados[:10],1):
    p=r['params']; t=r['train']; v=r['val']
    print(f"\n#{i} Score:{r['score']:.0f}")
    print(f"  TRAIN: {t['trades']}tr WR:{t['wr']:.0f}% ROI:{t['roi']:+.0f}% Racha:{t['racha']} DD:{t['dd']:.0f}%")
    print(f"  VAL:   {v['trades']}tr WR:{v['wr']:.0f}% ROI:{v['roi']:+.0f}% Racha:{v['racha']} DD:{v['dd']:.0f}%")
    print(f"  BB({p['bb_periodo']},{p['bb_mult']}) RSI({p['rsi_periodo']}):L<{p['rsi_long_max']}/S>{p['rsi_short_min']} "
          f"obj:{p['objetivo_pct']}% stop:{p['stop_pct']}% bars:{p['max_bars']} vwap:{p['usar_vwap']} apal:{p['apalancamiento']}x")

print(f"\n⏱️ Tiempo total: {(time.time()-inicio)/60:.1f} min")
print("💡 Nada se guardó en disco — corre de nuevo cuando quieras datos más frescos.")
