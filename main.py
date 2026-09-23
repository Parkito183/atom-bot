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
ESCANEO_FILE = os.path.join(LOGS_DIR, "ultimo_escaneo.json")
os.makedirs(LOGS_DIR, exist_ok=True)

# Orden de prioridad del escaneo: score validado en backtest (12 meses,
# train/val 70/30, motor ATR+Supertrend con btc_regimen+FNG+min_rr) — de
# mayor a menor. El primer activo de esta lista que dé señal en el ciclo
# de vigilancia es el que opera el bot; los demás se quedan esperando.
ACTIVOS_ESCANEO = ["LINKUSDT", "LTCUSDT", "SUIUSDT", "DOGEUSDT", "HBARUSDT", "ADAUSDT"]

def guardar_ultimo_escaneo(resultados, ganador):
    try:
        with open(ESCANEO_FILE, "w") as f:
            json.dump({"ts": datetime.now().isoformat(), "activos": resultados,
                       "ganador": ganador}, f, indent=2, default=str)
    except Exception as e:
        print(f"⚠️ Error guardando último escaneo: {e}")

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

# Estado compartido de precio/saldos ATOM — vive a nivel de módulo (no local
# a ejecutar()) porque tanto el loop principal como ciclo_ninja() necesitan
# leerlo y refrescarlo. Antes este refresco solo vivía dentro del while
# principal, y como ciclo_ninja() bloquea ese while por toda la duración del
# trade (puede ser días), el precio de ATOM y los saldos quedaban congelados
# mientras hubiera un trade activo — que con el escaneo multi-cripto es la
# mayoría del tiempo.
_runtime = {
    'precio_usd': None, 'precio_ref': None, 'tc': 17.5, 'saldos': {},
    'alertas_disp': set(),
    'ts_precio': 0.0, 'ts_blockchain': 0.0, 'ts_save': 0.0, 'ts_rewards': 0.0,
}

def housekeeping_atom(forzar=False):
    """Refresca precio ATOM (cada 5 min), saldos blockchain (cada hora) y
    persiste estado_atom.json (cada 30s o si algo cambió). Se llama tanto
    desde el loop principal como desde dentro de ciclo_ninja, para que el
    dashboard y /atom nunca queden con datos de hace horas/días."""
    ahora = time.time()
    cambios = False

    if forzar or ahora-_runtime['ts_precio']>=5*60:
        _runtime['ts_precio']=ahora
        nuevo=obtener_precio_atom_usd(); nuevo_tc=obtener_tipo_cambio_mxn()
        if nuevo:
            _runtime['precio_usd']=nuevo; _runtime['tc']=nuevo_tc
            if not _runtime['precio_ref']: _runtime['precio_ref']=nuevo
            _runtime['alertas_disp']=verificar_alertas_atom(nuevo,_runtime['precio_ref'],nuevo_tc,_runtime['alertas_disp'])
            cambio=(nuevo-_runtime['precio_ref'])/_runtime['precio_ref']*100
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ATOM ${nuevo:.4f} ({cambio:+.2f}%)")
            cambios = True

    if ahora-_runtime['ts_blockchain']>=60*60:
        _runtime['ts_blockchain']=ahora
        nuevos=consultar_saldos_blockchain_atom()
        if nuevos:
            _runtime['saldos']=nuevos
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Blockchain: {nuevos.get('staking',0):.2f} ATOM staked")
            cambios = True

    if ahora-_runtime['ts_rewards']>=60*60:
        _runtime['ts_rewards']=ahora
        try:
            from historial_rewards import obtener_historial_rewards
            obtener_historial_rewards()  # refresca el caché aquí, en el fondo — nunca en una ruta de petición
        except Exception as e:
            print(f"⚠️ Error refrescando histórico de rewards: {e}")

    if cambios or ahora-_runtime['ts_save']>=30:
        _runtime['ts_save']=ahora
        estado_t=cargar_estado_trading()
        guardar_estado_atom({
            "precio_actual":_runtime['precio_usd'],"precio_ref":_runtime['precio_ref'],"tc":_runtime['tc'],
            "saldos":_runtime['saldos'],"alertas_disparadas":list(_runtime['alertas_disp']),
            "ultima_actualizacion":datetime.now().isoformat(),"trading":estado_t,
        })

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
    activo = snap.get('activo', snap.get('simbolo','?').replace('USDT',''))
    cap_ef = 10_000 * CFG['apalancamiento']
    SEP = "━━━━━━━━━━━━━━━━━━━"
    return "\n".join([
        f"{emoji} *TRADE ABIERTO — {activo} {tipo.upper()}*", SEP,
        f"Precio entrada: *${precio:.6f}* USD (${precio*tc:.4f} MXN)",
        f"Capital: *${10_000:,} MXN* × {CFG['apalancamiento']}x = *${cap_ef:,} MXN*",
        f"Stop: *{CFG['stop_atr_mult']}×ATR* | Objetivo: *{CFG['objetivo_atr_mult']}×ATR*",
        f"RSI entrada: *{snap['rsi']:.1f}* | F&G: *{snap['fng']}*",
        f"Mercado: *{snap['mercado']}*", SEP,
        "🥷 Modo NINJA activado — monitoreo cada 2 min",
    ])

