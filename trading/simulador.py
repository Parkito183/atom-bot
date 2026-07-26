"""
simulador.py — Paper trading con apalancamiento simulado
Simula operaciones reales sin ejecutar órdenes en Binance
Capital: $10,000 MXN | Apalancamiento: 8x LONG/SHORT, 4x SCALPING
"""
import json, os
from datetime import datetime
from .estrategias import CFG, pnl_neto, ganancia_mxn

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ESTADO_FILE = os.path.join(BASE_DIR, "logs", "estado_trading.json")
HIST_FILE   = os.path.join(BASE_DIR, "logs", "historial_trades.json")

CAPITAL_MXN  = 10_000
TC_DEFAULT   = 17.5

def cargar_estado() -> dict:
    try:    return json.load(open(ESTADO_FILE))
    except: return {
        'en_trade':      False,
        'trade_actual':  None,
        'balance_mxn':   0.0,
        'trades_total':  0,
        'trades_ganados':0,
        'ultima_señal':  None,
    }

def guardar_estado(estado: dict):
    os.makedirs(os.path.dirname(ESTADO_FILE), exist_ok=True)
    with open(ESTADO_FILE, 'w') as f:
        json.dump(estado, f, indent=2, default=str)

def cargar_historial() -> list:
    try:    return json.load(open(HIST_FILE))
    except: return []

def guardar_historial(hist: list):
    os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
    with open(HIST_FILE, 'w') as f:
        json.dump(hist, f, indent=2, default=str)

def abrir_trade(tipo: str, precio: float, snap: dict, tc: float = TC_DEFAULT) -> dict:
    """Abre un trade simulado."""
    c      = CFG[tipo]
    cap_ef = CAPITAL_MXN / tc * c['apalancamiento']
    estado = cargar_estado()

    trade = {
        'tipo':           tipo,
        'precio_entrada': precio,
        'precio_max':     precio,
        'precio_min':     precio,
        'fecha_entrada':  datetime.now().isoformat(),
        'plan_b':         False,
        'capital_mxn':    CAPITAL_MXN,
        'apalancamiento': c['apalancamiento'],
        'capital_efectivo_usd': cap_ef,
        'capital_efectivo_mxn': cap_ef * tc,
        'fng_entrada':    snap.get('fng', 50),
        'rsi_entrada':    snap.get('rsi', 50),
        'mercado':        snap.get('mercado', 'neutral'),
        'tc':             tc,
    }

    estado['en_trade']     = True
    estado['trade_actual'] = trade
    estado['ultima_señal'] = {
        'tipo':  tipo,
        'fecha': datetime.now().isoformat(),
        'fng':   snap.get('fng', 50),
        'rsi':   snap.get('rsi', 50),
    }
    guardar_estado(estado)
    return trade

def cerrar_trade(precio_salida: float, razon: str, tc: float = TC_DEFAULT) -> dict:
    """Cierra el trade activo y registra resultado."""
    estado = cargar_estado()
    if not estado.get('en_trade') or not estado.get('trade_actual'):
        return None

    trade = estado['trade_actual']
    tipo  = trade['tipo']
    pe    = trade['precio_entrada']

    pnl   = pnl_neto(tipo, pe, precio_salida)
    gmxn  = ganancia_mxn(tipo, pnl, CAPITAL_MXN, tc)

    resultado = {
        **trade,
        'precio_salida':  precio_salida,
        'fecha_salida':   datetime.now().isoformat(),
        'razon_salida':   razon,
        'pnl_pct':        pnl,
        'ganancia_mxn':   gmxn,
        'ganador':        pnl > 0,
    }

    # Actualizar balance acumulado
    estado['balance_mxn']    = estado.get('balance_mxn', 0) + gmxn
    estado['trades_total']   = estado.get('trades_total', 0) + 1
    if pnl > 0:
        estado['trades_ganados'] = estado.get('trades_ganados', 0) + 1
    estado['en_trade']     = False
    estado['trade_actual'] = None
    estado['ultimo_trade'] = resultado
    guardar_estado(estado)

    # Agregar al historial
    hist = cargar_historial()
    hist.append(resultado)
    guardar_historial(hist)

    return resultado

def estado_trade_actual(precio_actual: float, tc: float = TC_DEFAULT) -> dict | None:
    """Retorna el estado del trade actual con P&L en tiempo real."""
    estado = cargar_estado()
    if not estado.get('en_trade') or not estado.get('trade_actual'):
        return None

    trade = estado['trade_actual']
    tipo  = trade['tipo']
    pe    = trade['precio_entrada']

    if tipo in ('long', 'scalping'):
        pnl_actual = (precio_actual - pe) / pe * 100
    else:
        pnl_actual = (pe - precio_actual) / pe * 100

    pnl_neto_pct = pnl_actual - CFG[tipo]['comision'] * 2 * 100
    gmxn_actual  = ganancia_mxn(tipo, pnl_neto_pct, CAPITAL_MXN, tc)

    return {
        **trade,
        'precio_actual':   precio_actual,
        'pnl_pct':         pnl_neto_pct,
        'ganancia_mxn':    gmxn_actual,
        'en_ganancia':     pnl_neto_pct > 0,
    }

def resumen_completo(tc: float = TC_DEFAULT) -> dict:
    """Retorna resumen completo del sistema de trading."""
    estado = cargar_estado()
    hist   = cargar_historial()

    total      = len(hist)
    ganados    = sum(1 for t in hist if t.get('ganador'))
    bal        = estado.get('balance_mxn', 0)
    wr         = ganados/total*100 if total > 0 else 0

    # Racha actual
    racha = 0
    for t in reversed(hist):
        if t.get('ganador'): break
        racha += 1

    # Por estrategia
    por_tipo = {}
    for tipo in ['long', 'short', 'scalping']:
        sub = [t for t in hist if t.get('tipo') == tipo]
        if sub:
            sw = [t for t in sub if t.get('ganador')]
            por_tipo[tipo] = {
                'trades': len(sub),
                'ganados': len(sw),
                'wr': len(sw)/len(sub)*100,
                'ganancia_mxn': sum(t.get('ganancia_mxn',0) for t in sub),
            }

    return {
        'total_trades':   total,
        'ganados':        ganados,
        'perdidos':       total - ganados,
        'win_rate':       wr,
        'balance_mxn':   bal,
        'racha_perdidas': racha,
        'en_trade':       estado.get('en_trade', False),
        'trade_actual':   estado.get('trade_actual'),
        'por_tipo':       por_tipo,
        'historial':      hist[-10:],  # últimos 10
    }
