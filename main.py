"""
main.py — ATOM Bot v2
Monitor ATOM + Sistema de trading 3 estrategias
Modo VIGILANCIA (cada 4h) + Modo NINJA (cada 2min en trade)
"""
import time, os, json, subprocess
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_env_file = os.path.join(_BASE_DIR, "config.env")
os.chdir(_BASE_DIR)

if os.path.exists(_env_file):
    for _l in open(_env_file).readlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ[_k.strip()] = _v.split("#")[0].strip()

from blockchain  import (consultar_saldos_blockchain_atom,
                          obtener_precio_atom_usd, obtener_tipo_cambio_mxn)
from bot_telegram import (enviar, escuchar, msg_bienvenida,
                           msg_atom_completo, procesar)
from trading.señales    import snapshot_actual, precio_actual
from trading.gestor     import elegir_estrategia, descripcion_señal, contexto_mercado
from trading.estrategias import (señal_salida_long, señal_salida_short,
                                  señal_salida_scalping, CFG)
from trading.simulador  import (abrir_trade, cerrar_trade,
                                 estado_trade_actual, cargar_estado as cargar_estado_trading,
                                 resumen_completo)

LOGS_DIR     = os.path.join(_BASE_DIR, "logs")
ESTADO_FILE  = os.path.join(LOGS_DIR, "estado_atom.json")
COMPRAS_FILE = os.path.join(_BASE_DIR, "compras_atom.json")
os.makedirs(LOGS_DIR, exist_ok=True)

ALERTA_BAJAS = [float(os.environ.get(f"ALERTA_BAJA_{i}", v))
                for i, v in enumerate([5,10,15], 1)]
ALERTA_SUBAS = [float(os.environ.get(f"ALERTA_SUBA_{i}", v))
                for i, v in enumerate([5,10,15], 1)]
ALERTAS_CONFIG = {
    "baja_1":ALERTA_BAJAS[0],"baja_2":ALERTA_BAJAS[1],"baja_3":ALERTA_BAJAS[2],
    "suba_1":ALERTA_SUBAS[0],"suba_2":ALERTA_SUBAS[1],"suba_3":ALERTA_SUBAS[2],
}

def cargar_compras():
    try:    return json.load(open(COMPRAS_FILE))
    except: return []

