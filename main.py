"""
main.py — ATOM Bot v3
Monitor ATOM + Trading LONG/SHORT (motor único ATR+Supertrend, sin scalping)
Modo VIGILANCIA (cada 15 min) + Modo NINJA (cada 2min en trade)
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
from trading.estrategias import señal_salida, CFG
from trading.simulador  import (abrir_trade, cerrar_trade,
                                 estado_trade_actual, cargar_estado as cargar_estado_trading,
                                 resumen_completo)

LOGS_DIR     = os.path.join(_BASE_DIR, "logs")
ESTADO_FILE  = os.path.join(LOGS_DIR, "estado_atom.json")
COMPRAS_FILE = os.path.join(_BASE_DIR, "compras_atom.json")
os.makedirs(LOGS_DIR, exist_ok=True)

ALERTA_BAJAS = [float(os.environ.get(f"ALERTA_BAJA_{i}", v)) for i,v in enumerate([5,10,15],1)]
ALERTA_SUBAS = [float(os.environ.get(f"ALERTA_SUBA_{i}", v)) for i,v in enumerate([5,10,15],1)]
ALERTAS_CONFIG = {"baja_1":ALERTA_BAJAS[0],"baja_2":ALERTA_BAJAS[1],"baja_3":ALERTA_BAJAS[2],
                   "suba_1":ALERTA_SUBAS[0],"suba_2":ALERTA_SUBAS[1],"suba_3":ALERTA_SUBAS[2]}

def cargar_compras():
    try:    return json.load(open(COMPRAS_FILE))
    except: return []

def guardar_estado_atom(estado):
    try:
        with open(ESTADO_FILE,"w") as f: json.dump(estado, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ Error guardando estado ATOM: {e}")

def cargar_estado_atom():
    try:    return json.load(open(ESTADO_FILE))
    except: return {}

def verificar_alertas_atom(precio_usd, precio_ref, tc, disparadas):
    nuevas=set(disparadas); cambio=((precio_usd-precio_ref)/precio_ref)*100
    for pct in ALERTA_BAJAS:
        key=f"baja_{pct}"
        if cambio<=-pct and key not in disparadas:
            nuevas.add(key)
            enviar(f"🚨📉 *ATOM CAYÓ {pct:.0f}%*\nPrecio: *${precio_usd:.4f}* USD (${precio_usd*tc:.2f} MXN)")
    for pct in ALERTA_SUBAS:
        key=f"suba_{pct}"
        if cambio>=pct and key not in disparadas:
            nuevas.add(key)
            enviar(f"🚀📈 *ATOM SUBIÓ {pct:.0f}%*\nPrecio: *${precio_usd:.4f}* USD (${precio_usd*tc:.2f} MXN)")
    if -2<=cambio<=2: nuevas=set()
    return nuevas

def msg_trade_abierto(tipo, precio, snap, tc):
    emoji = '📈' if tipo=='long' else '📉'
    cap_ef = 10_000 * CFG['apalancamiento']
    SEP = "━━━━━━━━━━━━━━━━━━━"
    return "\n".join([
        f"{emoji} *TRADE ABIERTO — {tipo.upper()}*", SEP,
        f"Precio entrada: *${precio:.6f}* USD (${precio*tc:.4f} MXN)",
        f"Capital: *${10_000:,} MXN* × {CFG['apalancamiento']}x = *${cap_ef:,} MXN*",
        f"Stop: *{CFG['stop_atr_mult']}×ATR* | Objetivo: *{CFG['objetivo_atr_mult']}×ATR*",
        f"RSI entrada: *{snap['rsi']:.1f}* | F&G: *{snap['fng']}*",
        f"Mercado: *{snap['mercado']}*", SEP,
        "🥷 Modo NINJA activado — monitoreo cada 2 min",
    ])

def msg_trade_cerrado(resultado, tc):
    emoji = "✅" if resultado['ganador'] else "🔴"
    pnl=resultado['pnl_pct']; gmxn=resultado['ganancia_mxn']
    SEP="━━━━━━━━━━━━━━━━━━━"; res=resumen_completo(tc)
    return "\n".join([
        f"{emoji} *TRADE CERRADO — {resultado['tipo'].upper()}*", SEP,
        f"Entrada: *${resultado['precio_entrada']:.6f}* USD",
        f"Salida:  *${resultado['precio_salida']:.6f}* USD",
        f"Razón: *{resultado['razon_salida']}*",
        f"P&L: *{pnl:+.2f}%* → *{'+' if gmxn>=0 else ''}{gmxn:,.0f} MXN*", SEP,
        f"📊 Acumulado: *{'+' if res['balance_mxn']>=0 else ''}{res['balance_mxn']:,.0f} MXN*",
        f"WR total: *{res['win_rate']:.0f}%* ({res['ganados']}/{res['total_trades']})",
    ])

def ciclo_ninja(snap_inicial, tc):
    """Modo ninja — YA NO bloquea comandos: procesa Telegram cada 15s
    mientras monitorea el precio. Evalúa salida cada ~120s reales (por tiempo,
    no por conteo de iteraciones, para que sea preciso aunque se interrumpa)."""
    tipo = snap_inicial['_tipo_trade']
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 NINJA activo — {tipo.upper()}")

    ts_inicio = time.time()
    max_segundos = CFG['max_bars']*4*3600 + 600  # margen de 10 min
    ts_ultimo_check_precio = 0.0

    while time.time()-ts_inicio < max_segundos:
        ahora = time.time()

        # Procesar comandos de Telegram SIEMPRE, aunque estemos en trade
        comandos = escuchar()
        if comandos:
            estado_t = cargar_estado_trading()
            for cmd in comandos:
                procesar(cmd, {}, snap_inicial.get('ada_precio',0), tc, 0,
                         ALERTAS_CONFIG, estado_t, resumen_completo(tc))

        # Evaluar salida cada ~120s reales (no bloquea el resto)
        if ahora - ts_ultimo_check_precio >= 120:
            ts_ultimo_check_precio = ahora
            p = precio_actual("ADAUSDT")
            if p:
                estado_t = cargar_estado_trading()
                if not estado_t.get('en_trade'):
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade cerrado externamente")
                    return

                snap = snapshot_actual(tc) or snap_inicial
                snap['ada_precio'] = p

                trade = estado_t['trade_actual']
                trade['precio_max'] = max(trade.get('precio_max',p), p)
                trade['precio_min'] = min(trade.get('precio_min',p), p)
                trade['bars_transcurridas'] = int((ahora-ts_inicio)/(4*3600))

                debe_salir, razon = señal_salida(tipo, p, trade, snap)

                pe=trade['precio_entrada']
                pnl = (p-pe)/pe*100 if tipo=='long' else (pe-p)/pe*100
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 {tipo.upper()} "
                      f"P&L:{pnl:+.2f}% | ADA:${p:.5f} | F&G:{snap.get('fng',50)}")

                if debe_salir:
                    resultado = cerrar_trade(p, razon, tc)
                    if resultado:
                        enviar(msg_trade_cerrado(resultado, tc))
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade cerrado: {razon} | P&L:{resultado['pnl_pct']:+.2f}%")
                    return

        time.sleep(15)  # mismo ritmo que el loop principal — responsive a Telegram

    p = precio_actual("ADAUSDT") or snap_inicial['ada_precio']
    resultado = cerrar_trade(p, "tiempo_maximo", tc)
    if resultado: enviar(msg_trade_cerrado(resultado, tc))

def ciclo_vigilancia(tc):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Evaluando señales...")
    snap = snapshot_actual(tc)
    if not snap:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Sin datos de mercado")
        return None
    tipo = elegir_estrategia(snap)
    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
          f"ADA:${snap['ada_precio']:.5f} RSI:{snap['rsi']:.1f} "
          f"ST:{snap['supertrend']}(prev:{snap['st_prev']}) F&G:{snap['fng']} "
          f"Mercado:{snap['mercado']} → {tipo or 'ESPERAR'}")
    if tipo:
        p = precio_actual("ADAUSDT") or snap['ada_precio']
        trade = abrir_trade(tipo, p, snap, tc)
        snap['_tipo_trade'] = tipo
        enviar(msg_trade_abierto(tipo, p, snap, tc))
        return snap
    return None

def ejecutar():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌌 ATOM Bot v3 arrancando...")
    dash_path = os.path.join(_BASE_DIR, "dashboard.py")
    if os.path.exists(dash_path):
        subprocess.Popen(["python3", dash_path],
            stdout=open(os.path.join(LOGS_DIR,"dashboard.log"),"a"),
            stderr=subprocess.STDOUT, cwd=_BASE_DIR)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🌐 Dashboard arrancado")

    estado_atom = cargar_estado_atom()
    precio_ref = estado_atom.get("precio_ref")
    alertas_disp = set(estado_atom.get("alertas_disparadas", []))
    saldos={}; precio_usd=None; tc = obtener_tipo_cambio_mxn()
    _ts_precio=0.0; _ts_blockchain=0.0; _ts_trading=0.0; _ts_save=0.0

    enviar(msg_bienvenida())

    while True:
        try:
            ahora = time.time()
            comandos = escuchar()
            if comandos:
                estado_t = cargar_estado_trading()
                for cmd in comandos:
                    procesar(cmd, saldos, precio_usd or 0, tc, precio_ref or 0,
                             ALERTAS_CONFIG, estado_t, resumen_completo(tc))

            if ahora-_ts_precio>=5*60:
                _ts_precio=ahora
                nuevo=obtener_precio_atom_usd(); nuevo_tc=obtener_tipo_cambio_mxn()
                if nuevo:
                    precio_usd=nuevo; tc=nuevo_tc
                    if not precio_ref: precio_ref=precio_usd
                    alertas_disp=verificar_alertas_atom(precio_usd,precio_ref,tc,alertas_disp)
                    cambio=(precio_usd-precio_ref)/precio_ref*100
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ATOM ${precio_usd:.4f} ({cambio:+.2f}%)")

            if ahora-_ts_blockchain>=60*60:
                _ts_blockchain=ahora
                nuevos=consultar_saldos_blockchain_atom()
                if nuevos:
                    saldos=nuevos
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Blockchain: {saldos.get('staking',0):.2f} ATOM staked")

            estado_t = cargar_estado_trading()
            if not estado_t.get('en_trade') and ahora-_ts_trading>=15*60:
                _ts_trading=ahora
                snap = ciclo_vigilancia(tc)
                if snap:
                    ciclo_ninja(snap, tc)
                    _ts_trading=time.time()

            if ahora-_ts_save>=30:
                _ts_save=ahora
                estado_t=cargar_estado_trading()
                guardar_estado_atom({
                    "precio_actual":precio_usd,"precio_ref":precio_ref,"tc":tc,
                    "saldos":saldos,"alertas_disparadas":list(alertas_disp),
                    "ultima_actualizacion":datetime.now().isoformat(),"trading":estado_t,
                })
            time.sleep(15)

        except KeyboardInterrupt:
            print("\n🛑 Bot detenido.")
            enviar("🛑 ATOM Bot v3 detenido.")
            break
        except Exception as e:
            print(f"⚠️ Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    ejecutar()