def msg_trade_cerrado(resultado, tc):
    emoji = "✅" if resultado['ganador'] else "🔴"
    activo = resultado.get('activo', resultado.get('simbolo','?').replace('USDT',''))
    pnl=resultado['pnl_pct']; gmxn=resultado['ganancia_mxn']
    SEP="━━━━━━━━━━━━━━━━━━━"; res=resumen_completo(tc)
    return "\n".join([
        f"{emoji} *TRADE CERRADO — {activo} {resultado['tipo'].upper()}*", SEP,
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
    simbolo = snap_inicial.get('simbolo', 'ADAUSDT')
    activo = snap_inicial.get('activo', simbolo.replace('USDT',''))
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 NINJA activo — {activo} {tipo.upper()}")

    # ts_inicio se ancla a la fecha_entrada REAL del trade (no a time.time() del
    # momento en que arranca este ciclo) — así el contador de bars_transcurridas
    # y el timeout de max_bars son correctos tanto en arranque normal (fecha_entrada
    # es prácticamente "ahora") como al retomar un trade que quedó huérfano tras
    # un reinicio del bot (fecha_entrada puede ser de días atrás).
    trade0 = cargar_estado_trading().get('trade_actual') or {}
    try:
        ts_inicio = datetime.fromisoformat(trade0['fecha_entrada']).timestamp()
    except (KeyError, ValueError, TypeError):
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
                procesar(cmd, _runtime['saldos'], _runtime['precio_usd'] or 0, tc, _runtime['precio_ref'] or 0,
                         ALERTAS_CONFIG, estado_t, resumen_completo(tc))

        # Precio ATOM/saldos/estado_atom.json — el while principal está
        # bloqueado mientras dure este trade, así que hay que refrescarlos
        # aquí también (housekeeping_atom se autolimita por sus propios
        # timers, es barato llamarlo en cada vuelta de 15s)
        housekeeping_atom()

        # Evaluar salida cada ~120s reales (no bloquea el resto)
        if ahora - ts_ultimo_check_precio >= 120:
            ts_ultimo_check_precio = ahora
            p = precio_actual(simbolo)
            if p:
                estado_t = cargar_estado_trading()
                if not estado_t.get('en_trade'):
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade cerrado externamente")
                    return

                snap = snapshot_actual(simbolo, tc) or snap_inicial
                snap['precio'] = p

                trade = estado_t['trade_actual']
                trade['precio_max'] = max(trade.get('precio_max',p), p)
                trade['precio_min'] = min(trade.get('precio_min',p), p)
                trade['bars_transcurridas'] = int((ahora-ts_inicio)/(4*3600))

                debe_salir, razon = señal_salida(tipo, p, trade, snap)

                pe=trade['precio_entrada']
                pnl = (p-pe)/pe*100 if tipo=='long' else (pe-p)/pe*100
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🥷 {activo} {tipo.upper()} "
                      f"P&L:{pnl:+.2f}% | {activo}:${p:.5f} | F&G:{snap.get('fng',50)}")

                if debe_salir:
                    resultado = cerrar_trade(p, razon, tc)
                    if resultado:
                        enviar(msg_trade_cerrado(resultado, tc))
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] Trade cerrado: {razon} | P&L:{resultado['pnl_pct']:+.2f}%")
                    return

        time.sleep(15)  # mismo ritmo que el loop principal — responsive a Telegram

    p = precio_actual(simbolo) or snap_inicial['precio']
    resultado = cerrar_trade(p, "tiempo_maximo", tc)
    if resultado: enviar(msg_trade_cerrado(resultado, tc))

