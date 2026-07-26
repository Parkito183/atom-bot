"""
señales.py — v3
Descarga velas ADA+BTC, calcula RSI/ATR/Supertrend/F&G/VWAP/WR
Snapshot listo para el motor ATR+Supertrend de estrategias.py
"""
import urllib.request, json, time, os
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FNG_ARCHIVO = os.path.join(BASE_DIR, "fear_greed_historico.json")

def descargar_velas(symbol, intervalo, limit=200):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={intervalo}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = json.loads(r.read())
        return [{'ts':int(v[0]),'open':float(v[1]),'high':float(v[2]),
                 'low':float(v[3]),'close':float(v[4]),'vol':float(v[5])} for v in raw]
    except Exception as e:
        print(f"⚠️ Error descargando {symbol}: {e}")
        return []

def precio_actual(symbol="ADAUSDT"):
    url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return float(json.loads(r.read())["price"])
    except:
        return None

def _ema(vals, span):
    k = 2/(span+1); e=[vals[0]]
    for v in vals[1:]: e.append(v*k+e[-1]*(1-k))
    return e

def calc_rsi(velas, periodo=21):
    closes=[v['close'] for v in velas]
    diffs=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    if len(diffs)<periodo: return velas
    gains=[max(x,0) for x in diffs]; losses=[max(-x,0) for x in diffs]
    ag=sum(gains[:periodo])/periodo; al=sum(losses[:periodo])/periodo
    rsi=[None]*(periodo+1)
    for i in range(periodo,len(diffs)):
        ag=(ag*(periodo-1)+gains[i])/periodo; al=(al*(periodo-1)+losses[i])/periodo
        rsi.append(100 if al==0 else 100-(100/(1+ag/al)))
    for i,v in enumerate(velas):
        v['rsi']=rsi[i] if i<len(rsi) else None
    return velas

def calc_atr(velas, periodo=14):
    n=len(velas)
    if n<2: return velas
    tr=[velas[0]['high']-velas[0]['low']]
    for i in range(1,n):
        h,l,pc=velas[i]['high'],velas[i]['low'],velas[i-1]['close']
        tr.append(max(h-l,abs(h-pc),abs(l-pc)))
    atr=_ema(tr,periodo)
    for i,v in enumerate(velas): v['atr']=atr[i]
    return velas

def calc_ema_field(velas, span, nombre):
    vals=_ema([v['close'] for v in velas], span)
    for i,v in enumerate(velas): v[nombre]=vals[i]
    return velas

def calc_supertrend(velas, periodo=10, mult=2.0):
    n=len(velas)
    if n<2: return velas
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
    return velas

def obtener_fng_actual():
    try:
        url = "https://api.alternative.me/fng/?limit=1&format=json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return int(json.loads(r.read())['data'][0]['value'])
    except:
        return 50

def snapshot_actual(tc=17.5):
    """Snapshot completo compatible con el motor ATR+Supertrend."""
    from .estrategias import CFG

    ada = descargar_velas("ADAUSDT", "4h", 150)
    btc = descargar_velas("BTCUSDT", "4h", 150)
    if not ada or not btc:
        return None

    calc_rsi(ada, periodo=CFG['rsi_periodo'])
    calc_atr(ada, periodo=14)
    calc_supertrend(ada, periodo=CFG['supertrend_periodo'], mult=CFG['supertrend_mult'])

    calc_ema_field(btc, 50, 'ema50')
    calc_atr(btc, periodo=14)
    calc_supertrend(btc, periodo=CFG['supertrend_periodo'], mult=CFG['supertrend_mult'])

    ultimo = ada[-1]
    prev   = ada[-2]
    btc_ultimo = btc[-1]

    fng_actual = obtener_fng_actual()
    atr_pct = (ultimo.get('atr',0)/ultimo['close']*100) if ultimo.get('atr') else 0

    if len(ada) >= 50:
        cambio_50 = (ultimo['close']-ada[-50]['close'])/ada[-50]['close']*100
        mercado = "alcista" if cambio_50>15 else "bajista" if cambio_50<-15 else "lateral"
    else:
        mercado = "neutral"

    return {
        'ts':            ultimo['ts'],
        'ada_precio':    ultimo['close'],
        'ada_precio_mxn':ultimo['close']*tc,
        'btc_precio':    btc_ultimo['close'],
        'rsi':           ultimo.get('rsi') or 50,
        'atr':           ultimo.get('atr') or 0,
        'atr_pct':       atr_pct,
        'supertrend':    ultimo.get('supertrend','bajista'),
        'st_prev':       prev.get('supertrend','bajista'),
        'btc_ema50':     btc_ultimo.get('ema50'),
        'btc_supertrend':btc_ultimo.get('supertrend','bajista'),
        'fng':           fng_actual,
        'mercado':       mercado,
        'tc':            tc,
    }
