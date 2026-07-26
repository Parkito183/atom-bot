"""
simulador.py — v3
Paper trading con el motor único ATR+Supertrend. Un solo apalancamiento (CFG['apalancamiento']).
"""
import json, os
from datetime import datetime
from .estrategias import CFG, pnl_neto, ganancia_mxn, calcular_niveles

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESTADO_FILE = os.path.join(BASE_DIR, "logs", "estado_trading.json")
HIST_FILE   = os.path.join(BASE_DIR, "logs", "historial_trades.json")
CAPITAL_MXN = 10_000
TC_DEFAULT  = 17.5

def cargar_estado():
    try:    return json.load(open(ESTADO_FILE))
    except: return {'en_trade':False,'trade_actual':None,'balance_mxn':0.0,
                     'trades_total':0,'trades_ganados':0,'ultima_señal':None}

def guardar_estado(estado):
    os.makedirs(os.path.dirname(ESTADO_FILE), exist_ok=True)
    with open(ESTADO_FILE,'w') as f: json.dump(estado, f, indent=2, default=str)

def cargar_historial():
    try:    return json.load(open(HIST_FILE))
    except: return []

def guardar_historial(hist):
    os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
    with open(HIST_FILE,'w') as f: json.dump(hist, f, indent=2, default=str)

def abrir_trade(tipo, precio, snap, tc=TC_DEFAULT):
    atr = snap.get('atr', precio*0.02) or precio*0.02
    stop, objetivo = calcular_niveles(tipo, precio, atr)
    cap_ef = CAPITAL_MXN/tc*CFG['apalancamiento']
    estado = cargar_estado()
    trade = {
        'tipo': tipo, 'precio_entrada': precio, 'stop': stop, 'objetivo': objetivo,
        'precio_max': precio, 'precio_min': precio, 'bars_transcurridas': 0,
        'fecha_entrada': datetime.now().isoformat(),
        'capital_mxn': CAPITAL_MXN, 'apalancamiento': CFG['apalancamiento'],
        'capital_efectivo_usd': cap_ef, 'capital_efectivo_mxn': cap_ef*tc,
        'fng_entrada': snap.get('fng',50), 'rsi_entrada': snap.get('rsi',50),
        'mercado': snap.get('mercado','neutral'),
        'btc_regimen': snap.get('_btc_regimen','lateral'), 'tc': tc,
    }
    estado['en_trade']=True; estado['trade_actual']=trade
    estado['ultima_señal']={'tipo':tipo,'fecha':datetime.now().isoformat(),
                             'fng':snap.get('fng',50),'rsi':snap.get('rsi',50)}
    guardar_estado(estado)
    return trade

def cerrar_trade(precio_salida, razon, tc=TC_DEFAULT):
    estado = cargar_estado()
    if not estado.get('en_trade') or not estado.get('trade_actual'): return None
    trade = estado['trade_actual']; tipo=trade['tipo']; pe=trade['precio_entrada']
    pnl = pnl_neto(tipo, pe, precio_salida)
    gmxn = ganancia_mxn(pnl, CAPITAL_MXN, tc)
    resultado = {**trade, 'precio_salida':precio_salida, 'fecha_salida':datetime.now().isoformat(),
                 'razon_salida':razon, 'pnl_pct':pnl, 'ganancia_mxn':gmxn, 'ganador':pnl>0}
    estado['balance_mxn']=estado.get('balance_mxn',0)+gmxn
    estado['trades_total']=estado.get('trades_total',0)+1
    if pnl>0: estado['trades_ganados']=estado.get('trades_ganados',0)+1
    estado['en_trade']=False; estado['trade_actual']=None; estado['ultimo_trade']=resultado
    guardar_estado(estado)
    hist=cargar_historial(); hist.append(resultado); guardar_historial(hist)
    return resultado

def estado_trade_actual(precio_actual, tc=TC_DEFAULT):
    estado = cargar_estado()
    if not estado.get('en_trade') or not estado.get('trade_actual'): return None
    trade=estado['trade_actual']; tipo=trade['tipo']; pe=trade['precio_entrada']
    pnl = pnl_neto(tipo, pe, precio_actual)
    gmxn = ganancia_mxn(pnl, CAPITAL_MXN, tc)
    return {**trade, 'precio_actual':precio_actual, 'pnl_pct':pnl,
            'ganancia_mxn':gmxn, 'en_ganancia':pnl>0}

def resumen_completo(tc=TC_DEFAULT):
    estado=cargar_estado(); hist=cargar_historial()
    total=len(hist); ganados=sum(1 for t in hist if t.get('ganador'))
    bal=estado.get('balance_mxn',0); wr=ganados/total*100 if total>0 else 0
    racha=0
    for t in reversed(hist):
        if t.get('ganador'): break
        racha+=1
    por_tipo={}
    for tipo in ['long','short']:
        sub=[t for t in hist if t.get('tipo')==tipo]
        if sub:
            sw=[t for t in sub if t.get('ganador')]
            por_tipo[tipo]={'trades':len(sub),'ganados':len(sw),
                             'wr':len(sw)/len(sub)*100,
                             'ganancia_mxn':sum(t.get('ganancia_mxn',0) for t in sub)}
    return {'total_trades':total,'ganados':ganados,'perdidos':total-ganados,'win_rate':wr,
            'balance_mxn':bal,'racha_perdidas':racha,'en_trade':estado.get('en_trade',False),
            'trade_actual':estado.get('trade_actual'),'por_tipo':por_tipo,'historial':hist[-10:]}
