#!/usr/bin/env python3
"""
optimizer_v2.py — Grid Search AMPLIADO + Validación Train/Val integrada
Prueba miles de combinaciones. Cada una se evalúa en 2 períodos:
  TRAIN (75% histórico) y VALIDACIÓN (25% más reciente)
Solo sobreviven al TOP las que funcionan en AMBOS — reduce overfitting.
Guarda checkpoint cada 500 combos por si se interrumpe.
"""
import urllib.request, json, time, os, random
from datetime import datetime
from itertools import product

# ═══════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════
CONFIG = {
    'symbol_ada': 'ADAUSDT', 'symbol_btc': 'BTCUSDT',
    'timeframe': '4h', 'start_date': '2023-01-01',
    'capital_mxn': 10000, 'tc': 17.5,
}
CACHE_DIR   = '/mnt/Datos/Script/DOT_Bot/logs/cache'
OUT_JSON    = '/mnt/Datos/Script/DOT_Bot/logs/optimizer_v3_resultados.json'
OUT_TXT     = '/mnt/Datos/Script/DOT_Bot/logs/optimizer_v3_resultados.txt'
CHECKPOINT  = '/mnt/Datos/Script/DOT_Bot/logs/optimizer_v3_checkpoint.json'
os.makedirs(CACHE_DIR, exist_ok=True)

SPLIT_PCT     = 0.75    # 75% train / 25% validación (más reciente)
MAX_COMBOS    = 20000   # búsqueda aleatoria dentro del espacio total
CHECKPOINT_EVERY = 500

# ═══════════════════════════════════════════════════════════════
# ESPACIO DE BÚSQUEDA AMPLIADO — muchas más variables que v1
# ═══════════════════════════════════════════════════════════════
PARAM_GRID = {
    # Gestión de riesgo
    'stop_atr_mult':         [1.0, 1.5, 2.0, 2.5, 3.0],
    'objetivo_atr_mult':     [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0],
    'min_rr':                [1.5, 2.0, 2.5, 3.0],

    # RSI — periodo y umbrales
    'rsi_periodo':           [10, 14, 21],
    'rsi_long_min':          [25, 30, 35, 40],
    'rsi_long_max':          [65, 70, 75, 80],
    'rsi_short_min':         [20, 25, 30, 35],
    'rsi_short_max':         [60, 65, 70, 75],

    # Duración del trade
    'max_bars':              [12, 18, 24, 30, 36, 48],
    'atr_min_pct':           [0.2, 0.3, 0.5, 0.8],

    # Trailing
    'trailing':              [True, False],
    'trailing_atr_mult':     [0.5, 1.0, 1.5, 2.0],

    # Filtro BTC
    'btc_confirmacion':      [True, False],
    'btc_emergencia':        [True, False],

    # Salida temprana
    'early_exit':            [True, False],
    'early_exit_bars':       [3, 4, 6, 8],
    'early_exit_min_advance':[0.3, 0.5, 1.0],

    # Supertrend
    'supertrend_mult':       [2.0, 2.5, 3.0, 3.5],
    'supertrend_periodo':    [7, 10, 14],

    # Apalancamiento
    'apalancamiento':        [2, 3, 4, 5, 6, 8],
}

def log(msg):
    print(msg, flush=True)

# ═══════════════════════════════════════════════════════════════
# DESCARGA CON CACHE
# ═══════════════════════════════════════════════════════════════
def descargar_con_cache(symbol, interval, start_str):
    cache_file = os.path.join(CACHE_DIR, f"{symbol}_{interval}_{start_str}.json")
    if os.path.exists(cache_file):
        log(f"  💾 Cache: {symbol}")
        with open(cache_file, 'r') as f: return json.load(f)
    url_base = "https://fapi.binance.com/fapi/v1/klines"
    start_ts = int(datetime.strptime(start_str,'%Y-%m-%d').timestamp()*1000)
    end_ts   = int(datetime.now().timestamp()*1000)
    all_velas=[]; current_ts=start_ts
    log(f"  📥 Descargando {symbol}...")
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
        except Exception as e:
            log(f"  ⚠️ {e}"); time.sleep(2)
    with open(cache_file,'w') as f: json.dump(all_velas,f)
    log(f"  ✅ {symbol}: {len(all_velas)} velas")
    return all_velas

