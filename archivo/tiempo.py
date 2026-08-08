"""
test_tiempo.py — Mide cuánto tarda realmente 1 combinación
para poder estimar el tiempo total de las 55,296 combinaciones
"""
import urllib.request, json, time, os
from datetime import datetime
from itertools import product

CONFIG = {
    'symbol_ada': 'ADAUSDT', 'symbol_btc': 'BTCUSDT',
    'timeframe': '4h', 'start_date': '2023-01-01',
    'capital_mxn': 10000, 'tc': 17.5,
}
CACHE_DIR = '/mnt/Datos/Script/DOT_Bot/logs/cache'
os.makedirs(CACHE_DIR, exist_ok=True)

def descargar_con_cache(symbol, interval, start_str, end_str=None):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{start_str}.json")
    if os.path.exists(cache_file):
        print(f"  💾 Cache: {symbol}")
        with open(cache_file, 'r') as f:
            return json.load(f)
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str, '%Y-%m-%d').timestamp() * 1000)
    end_ts = int(datetime.now().timestamp() * 1000)
    all_velas = []; current_ts = start_ts
    print(f"  📥 Descargando {symbol}...")
    while current_ts < end_ts:
        url = f"{url_base}?symbol={symbol}&interval={interval}&startTime={current_ts}&limit=1000"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
                if not data: break
                for v in data:
                    all_velas.append({'ts':int(v[0]),'open':float(v[1]),'high':float(v[2]),
                                      'low':float(v[3]),'close':float(v[4]),'vol':float(v[5])})
                current_ts = data[-1][0] + 1
                time.sleep(0.15)
        except Exception as e:
            time.sleep(2)
    with open(cache_file, 'w') as f:
        json.dump(all_velas, f)
    print(f"  ✅ {symbol}: {len(all_velas)} velas")
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

def ejecutar_backtest_rapido(ada_velas, btc_velas, c):
    capital_mxn=CONFIG['capital_mxn']; tc=CONFIG['tc']
    trades=[]; en_trade=False; trade=None
    for i in range(50, len(ada_velas)):
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
                trades.append({'tipo':tipo,'pnl_pct':pnl_neto,'ganancia_mxn':ganancia_mxn,'ganador':pnl_neto>0,'razon':razon})
                en_trade=False; trade=None
        if not en_trade:
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
                            trade={'tipo':'long','precio_entrada':precio,'stop':stop,'objetivo':objetivo,'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True; continue
            if st_prev=='alcista' and st_now=='bajista':
                if c['rsi_short_min']<=rsi<=c['rsi_short_max']:
                    if not (c['btc_confirmacion'] and btc_regimen=='alcista'):
                        stop=precio+atr*c['stop_atr_mult']; objetivo=precio-atr*c['objetivo_atr_mult']
                        if (precio-objetivo)/(stop-precio)>=2.0:
                            trade={'tipo':'short','precio_entrada':precio,'stop':stop,'objetivo':objetivo,'idx_entrada':i,'btc_regimen':btc_regimen}
                            en_trade=True
    n=len(trades)
    if n==0: return {'trades':0}
    ganados=sum(1 for t in trades if t['ganador'])
    return {'trades':n,'wr':ganados/n*100,'pnl_total':sum(t['ganancia_mxn'] for t in trades)}

# ══ TEST DE TIEMPO ══
print("📥 Cargando datos (con cache si existe)...")
t0=time.time()
ada_raw=descargar_con_cache(CONFIG['symbol_ada'],CONFIG['timeframe'],CONFIG['start_date'])
btc_raw=descargar_con_cache(CONFIG['symbol_btc'],CONFIG['timeframe'],CONFIG['start_date'])
ts_comunes=sorted({v['ts'] for v in ada_raw}&{v['ts'] for v in btc_raw})
ada_base=[dict(v) for v in ada_raw if v['ts'] in ts_comunes]
btc_base=[dict(v) for v in btc_raw if v['ts'] in ts_comunes]
print(f"🔗 Alineadas: {len(ada_base)} velas (tardó {time.time()-t0:.1f}s)")

print("🔧 Precalculando indicadores base...")
t0=time.time()
calc_todos_base(ada_base); calc_todos_base(btc_base)
print(f"   Tardó {time.time()-t0:.2f}s")

# Probar 20 combos de ejemplo
combo_test = {
    'stop_atr_mult':2.0,'objetivo_atr_mult':3.0,'rsi_long_min':30,'rsi_long_max':70,
    'rsi_short_min':25,'rsi_short_max':60,'max_bars':24,'trailing':True,
    'trailing_atr_mult':1.0,'btc_confirmacion':True,'btc_emergencia':True,
    'early_exit':True,'early_exit_bars':4,'early_exit_min_advance':0.5,
    'supertrend_mult':2.5,'apalancamiento':3,
}

print("\n⏱️  Midiendo tiempo de 20 combinaciones...")
t0=time.time()
for i in range(20):
    ada_copy=[dict(v) for v in ada_base]
    btc_copy=[dict(v) for v in btc_base]
    calc_supertrend(ada_copy, mult=combo_test['supertrend_mult'])
    calc_supertrend(btc_copy, mult=combo_test['supertrend_mult'])
    resultado = ejecutar_backtest_rapido(ada_copy, btc_copy, combo_test)
tiempo_20 = time.time()-t0
tiempo_por_combo = tiempo_20/20

print(f"\n{'='*60}")
print(f"📊 RESULTADO DEL TEST DE TIEMPO")
print(f"{'='*60}")
print(f"Tiempo para 20 combos: {tiempo_20:.2f}s")
print(f"Tiempo por combo:      {tiempo_por_combo*1000:.1f}ms")
print(f"")
print(f"Para 55,296 combinaciones totales:")
tiempo_total_seg = 55296 * tiempo_por_combo
print(f"   Tiempo estimado: {tiempo_total_seg/60:.1f} minutos ({tiempo_total_seg/3600:.2f} horas)")
print(f"{'='*60}")
