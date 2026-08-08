#!/usr/bin/env python3
"""
validar_rank1.py — Prueba final de la configuración RANK #1
en 3 ventanas: completo, últimos 6 meses, últimos 3 meses.
Usa el motor ATR/Supertrend (no el RSI-cruce del bot en vivo).
"""
import urllib.request, json, time, os
from datetime import datetime

CONFIG = {'symbol_ada':'ADAUSDT','symbol_btc':'BTCUSDT','timeframe':'4h',
          'start_date':'2023-01-01','capital_mxn':10000,'tc':17.5}
CACHE_DIR = '/mnt/Datos/Script/DOT_Bot/logs/cache'

GANADORA = {
    'stop_atr_mult':3.0,'objetivo_atr_mult':4.5,'min_rr':1.5,
    'rsi_periodo':21,'rsi_long_min':40,'rsi_long_max':80,
    'rsi_short_min':30,'rsi_short_max':75,
    'max_bars':48,'atr_min_pct':0.5,
    'trailing':False,'trailing_atr_mult':2.0,
    'btc_confirmacion':False,'btc_emergencia':True,
    'early_exit':False,'early_exit_bars':4,'early_exit_min_advance':0.5,
    'supertrend_mult':2.0,'supertrend_periodo':10,
    'apalancamiento':8,
}

def descargar_con_cache(symbol, interval, start_str):
    cache_file=os.path.join(CACHE_DIR,f"{symbol}_{interval}_{start_str}.json")
    if os.path.exists(cache_file):
        with open(cache_file,'r') as f: return json.load(f)
    url_base="https://fapi.binance.com/fapi/v1/klines"
    start_ts=int(datetime.strptime(start_str,'%Y-%m-%d').timestamp()*1000)
    end_ts=int(datetime.now().timestamp()*1000)
    all_velas=[]; current_ts=start_ts
    while current_ts<end_ts:
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
    os.makedirs(CACHE_DIR,exist_ok=True)
    with open(cache_file,'w') as f: json.dump(all_velas,f)
    return all_velas

def _ema(vals,span):
    k=2/(span+1); e=[vals[0]]
    for v in vals[1:]: e.append(v*k+e[-1]*(1-k))
    return e

def calc_rsi(velas,periodo=14):
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

def calc_ema_field(velas,span,nombre):
    vals=_ema([v['close'] for v in velas],span)
    for i,v in enumerate(velas): v[nombre]=vals[i]

def calc_atr(velas,periodo=14):
    n=len(velas)
    if n<2: return
    tr=[velas[0]['high']-velas[0]['low']]
    for i in range(1,n):
        h,l,pc=velas[i]['high'],velas[i]['low'],velas[i-1]['close']
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr=_ema(tr,periodo)
    for i,v in enumerate(velas): v['atr']=atr[i]

def calc_supertrend(velas,periodo=10,mult=3.0):
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

def detectar_regimen_btc(velas,i):
    v=velas[i]; ema50=v.get('ema50'); st=v.get('supertrend')
    if ema50 is None or st is None: return 'lateral'
    dist=abs(v['close']-ema50)/ema50*100
    if dist<1.5: return 'lateral'
    if st=='alcista' and v['close']>ema50: return 'alcista'
    if st=='bajista' and v['close']<ema50: return 'bajista'
    return 'lateral'

def ejecutar_backtest(ada,btc,c,idx_ini,idx_fin,capital_mxn,tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini,idx_fin):
        if en_trade and trade:
            v=ada[i]; precio=v['close']; tipo=trade['tipo']
            pe=trade['precio_entrada']; stop=trade['stop']; objetivo=trade['objetivo']
            atr=v.get('atr',pe*0.02); bars=i-trade['idx_entrada']
            trade['precio_max']=max(trade.get('precio_max',pe),precio)
            trade['precio_min']=min(trade.get('precio_min',pe),precio)
            debe_salir,razon=False,None
            if tipo=='long' and precio<=stop: debe_salir,razon=True,"stop"
            elif tipo=='short' and precio>=stop: debe_salir,razon=True,"stop"
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
                btc_reg=detectar_regimen_btc(btc,i)
                btc_entrada=trade.get('btc_regimen','neutral')
                if tipo=='long' and btc_reg=='bajista' and btc_entrada!='bajista': debe_salir,razon=True,"btc_emerg"
                elif tipo=='short' and btc_reg=='alcista' and btc_entrada!='alcista': debe_salir,razon=True,"btc_emerg"
            if not debe_salir and bars>=c['max_bars']: debe_salir,razon=True,"tiempo"
            if debe_salir:
                pnl_bruto=(precio-pe)/pe*100 if tipo=='long' else (pe-precio)/pe*100
                pnl_neto=pnl_bruto-0.0005*2*100
                cap_ef=capital_mxn/tc*c['apalancamiento']
                gmxn=cap_ef*pnl_neto/100*tc
                trades.append({'ts':v['ts'],'tipo':tipo,'pnl':pnl_neto,'gmxn':gmxn,'ganador':pnl_neto>0,'razon':razon})
                en_trade=False; trade=None
        if not en_trade and i>=50:
            v=ada[i]; v_prev=ada[i-1]
            if v.get('rsi') is None or v_prev.get('rsi') is None: continue
            precio=v['close']; atr=v.get('atr',precio*0.02); rsi=v['rsi']
            st_now=v.get('supertrend'); st_prev=v_prev.get('supertrend')
            if atr/precio*100<c['atr_min_pct']: continue
            btc_regimen=detectar_regimen_btc(btc,i)
            if st_prev=='bajista' and st_now=='alcista':
                if c['rsi_long_min']<=rsi<=c['rsi_long_max']:
                    if not (c['btc_confirmacion'] and btc_regimen=='bajista'):
                        stop=precio-atr*c['stop_atr_mult']; objetivo=precio+atr*c['objetivo_atr_mult']
                        riesgo=precio-stop
                        if riesgo>0 and (objetivo-precio)/riesgo>=c['min_rr']:
                            trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':objetivo,
                                   'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True; continue
            if st_prev=='alcista' and st_now=='bajista':
                if c['rsi_short_min']<=rsi<=c['rsi_short_max']:
                    if not (c['btc_confirmacion'] and btc_regimen=='alcista'):
                        stop=precio+atr*c['stop_atr_mult']; objetivo=precio-atr*c['objetivo_atr_mult']
                        riesgo=stop-precio
                        if riesgo>0 and (precio-objetivo)/riesgo>=c['min_rr']:
                            trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':objetivo,
                                   'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True
    return trades