# ═══════════════════════════════════════════════════════════════
# INDICADORES (parametrizables: rsi_periodo, supertrend_periodo/mult)
# ═══════════════════════════════════════════════════════════════
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

def calc_ema_field(velas, span, nombre):
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

def calc_base_fijo(velas):
    """Indicadores que NO cambian entre combos (EMA50, ATR base)."""
    calc_ema_field(velas,50,'ema50')
    calc_atr(velas)

def detectar_regimen_btc(velas, i):
    v=velas[i]; ema50=v.get('ema50'); st=v.get('supertrend')
    if ema50 is None or st is None: return 'lateral'
    dist=abs(v['close']-ema50)/ema50*100
    if dist<1.5: return 'lateral'
    if st=='alcista' and v['close']>ema50: return 'alcista'
    if st=='bajista' and v['close']<ema50: return 'bajista'
    return 'lateral'

# ═══════════════════════════════════════════════════════════════
# BACKTEST PARAMETRIZADO (recibe rango de índices)
# ═══════════════════════════════════════════════════════════════
def ejecutar_backtest(ada, btc, c, idx_ini, idx_fin, capital_mxn, tc):
    trades=[]; en_trade=False; trade=None
    for i in range(idx_ini, idx_fin):
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
                trades.append({'tipo':tipo,'pnl':pnl_neto,'gmxn':gmxn,'ganador':pnl_neto>0,'razon':razon})
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

def drawdown_pct_y_liquidado(trades, capital_efectivo_mxn):
    """Drawdown medido correctamente contra el capital efectivo invertido,
    no contra un pico de ganancias que arranca en $0 (eso inflaba el % sin sentido).
    Si el equity llega a <= 0 en algún punto, la cuenta se hubiera liquidado."""
    equity = capital_efectivo_mxn
    pico = equity
    dd_pct = 0
    liquidado = False
    for t in trades:
        equity += t['gmxn']
        if equity <= 0:
            liquidado = True
            equity = 0.01  # evita división por cero, ya quedó marcado
        pico = max(pico, equity)
        dd_pct = max(dd_pct, (pico-equity)/pico*100 if pico>0 else 100)
    return dd_pct, liquidado

def evaluar(trades, capital_mxn, apalancamiento):
    n=len(trades)
    if n==0: return None
    ganados=sum(1 for t in trades if t['ganador'])
    pnl=sum(t['gmxn'] for t in trades)
    cap_ef = capital_mxn * apalancamiento
    dd, liquidado = drawdown_pct_y_liquidado(trades, cap_ef)
    return {
        'trades':n, 'wr':ganados/n*100, 'pnl':pnl, 'roi':pnl/capital_mxn*100,
        'racha':racha_max(trades), 'dd':dd, 'liquidado':liquidado,
    }

def score_robusto(train, val):
    """Penaliza fuerte: pocos trades, WR bajo, drawdown alto, racha larga,
    e inconsistencia entre train y validación (evita overfitting)."""
    if not train or not val: return -1e9
    if train.get('liquidado') or val.get('liquidado'): return -1e9  # cuenta reventada
    if val['trades'] < 8: return -1e9          # muestra mínima en validación
    if val['roi'] <= 0: return -1e9              # DEBE ganar en datos "nuevos"
    if val['wr'] < 38: return -1e9
    if val['dd'] > 60: return -1e9               # drawdown insostenible (más estricto)

    s  = val['roi'] * 3
    s += val['wr'] * 2
    s -= val['dd'] * 1.5
    s -= val['racha'] * 15
    s += min(val['trades'], 30) * 2
    # Consistencia: penaliza si train fue MUCHO mejor que val (señal de overfit)
    if train['roi'] > 0:
        ratio = val['roi'] / train['roi']
        consist = max(0.2, min(ratio, 1.3))
    else:
        consist = 0.5
    s *= consist
    return s

