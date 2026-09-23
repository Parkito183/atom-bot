#!/usr/bin/env python3
"""
smoke_test.py — Verificación rápida post-reinicio del bot.

Corre una batería de chequeos de sanidad sobre el servicio, el dashboard
y el estado guardado, para no depender de revisar todo a mano cada vez
que se reinicia el bot. Es de solo lectura — no modifica nada, no llama
al motor de trading en vivo (usa lo que YA está corriendo/guardado).

Uso:
    python3 smoke_test.py            # corre todos los chequeos
    python3 smoke_test.py -v         # además imprime detalle de cada uno

Exit code 0 si todo pasó, 1 si algún chequeo FALLÓ (los WARN no cuentan
como falla — son cosas a mirar pero no necesariamente rotas).
"""
import json, os, subprocess, sys, urllib.request
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DASHBOARD_URL = "http://127.0.0.1:8080"
VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv

# Piso conocido del histórico de rewards — nunca debe verse por debajo de
# esto salvo que sea un reinicio limpio de la wallet (no es el caso aquí).
# Ver historial_rewards.py — se actualiza si el histórico crece de verdad.
REWARDS_FLOOR = 72.291859

resultados = []  # (nombre, 'OK'|'FALLO'|'WARN', mensaje)

def check(nombre):
    def decorator(fn):
        def wrapper():
            try:
                estado, msg = fn()
            except Exception as e:
                estado, msg = "FALLO", f"excepción durante el chequeo: {e}"
            resultados.append((nombre, estado, msg))
            if VERBOSE or estado != "OK":
                icono = {"OK": "✅", "FALLO": "🔴", "WARN": "⚠️"}[estado]
                print(f"{icono} {nombre}: {msg}")
        return wrapper
    return decorator