def racha_max(trades):
    mx=r=0
    for t in trades:
        if not t['ganador']: r+=1; mx=max(mx,r)
        else: r=0
    return mx

def drawdown_pct(trades, capital_efectivo):
    equity=capital_efectivo; pico=equity; dd=0; liquidado=False
    for t in trades:
        equity+=t['gmxn']
        if equity<=0: liquidado=True; equity=0.01
        pico=max(pico,equity)
        dd=max(dd,(pico-equity)/pico*100 if pico>0 else 100)
    return dd, liquidado

def reporte(trades, nombre, capital_mxn, apalancamiento):
    print(f"\n{'─'*60}\n📊 {nombre}\n{'─'*60}")
    n=len(trades)
    if n==0: print("❌ Sin trades"); return
    ganados=sum(1 for t in trades if t['ganador'])
    wr=ganados/n*100
    pnl=sum(t['gmxn'] for t in trades)
    cap_ef=capital_mxn*apalancamiento
    dd,liq=drawdown_pct(trades,cap_ef)
    racha=racha_max(trades)
    print(f"Trades: {n} | WR: {wr:.1f}% | P&L: ${pnl:,.0f} MXN | ROI: {pnl/capital_mxn*100:+.1f}%")
    print(f"Racha máx pérdidas: {racha} | Drawdown: {dd:.1f}%{' ⚠️ LIQUIDADO' if liq else ''}")
    if racha>=6: print("⚠️  Racha larga — riesgo psicológico/margen alto")
    if dd>=50: print("⚠️  Drawdown considerable — mitad del camino en rojo antes de recuperar")
    if wr<40: print("⚠️  WR bajo — pierdes más de 6 de cada 10")

print("="*60)
print("🔍 VALIDACIÓN FINAL — RANK #1 del optimizer")
print("="*60)
for k,v in GANADORA.items(): print(f"   {k}: {v}")

print("\n📥 Cargando datos...")
ada_raw=descargar_con_cache(CONFIG['symbol_ada'],CONFIG['timeframe'],CONFIG['start_date'])
btc_raw=descargar_con_cache(CONFIG['symbol_btc'],CONFIG['timeframe'],CONFIG['start_date'])
ts_comunes=sorted({v['ts'] for v in ada_raw}&{v['ts'] for v in btc_raw})
ada=[dict(v) for v in ada_raw if v['ts'] in ts_comunes]
btc=[dict(v) for v in btc_raw if v['ts'] in ts_comunes]
print(f"✅ {len(ada)} velas alineadas")

calc_ema_field(ada,50,'ema50'); calc_atr(ada)
calc_ema_field(btc,50,'ema50'); calc_atr(btc)
calc_rsi(ada, periodo=GANADORA['rsi_periodo'])
calc_supertrend(ada, periodo=GANADORA['supertrend_periodo'], mult=GANADORA['supertrend_mult'])
calc_supertrend(btc, periodo=GANADORA['supertrend_periodo'], mult=GANADORA['supertrend_mult'])

n=len(ada); capital_mxn=CONFIG['capital_mxn']; tc=CONFIG['tc']; apal=GANADORA['apalancamiento']

trades_completo=ejecutar_backtest(ada,btc,GANADORA,50,n,capital_mxn,tc)
reporte(trades_completo,"PERÍODO COMPLETO (2023-hoy)",capital_mxn,apal)

seis_meses_ms=6*30*24*3600*1000
idx6=next((i for i,v in enumerate(ada) if v['ts']>=ada[-1]['ts']-seis_meses_ms), n-500)
trades6=ejecutar_backtest(ada,btc,GANADORA,idx6,n,capital_mxn,tc)
reporte(trades6,"ÚLTIMOS 6 MESES",capital_mxn,apal)

tres_meses_ms=3*30*24*3600*1000
idx3=next((i for i,v in enumerate(ada) if v['ts']>=ada[-1]['ts']-tres_meses_ms), n-250)
trades3=ejecutar_backtest(ada,btc,GANADORA,idx3,n,capital_mxn,tc)
reporte(trades3,"ÚLTIMOS 3 MESES",capital_mxn,apal)

uno_mes_ms=1*30*24*3600*1000
idx1=next((i for i,v in enumerate(ada) if v['ts']>=ada[-1]['ts']-uno_mes_ms), n-90)
trades1=ejecutar_backtest(ada,btc,GANADORA,idx1,n,capital_mxn,tc)
reporte(trades1,"ÚLTIMO MES",capital_mxn,apal)

print(f"\n{'='*60}\n💡 Si el WR/ROI se mantiene parecido en todas las ventanas,")
print("la estrategia es robusta de verdad, no solo un pico histórico.")
print(f"{'='*60}")