def guardar_estado_atom(estado):
    try:
        with open(ESTADO_FILE, "w") as f:
            json.dump(estado, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ Error guardando estado ATOM: {e}")

def cargar_estado_atom():
    try:    return json.load(open(ESTADO_FILE))
    except: return {}

def verificar_alertas_atom(precio_usd, precio_ref, tc, disparadas):
    nuevas = set(disparadas)
    cambio = ((precio_usd - precio_ref) / precio_ref) * 100
    for pct in ALERTA_BAJAS:
        key = f"baja_{pct}"
        if cambio <= -pct and key not in disparadas:
            nuevas.add(key)
            enviar(f"🚨📉 *ATOM CAYÓ {pct:.0f}%*\n"
                   f"Precio: *${precio_usd:.4f}* USD (${precio_usd*tc:.2f} MXN)")
    for pct in ALERTA_SUBAS:
        key = f"suba_{pct}"
        if cambio >= pct and key not in disparadas:
            nuevas.add(key)
            enviar(f"🚀📈 *ATOM SUBIÓ {pct:.0f}%*\n"
                   f"Precio: *${precio_usd:.4f}* USD (${precio_usd*tc:.2f} MXN)")
    if -2 <= cambio <= 2:
        nuevas = set()
    return nuevas

def msg_trade_abierto(tipo, precio, snap, tc):
    emojis = {'long':'📈','short':'📉','scalping':'⚡'}
    c = CFG[tipo]
    cap_ef = 10_000 * c['apalancamiento']
    SEP = "━━━━━━━━━━━━━━━━━━━"
    return "\n".join([
        f"{emojis[tipo]} *TRADE ABIERTO — {tipo.upper()}*",
        SEP,
        f"Precio entrada: *${precio:.6f}* USD (${precio*tc:.4f} MXN)",
        f"Capital: *${10_000:,} MXN* × {c['apalancamiento']}x = *${cap_ef:,} MXN*",
        f"Objetivo: *+{c['objetivo_pct']}%* | Stop: *-{c['stop_pct']}%*",
        f"RSI entrada: *{snap['rsi']:.1f}* | F&G: *{snap['fng']}*",
        f"Mercado: *{snap['mercado']}*",
        SEP,
        "🥷 Modo NINJA activado — monitoreo cada 2 min",
    ])

def msg_trade_cerrado(resultado, tc):
    emoji = "✅" if resultado['ganador'] else "🔴"
    pnl   = resultado['pnl_pct']
    gmxn  = resultado['ganancia_mxn']
    SEP   = "━━━━━━━━━━━━━━━━━━━"
    res   = resumen_completo(tc)
    return "\n".join([
        f"{emoji} *TRADE CERRADO — {resultado['tipo'].upper()}*",
        SEP,
        f"Entrada: *${resultado['precio_entrada']:.6f}* USD",
        f"Salida:  *${resultado['precio_salida']:.6f}* USD",
        f"Razón: *{resultado['razon_salida']}*",
        f"P&L: *{pnl:+.2f}%* → *{'+' if gmxn>=0 else ''}{gmxn:,.0f} MXN*",
        SEP,
        f"📊 Acumulado: *{'+' if res['balance_mxn']>=0 else ''}{res['balance_mxn']:,.0f} MXN*",
        f"WR total: *{res['win_rate']:.0f}%* ({res['ganados']}/{res['total_trades']})",
    ])

def ciclo_ninja(snap_inicial, tc):
    """Modo ninja — monitorea cada 2 min mientras hay trade abierto."""
    tipo = snap_inicial['_tipo_trade']
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 NINJA activo — {tipo.upper()}")

    max_iter = int(CFG[tipo]['max_dias'] * 24 * 60 / 2) + 200  # +Plan B margin
    for _ in range(max_iter):
        time.sleep(120)  # 2 minutos

        # Precio en tiempo real
        p = precio_actual("ADAUSDT")
        if not p:
            continue

        estado_t = cargar_estado_trading()
        if not estado_t.get('en_trade'):
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade cerrado externamente")
            return

        # Snapshot ligero para indicadores de salida
        snap = snapshot_actual(tc)
        if not snap:
            snap = snap_inicial
        snap['ada_precio'] = p

        trade = estado_t['trade_actual']
        trade['precio_max'] = max(trade.get('precio_max', p), p)
        trade['precio_min'] = min(trade.get('precio_min', p), p)

        debe_salir = False; razon = None
        if tipo == 'long':
            debe_salir, razon = señal_salida_long(p, trade, snap)
        elif tipo == 'short':
            debe_salir, razon = señal_salida_short(p, trade, snap)
        elif tipo == 'scalping':
            debe_salir, razon = señal_salida_scalping(p, trade, snap)

        # Mostrar P&L cada 30 min
        pe  = trade['precio_entrada']
        if tipo in ('long','scalping'):
            pnl = (p-pe)/pe*100
        else:
            pnl = (pe-p)/pe*100
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 {tipo.upper()} "
              f"P&L:{pnl:+.2f}% | ADA:${p:.5f} | F&G:{snap.get('fng',50)}")

        if debe_salir:
            resultado = cerrar_trade(p, razon, tc)
            if resultado:
                enviar(msg_trade_cerrado(resultado, tc))
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Trade cerrado: {razon} | P&L:{resultado['pnl_pct']:+.2f}%")
            return

    # Tiempo máximo alcanzado
    p = precio_actual("ADAUSDT") or snap_inicial['ada_precio']
    resultado = cerrar_trade(p, "tiempo_maximo", tc)
    if resultado:
        enviar(msg_trade_cerrado(resultado, tc))

