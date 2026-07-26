"""
señales.py — Calcula todos los indicadores técnicos
RSI, BTC correlación, Fear & Greed, VWAP, Williams R, Supertrend
"""
import urllib.request, json, time, os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FNG_ARCHIVO = os.path.join(BASE_DIR, "..", "fear_greed_historico.json")

# ── Descarga de velas ──────────────────────────────────────────
def descargar_velas(symbol, intervalo, limit=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intervalo}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = json.loads(r.read())
        velas = []
        for v in raw:
            velas.append({
                'ts':    int(v[0]),
                'open':  float(v[1]),
                'high':  float(v[2]),
                'low':   float(v[3]),
                'close': float(v[4]),
                'vol':   float(v[5]),
            })
        return velas
    except Exception as e:
        print(f"⚠️ Error descargando {symbol}: {e}")
        return []

def precio_actual(symbol="ADAUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read())
            return float(d["price"])
    except:
        return None

# ── Indicadores ────────────────────────────────────────────────
def _ema(vals, span):
    k = 2/(span+1); e = [vals[0]]
    for v in vals[1:]: e.append(v*k + e[-1]*(1-k))
    return e

def calc_rsi(velas, periodo=14):
    closes = [v['close'] for v in velas]
    diffs  = [closes[i]-closes[i-1] for i in range(1, len(closes))]
    ag = _ema([max(x,0) for x in diffs], 27)
    al = _ema([max(-x,0) for x in diffs], 27)
    rsi = [None] + [100-(100/(1+ag[i]/max(al[i],1e-9))) for i in range(len(diffs))]
    for i, v in enumerate(velas):
        v['rsi']      = rsi[i]
        v['rsi_prev'] = rsi[i-1] if i > 0 else rsi[i]
    return velas

def calc_vwap(velas):
    cpv = cv = 0
    for v in velas:
        tp   = (v['high']+v['low']+v['close'])/3
        cpv += tp * v['vol']
        cv  += v['vol']
        v['vwap'] = cpv/cv if cv > 0 else v['close']
    return velas

def calc_williams_r(velas, periodo=14):
    n = len(velas)
    for i in range(n):
        if i < periodo:
            velas[i]['wr'] = None
            continue
        h = max(v['high']  for v in velas[i-periodo:i+1])
        l = min(v['low']   for v in velas[i-periodo:i+1])
        velas[i]['wr'] = -100*(h-velas[i]['close'])/(h-l) if h!=l else -50
    return velas

def calc_volma(velas, periodo=20):
    vols = [v['vol'] for v in velas]
    for i in range(len(velas)):
        if i < periodo:
            velas[i]['volma'] = None
        else:
            velas[i]['volma'] = sum(vols[i-periodo:i])/periodo
    return velas

def calc_supertrend(velas, periodo=7, mult=2.0):
    n = len(velas)
    tr = [velas[0]['high']-velas[0]['low']]
    for i in range(1, n):
        h, l, pc = velas[i]['high'], velas[i]['low'], velas[i-1]['close']
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
    atr   = _ema(tr, periodo)
    upper = [((velas[i]['high']+velas[i]['low'])/2)+mult*atr[i] for i in range(n)]
    lower = [((velas[i]['high']+velas[i]['low'])/2)-mult*atr[i] for i in range(n)]
    st    = ['bajista']*n; stl = [upper[0]]*n
    for i in range(1, n):
        c = velas[i]['close']
        if st[i-1] == 'alcista':
            lower[i] = max(lower[i], stl[i-1])
            st[i]    = 'bajista' if c < stl[i-1] else 'alcista'
            stl[i]   = upper[i] if st[i]=='bajista' else lower[i]
        else:
            upper[i] = min(upper[i], stl[i-1])
            st[i]    = 'alcista' if c > stl[i-1] else 'bajista'
            stl[i]   = lower[i] if st[i]=='alcista' else upper[i]
    for i in range(n):
        velas[i]['supertrend'] = st[i]
    return velas

def calc_todos(velas):
    calc_rsi(velas)
    calc_vwap(velas)
    calc_williams_r(velas)
    calc_volma(velas)
    calc_supertrend(velas)
    return [v for v in velas if v.get('rsi') is not None and v.get('volma') is not None]

def calc_pct(velas):
    pcts = [0.0]
    for i in range(1, len(velas)):
        pcts.append((velas[i]['close']-velas[i-1]['close'])/velas[i-1]['close']*100)
    return pcts

# ── Fear & Greed ───────────────────────────────────────────────
def obtener_fng_actual():
    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            d = json.loads(r.read())
            return int(d['data'][0]['value'])
    except:
        return 50

def cargar_fng_historico():
    try:
        return json.load(open(FNG_ARCHIVO))
    except:
        return {}

def get_fng_fecha(ts, fng_hist):
    fecha = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d')
    return fng_hist.get(fecha, 50)

# ── Contexto completo (snapshot actual) ───────────────────────
def snapshot_actual(tc=17.5):
    """Retorna un snapshot completo del mercado en tiempo real."""
    ada_velas = descargar_velas("ADAUSDT", "4h", 150)
    btc_velas = descargar_velas("BTCUSDT", "4h", 150)
    if not ada_velas or not btc_velas:
        return None

    ada_velas = calc_todos(ada_velas)
    btc_pct   = calc_pct(btc_velas)
    ada_pct   = calc_pct(ada_velas)
    btc_map   = {v['ts']:i for i, v in enumerate(btc_velas)}
    fng_hist  = cargar_fng_historico()
    fng_actual = obtener_fng_actual()

    ultimo     = ada_velas[-1]
    btc_ultimo = btc_velas[-1]
    ts_actual  = ultimo['ts']

    # Correlación ADA vs BTC (últimas 3 velas)
    ventana = 3
    btc_idx = btc_map.get(ts_actual)
    diff_acum = 0
    if btc_idx and btc_idx >= ventana:
        diff_acum = sum(
            ada_pct[-(ventana-j)] - btc_pct[btc_idx-j]
            for j in range(ventana)
        )

    # BTC filtro para LONG
    btc_ok_long = True
    if btc_idx and btc_idx >= 5:
        pc_antes  = btc_velas[btc_idx-5]['close']
        pc_ahora  = btc_velas[btc_idx]['close']
        caida_btc = (pc_antes-pc_ahora)/pc_antes*100
        min_btc   = min(v['low'] for v in btc_velas[btc_idx-5:btc_idx+1])
        rebote_btc = (pc_ahora-min_btc)/min_btc*100
        btc_ok_long = caida_btc <= 8.0 and rebote_btc >= 3.0

    # Tipo de mercado
    if len(ada_velas) >= 50:
        cambio_50 = (ultimo['close']-ada_velas[-50]['close'])/ada_velas[-50]['close']*100
        if cambio_50 > 15:   mercado = "alcista"
        elif cambio_50 < -15: mercado = "bajista"
        else:                 mercado = "lateral"
    else:
        mercado = "neutral"

    return {
        'ts':          ts_actual,
        'ada_precio':  ultimo['close'],
        'ada_precio_mxn': ultimo['close'] * tc,
        'btc_precio':  btc_ultimo['close'],
        'rsi':         ultimo.get('rsi') or 50,
        'rsi_prev':    ultimo.get('rsi_prev') or 50,
        'vwap':        ultimo.get('vwap') or ultimo['close'],
        'wr':          ultimo.get('wr'),
        'supertrend':  ultimo.get('supertrend', 'bajista'),
        'volma':       ultimo.get('volma'),
        'vol':         ultimo.get('vol'),
        'fng':         fng_actual,
        'diff_btc':    diff_acum,
        'ada_vela_pct': ada_pct[-1] if ada_pct else 0,
        'btc_ok_long': btc_ok_long,
        'mercado':     mercado,
        'ada_velas':   ada_velas,
        'btc_velas':   btc_velas,
        'tc':          tc,
    }