def ciclo_vigilancia(tc):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Evaluando señales en {len(ACTIVOS_ESCANEO)} activos "
          f"({', '.join(s.replace('USDT','') for s in ACTIVOS_ESCANEO)})...")
    resultados = []
    for simbolo in ACTIVOS_ESCANEO:
        snap = snapshot_actual(simbolo, tc)
        if not snap:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Sin datos de mercado para {simbolo}")
            resultados.append({"simbolo": simbolo, "activo": simbolo.replace("USDT",""), "error": True})
            continue

        tipo = elegir_estrategia(snap)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] "
              f"{snap['activo']}:${snap['precio']:.5f} RSI:{snap['rsi']:.1f} "
              f"ST:{snap['supertrend']}(prev:{snap['st_prev']}) F&G:{snap['fng']} "
              f"Mercado:{snap['mercado']} → {tipo or 'ESPERAR'}")
        resultados.append({
            "simbolo": simbolo, "activo": snap['activo'], "precio": snap['precio'],
            "rsi": snap['rsi'], "supertrend": snap['supertrend'], "fng": snap['fng'],
            "mercado": snap['mercado'], "señal": tipo,
        })

        if tipo:
            p = precio_actual(simbolo) or snap['precio']
            trade = abrir_trade(tipo, p, snap, tc)
            snap['_tipo_trade'] = tipo
            enviar(msg_trade_abierto(tipo, p, snap, tc))
            # el resto de la lista de prioridad ni se evalúa — este activo ya ganó el ciclo
            guardar_ultimo_escaneo(resultados, ganador=simbolo)
            return snap

    guardar_ultimo_escaneo(resultados, ganador=None)
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
    _runtime['precio_ref'] = estado_atom.get("precio_ref")
    _runtime['alertas_disp'] = set(estado_atom.get("alertas_disparadas", []))
    # Semilla de saldos desde el último valor guardado en disco -- si la
    # primera consulta en vivo (abajo) falla justo al arrancar (red aún
    # inestable, Cosmos caído, etc.), esto evita mostrar 0.00 en todo
    # mientras no se recupera; se mantiene el último saldo real conocido.
    _runtime['saldos'] = estado_atom.get("saldos") or {}
    _runtime['tc'] = obtener_tipo_cambio_mxn()
    _ts_trading = 0.0
    housekeeping_atom(forzar=True)  # precio/saldos frescos desde el primer segundo, no esperar 5 min

    enviar(msg_bienvenida())

    # Retomar un trade que haya quedado abierto de una corrida anterior —
    # sin esto, un reinicio con en_trade=True deja el trade huérfano para
    # siempre (nada más vuelve a llamar ciclo_ninja mientras en_trade siga
    # True), sin vigilancia de stop/objetivo/tiempo_maximo/btc_emergencia.
    estado_t_inicial = cargar_estado_trading()
    trade_previo = estado_t_inicial.get('trade_actual')
    if estado_t_inicial.get('en_trade') and trade_previo:
        activo_previo = trade_previo.get('activo', trade_previo.get('simbolo','ADAUSDT').replace('USDT',''))
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔄 RETOMANDO trade abierto de una corrida anterior: "
              f"{activo_previo} {trade_previo.get('tipo','?').upper()} — "
              f"entrada ${trade_previo.get('precio_entrada',0):.6f} desde {trade_previo.get('fecha_entrada','?')[:16].replace('T',' ')} "
              f"— activando modo NINJA de inmediato")
        snap_resume = {
            '_tipo_trade': trade_previo.get('tipo'),
            'simbolo':     trade_previo.get('simbolo', 'ADAUSDT'),
            'activo':      activo_previo,
            'precio':      trade_previo.get('precio_entrada', 0),
        }
        ciclo_ninja(snap_resume, _runtime['tc'])
        _ts_trading = time.time()
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Trade retomado se cerró (o cumplió tiempo_maximo) — vuelve la vigilancia normal")

    while True:
        try:
            ahora = time.time()
            comandos = escuchar()
            if comandos:
                estado_t = cargar_estado_trading()
                for cmd in comandos:
                    procesar(cmd, _runtime['saldos'], _runtime['precio_usd'] or 0, _runtime['tc'], _runtime['precio_ref'] or 0,
                             ALERTAS_CONFIG, estado_t, resumen_completo(_runtime['tc']))

            housekeeping_atom()

            estado_t = cargar_estado_trading()
            if not estado_t.get('en_trade') and ahora-_ts_trading>=15*60:
                _ts_trading=ahora
                snap = ciclo_vigilancia(_runtime['tc'])
                if snap:
                    ciclo_ninja(snap, _runtime['tc'])
                    _ts_trading=time.time()

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