def ciclo_vigilancia(tc):
    """Modo vigilancia — evalúa señales cada 4h."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Evaluando señales...")
    snap = snapshot_actual(tc)
    if not snap:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Sin datos de mercado")
        return None

    tipo = elegir_estrategia(snap)
    ctx  = contexto_mercado(snap)

    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"ADA:${snap['ada_precio']:.5f} RSI:{snap['rsi']:.1f} "
          f"F&G:{snap['fng']} Mercado:{snap['mercado']} → {tipo or 'ESPERAR'}")

    if tipo:
        p = precio_actual("ADAUSDT") or snap['ada_precio']
        trade = abrir_trade(tipo, p, snap, tc)
        snap['_tipo_trade'] = tipo
        enviar(msg_trade_abierto(tipo, p, snap, tc))
        return snap  # retorna para entrar en modo ninja

    return None

def ejecutar():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌌 ATOM Bot v2 arrancando...")

    # Dashboard
    dash_path = os.path.join(_BASE_DIR, "dashboard.py")
    if os.path.exists(dash_path):
        subprocess.Popen(["python3", dash_path],
            stdout=open(os.path.join(LOGS_DIR, "dashboard.log"), "a"),
            stderr=subprocess.STDOUT, cwd=_BASE_DIR)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌐 Dashboard arrancado")

    # Estado inicial
    estado_atom       = cargar_estado_atom()
    precio_ref        = estado_atom.get("precio_ref")
    alertas_disp      = set(estado_atom.get("alertas_disparadas", []))
    saldos            = {}
    precio_usd        = None
    tc                = obtener_tipo_cambio_mxn()

    _ts_precio        = 0.0
    _ts_blockchain    = 0.0
    _ts_trading       = 0.0   # cada 4h
    _ts_save          = 0.0

    enviar(msg_bienvenida())

    while True:
        try:
            ahora = time.time()

            # Escuchar Telegram
            comandos = escuchar()
            if comandos:
                estado_t = cargar_estado_trading()
                compras  = cargar_compras()
                for cmd in comandos:
                    print(f'DEBUG saldos tipo: {type(saldos)} val: {str(saldos)[:50]}')
                    procesar(cmd, saldos, precio_usd or 0, tc,
                             precio_ref or 0, ALERTAS_CONFIG,
                             estado_t, resumen_completo(tc))

            # Precio ATOM cada 5 min
            if ahora - _ts_precio >= 5*60:
                _ts_precio = ahora
                nuevo = obtener_precio_atom_usd()
                nuevo_tc = obtener_tipo_cambio_mxn()
                if nuevo:
                    precio_usd = nuevo; tc = nuevo_tc
                    if not precio_ref: precio_ref = precio_usd
                    alertas_disp = verificar_alertas_atom(
                        precio_usd, precio_ref, tc, alertas_disp)
                    cambio = (precio_usd-precio_ref)/precio_ref*100
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                          f"ATOM ${precio_usd:.4f} ({cambio:+.2f}%)")

            # Blockchain cada 60 min
            if ahora - _ts_blockchain >= 60*60:
                _ts_blockchain = ahora
                nuevos = consultar_saldos_blockchain_atom()
                if nuevos:
                    saldos = nuevos
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                          f"Blockchain: {saldos.get('staking',0):.2f} ATOM staked")

            # Ciclo trading cada 4h (si no hay trade activo)
            estado_t = cargar_estado_trading()
            if not estado_t.get('en_trade') and ahora - _ts_trading >= 15*60:
                _ts_trading = ahora
                snap = ciclo_vigilancia(tc)
                if snap:  # señal encontrada → modo ninja
                    ciclo_ninja(snap, tc)
                    _ts_trading = time.time()  # reset timer después del trade

            # Guardar estado ATOM cada 30s
            if ahora - _ts_save >= 30:
                _ts_save = ahora
                estado_t = cargar_estado_trading()
                guardar_estado_atom({
                    "precio_actual":        precio_usd,
                    "precio_ref":           precio_ref,
                    "tc":                   tc,
                    "saldos":               saldos,
                    "alertas_disparadas":   list(alertas_disp),
                    "ultima_actualizacion": datetime.now().isoformat(),
                    "trading":              estado_t,
                })

            time.sleep(15)

        except KeyboardInterrupt:
            print("\n🛑 Bot detenido.")
            enviar("🛑 ATOM Bot v2 detenido.")
            break
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    ejecutar()