# ═══════════════════════════════════════════════════════════════
# GENERADOR DE COMBINACIONES ALEATORIAS ÚNICAS
# ═══════════════════════════════════════════════════════════════
def generar_combos(grid, n, seed=42):
    random.seed(seed)
    keys = list(grid.keys())
    vistos = set()
    combos = []
    intentos = 0
    while len(combos) < n and intentos < n*5:
        intentos += 1
        combo = tuple(random.choice(grid[k]) for k in keys)
        if combo in vistos: continue
        vistos.add(combo)
        combos.append(dict(zip(keys, combo)))
    return combos

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    log("="*70)
    log("🤖 OPTIMIZER V2 — Grid ampliado + validación train/val integrada")
    log("="*70)

    log("\n📥 Cargando datos...")
    ada_raw = descargar_con_cache(CONFIG['symbol_ada'], CONFIG['timeframe'], CONFIG['start_date'])
    btc_raw = descargar_con_cache(CONFIG['symbol_btc'], CONFIG['timeframe'], CONFIG['start_date'])
    ts_comunes = sorted({v['ts'] for v in ada_raw} & {v['ts'] for v in btc_raw})
    ada_base = [dict(v) for v in ada_raw if v['ts'] in ts_comunes]
    btc_base = [dict(v) for v in btc_raw if v['ts'] in ts_comunes]
    log(f"🔗 Alineadas: {len(ada_base)} velas")

    calc_base_fijo(ada_base)
    calc_base_fijo(btc_base)

    n = len(ada_base)
    idx_split = int(n * SPLIT_PCT)
    dias_train = (ada_base[idx_split]['ts']-ada_base[0]['ts'])/(1000*3600*24)
    dias_val   = (ada_base[-1]['ts']-ada_base[idx_split]['ts'])/(1000*3600*24)
    log(f"📊 Train: {dias_train/30:.1f} meses | Validación: {dias_val/30:.1f} meses (más reciente)")

    log(f"\n🎲 Generando {MAX_COMBOS} combinaciones aleatorias únicas...")
    combos = generar_combos(PARAM_GRID, MAX_COMBOS)
    log(f"✅ {len(combos)} combinaciones listas para probar")

    # Espacio total teórico
    total_teorico = 1
    for v in PARAM_GRID.values(): total_teorico *= len(v)
    log(f"   (Espacio total teórico: {total_teorico:,} combinaciones posibles)")

    resultados = []
    inicio = time.time()

    for idx, params in enumerate(combos):
        try:
            ada = [dict(v) for v in ada_base]
            btc = [dict(v) for v in btc_base]
            calc_rsi(ada, periodo=params['rsi_periodo'])
            calc_rsi(btc, periodo=params['rsi_periodo'])
            calc_supertrend(ada, periodo=params['supertrend_periodo'], mult=params['supertrend_mult'])
            calc_supertrend(btc, periodo=params['supertrend_periodo'], mult=params['supertrend_mult'])

            trades_train = ejecutar_backtest(ada, btc, params, 50, idx_split, CONFIG['capital_mxn'], CONFIG['tc'])
            trades_val   = ejecutar_backtest(ada, btc, params, idx_split, n, CONFIG['capital_mxn'], CONFIG['tc'])

            ev_train = evaluar(trades_train, CONFIG['capital_mxn'], params['apalancamiento'])
            ev_val   = evaluar(trades_val, CONFIG['capital_mxn'], params['apalancamiento'])
            sc = score_robusto(ev_train, ev_val)

            if sc > -1e9:
                resultados.append({'params':params,'score':sc,'train':ev_train,'val':ev_val})
        except Exception:
            pass

        if (idx+1) % 100 == 0:
            elapsed = time.time()-inicio
            eta = elapsed/(idx+1)*(len(combos)-idx-1)
            mejor = max((r['score'] for r in resultados), default=0)
            log(f"  [{idx+1:5}/{len(combos)}] {(idx+1)/len(combos)*100:5.1f}% | "
                f"válidas:{len(resultados):4} | ETA:{eta/60:5.1f}min | mejor score:{mejor:.0f}")

        if (idx+1) % CHECKPOINT_EVERY == 0:
            resultados.sort(key=lambda x:x['score'], reverse=True)
            with open(CHECKPOINT, 'w') as f:
                json.dump({'progreso': f"{idx+1}/{len(combos)}",
                           'top20_parcial': resultados[:20]}, f, indent=2, default=str)

    resultados.sort(key=lambda x:x['score'], reverse=True)

    # Dedupe por firma (evita 16 filas idénticas como en v1)
    top_unicos = []
    firmas_vistas = set()
    for r in resultados:
        firma = (r['val']['trades'], round(r['val']['wr'],1), round(r['val']['roi'],1))
        if firma in firmas_vistas: continue
        firmas_vistas.add(firma)
        top_unicos.append(r)
        if len(top_unicos) >= 25: break

    log(f"\n{'='*70}")
    log(f"🏆 TOP {len(top_unicos)} CONFIGURACIONES ROBUSTAS (de {len(resultados)} válidas / {len(combos)} probadas)")
    log(f"{'='*70}")
    for i, r in enumerate(top_unicos, 1):
        p=r['params']; t=r['train']; v=r['val']
        log(f"\n#{i} — Score:{r['score']:.0f}")
        log(f"   TRAIN → {t['trades']}tr WR:{t['wr']:.0f}% ROI:{t['roi']:+.0f}% Racha:{t['racha']} DD:{t['dd']:.0f}%" + (' ⚠️LIQUIDADO' if t.get('liquidado') else ''))
        log(f"   VAL   → {v['trades']}tr WR:{v['wr']:.0f}% ROI:{v['roi']:+.0f}% Racha:{v['racha']} DD:{v['dd']:.0f}%" + (' ⚠️LIQUIDADO' if v.get('liquidado') else ''))
        log(f"   Params: stop={p['stop_atr_mult']}x obj={p['objetivo_atr_mult']}x rr_min={p['min_rr']} "
            f"RSI({p['rsi_periodo']}):{p['rsi_long_min']}-{p['rsi_long_max']}/{p['rsi_short_min']}-{p['rsi_short_max']} "
            f"bars={p['max_bars']} apal={p['apalancamiento']}x")
        log(f"   ST({p['supertrend_periodo']},{p['supertrend_mult']}) btc_conf={p['btc_confirmacion']} "
            f"trailing={p['trailing']} early_exit={p['early_exit']}")

    # Guardar JSON completo
    with open(OUT_JSON, 'w') as f:
        json.dump({
            'fecha': datetime.now().isoformat(),
            'combos_probadas': len(combos),
            'combos_validas': len(resultados),
            'dias_train': dias_train, 'dias_val': dias_val,
            'top25_robustas': top_unicos,
        }, f, indent=2, default=str)

    # TXT legible
    with open(OUT_TXT, 'w') as f:
        f.write("="*70+"\n🏆 TOP CONFIGURACIONES ROBUSTAS (validadas train+val)\n"+"="*70+"\n\n")
        for i, r in enumerate(top_unicos, 1):
            p=r['params']; t=r['train']; v=r['val']
            f.write(f"RANK #{i} | Score:{r['score']:.0f}\n")
            f.write(f"  TRAIN: {t['trades']}tr WR:{t['wr']:.0f}% ROI:{t['roi']:+.0f}% Racha:{t['racha']} DD:{t['dd']:.0f}%\n")
            f.write(f"  VAL:   {v['trades']}tr WR:{v['wr']:.0f}% ROI:{v['roi']:+.0f}% Racha:{v['racha']} DD:{v['dd']:.0f}%\n")
            f.write(f"  stop={p['stop_atr_mult']}x obj={p['objetivo_atr_mult']}x rr_min={p['min_rr']} "
                    f"RSI_periodo={p['rsi_periodo']} RSI_L={p['rsi_long_min']}-{p['rsi_long_max']} "
                    f"RSI_S={p['rsi_short_min']}-{p['rsi_short_max']}\n")
            f.write(f"  max_bars={p['max_bars']} apal={p['apalancamiento']}x ST({p['supertrend_periodo']},{p['supertrend_mult']}) "
                    f"btc_conf={p['btc_confirmacion']} btc_emerg={p['btc_emergencia']}\n")
            f.write(f"  trailing={p['trailing']}({p['trailing_atr_mult']}) early_exit={p['early_exit']} "
                    f"atr_min={p['atr_min_pct']}%\n\n")

    log(f"\n💾 JSON: {OUT_JSON}")
    log(f"💾 TXT:  {OUT_TXT}")
    log(f"⏱️  Tiempo total: {(time.time()-inicio)/60:.1f} minutos")
    log("✅ Listo — presiona el botón de subir a GitHub cuando despiertes")

if __name__ == "__main__":
    main()