def _get_json(path, timeout=8):
    req = urllib.request.Request(f"{DASHBOARD_URL}{path}", headers={"User-Agent": "smoke_test"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())

def _cargar_json(path):
    return json.load(open(path))


@check("1. Servicio systemd activo")
def chk_servicio():
    r = subprocess.run(["systemctl", "--user", "is-active", "atom-bot"],
                        capture_output=True, text=True)
    activo = r.stdout.strip()
    if activo != "active":
        return "FALLO", f"systemctl reporta '{activo}', se esperaba 'active'"
    return "OK", "active"

@check("2. Procesos main.py y dashboard.py corriendo")
def chk_procesos():
    r = subprocess.run(["pgrep", "-f", "main.py"], capture_output=True, text=True)
    main_pids = [p for p in r.stdout.split() if p]
    r2 = subprocess.run(["pgrep", "-f", "dashboard.py"], capture_output=True, text=True)
    dash_pids = [p for p in r2.stdout.split() if p]
    if not main_pids:
        return "FALLO", "no hay proceso main.py corriendo"
    if not dash_pids:
        return "FALLO", "no hay proceso dashboard.py corriendo"
    return "OK", f"main.py pid={main_pids[0]} | dashboard.py pid={dash_pids[0]}"

@check("3. Endpoint /api responde")
def chk_api():
    status, data = _get_json("/api")
    if status != 200:
        return "FALLO", f"HTTP {status}"
    faltantes = [k for k in ("atom", "trading", "historial") if k not in data]
    if faltantes:
        return "FALLO", f"faltan claves en la respuesta: {faltantes}"
    return "OK", "HTTP 200, estructura completa"

@check("4. Endpoint /api/senal responde")
def chk_api_senal():
    status, data = _get_json("/api/senal")
    if status != 200:
        return "FALLO", f"HTTP {status}"
    return "OK", "HTTP 200"

@check("5. Precio ATOM no está congelado (housekeeping vivo)")
def chk_atom_fresco():
    estado = _cargar_json(os.path.join(LOGS_DIR, "estado_atom.json"))
    ts = estado.get("ultima_actualizacion")
    if not ts:
        return "FALLO", "estado_atom.json sin 'ultima_actualizacion'"
    edad_min = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 60
    if edad_min > 10:
        return "FALLO", f"último guardado hace {edad_min:.0f} min (>10) — housekeeping pudo congelarse"
    return "OK", f"actualizado hace {edad_min:.1f} min"

@check("6. Trade activo: campos completos y dirección stop/objetivo coherente")
def chk_trade_coherente():
    estado_t = _cargar_json(os.path.join(LOGS_DIR, "estado_trading.json"))
    if not estado_t.get("en_trade"):
        return "OK", "sin trade abierto (modo vigilancia)"
    trade = estado_t.get("trade_actual") or {}
    faltantes = [k for k in ("simbolo", "activo", "tipo", "precio_entrada", "stop", "objetivo")
                 if trade.get(k) in (None, "")]
    if faltantes:
        return "FALLO", f"trade_actual sin campos: {faltantes}"
    tipo = trade["tipo"]; pe = trade["precio_entrada"]; stop = trade["stop"]; obj = trade["objetivo"]
    if tipo == "long" and not (stop < pe < obj):
        return "FALLO", f"LONG con stop/objetivo invertidos (stop={stop} entrada={pe} obj={obj})"
    if tipo == "short" and not (obj < pe < stop):
        return "FALLO", f"SHORT con stop/objetivo invertidos (obj={obj} entrada={pe} stop={stop})"
    return "OK", f"{trade['activo']} {tipo} — entrada {pe}, stop {stop}, objetivo {obj}"

@check("7. P&L en vivo coincide con recálculo manual (pnl_neto)")
def chk_pnl_correcto():
    status, data = _get_json("/api")
    tr = data["trading"]
    if not tr.get("en_trade") or not tr.get("trade_actual"):
        return "OK", "sin trade abierto, no aplica"
    p_actual = tr.get("activo_precio_actual")
    if not p_actual:
        return "WARN", "activo_precio_actual vacío — no se pudo consultar el precio en vivo"
    sys.path.insert(0, BASE_DIR)
    from trading.estrategias import pnl_neto
    trade = tr["trade_actual"]
    esperado = pnl_neto(trade["tipo"], trade["precio_entrada"], p_actual)
    reportado = tr.get("pnl_actual")
    if reportado is None:
        return "FALLO", "pnl_actual ausente en /api"
    if abs(esperado - reportado) > 0.01:
        return "FALLO", (f"pnl_actual={reportado:.4f}% pero pnl_neto() manual da {esperado:.4f}% "
                          f"(diferencia {abs(esperado-reportado):.4f}pp — ¿volvió el bug de comisión no restada?)")
    return "OK", f"pnl_actual={reportado:.4f}% coincide con pnl_neto() manual"

@check("8. Histórico de rewards de ATOM no bajó del piso conocido")
def chk_rewards_historico():
    sys.path.insert(0, BASE_DIR)
    # Lectura de solo-caché, igual que dashboard/Telegram — el refresco en
    # vivo corre aparte en housekeeping_atom(), no debe bloquear este check.
    from historial_rewards import obtener_historial_rewards_cache
    hist = obtener_historial_rewards_cache()
    total = hist.get("total_atom", 0.0)
    if total < REWARDS_FLOOR - 1e-6:
        return "FALLO", (f"total_atom={total:.6f} ATOM, por DEBAJO del piso conocido "
                          f"({REWARDS_FLOOR}) — el histórico no puede bajar, revisar historial_rewards.py")
    nota = hist.get("nota")
    if nota:
        return "WARN", f"{total:.4f} ATOM (>= piso, OK) pero con nota: {nota}"
    return "OK", f"{total:.4f} ATOM"

@check("9. Balance acumulado consistente con el historial de trades")
def chk_balance_consistente():
    estado_t = _cargar_json(os.path.join(LOGS_DIR, "estado_trading.json"))
    hist_path = os.path.join(LOGS_DIR, "historial_trades.json")
    if not os.path.exists(hist_path):
        return "WARN", "sin historial_trades.json todavía (0 trades cerrados)"
    hist = _cargar_json(hist_path)
    suma = sum(t.get("ganancia_mxn", 0) for t in hist)
    balance = estado_t.get("balance_mxn", 0)
    if abs(suma - balance) > 1.0:  # tolerancia de redondeo
        return "FALLO", f"balance_mxn={balance:.2f} pero suma de historial={suma:.2f} (diff {abs(suma-balance):.2f})"
    return "OK", f"balance_mxn={balance:.2f} MXN, {len(hist)} trades cerrados, consistente"

@check("10. Sin errores/tracebacks en los últimos 10 minutos de journal")
def chk_journal_sin_errores():
    r = subprocess.run(
        ["journalctl", "--user", "-u", "atom-bot", "--no-pager", "--since", "-10 min"],
        capture_output=True, text=True)
    lineas = r.stdout.splitlines()
    sospechosas = [l for l in lineas if "Traceback" in l or "⚠️ Error:" in l]
    if sospechosas:
        return "WARN", f"{len(sospechosas)} línea(s) con error en los últimos 10 min (revisar journalctl)"
    return "OK", f"{len(lineas)} líneas revisadas, sin errores"


def main():
    for fn in (chk_servicio, chk_procesos, chk_api, chk_api_senal, chk_atom_fresco,
               chk_trade_coherente, chk_pnl_correcto, chk_rewards_historico,
               chk_balance_consistente, chk_journal_sin_errores):
        fn()

    oks = sum(1 for _, e, _ in resultados if e == "OK")
    warns = sum(1 for _, e, _ in resultados if e == "WARN")
    fallos = sum(1 for _, e, _ in resultados if e == "FALLO")

    print(f"\n{'='*60}")
    print(f"SMOKE TEST — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    for nombre, estado, msg in resultados:
        icono = {"OK": "✅", "FALLO": "🔴", "WARN": "⚠️"}[estado]
        print(f"{icono} {nombre}")
        if estado != "OK" or VERBOSE:
            print(f"     {msg}")
    print(f"{'='*60}")
    print(f"{oks} OK | {warns} WARN | {fallos} FALLO")

    if fallos:
        print("\n🔴 HAY FALLOS — revisar antes de dar por bueno el reinicio.")
        return 1
    if warns:
        print("\n⚠️  Todo pasó, pero hay advertencias que vale la pena mirar.")
        return 0
    print("\n✅ Todo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
