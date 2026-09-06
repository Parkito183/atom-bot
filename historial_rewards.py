"""
historial_rewards.py — Histórico de rewards de staking ATOM ya reclamados.

Los rewards de esta wallet se retiran vía un servicio de auto-restake
(authz: MsgExec → MsgWithdrawDelegatorReward + MsgDelegate), no manualmente.

IMPORTANTE (hallazgo 2026-09-06): los nodos LCD públicos de Cosmos Hub PODAN
su índice de transacciones — no retienen el histórico completo indefinidamente
("cosmos-rest.publicnode.com" llegó a devolver total=0 para una wallet con 41+
retiros reales confirmados, sin ningún error HTTP; cosmos.directory confirmó
explícitamente "lowest height is X" para un bloque ya podado). Por eso este
módulo NO vuelve a calcular el total desde cero en cada consulta — eso asume
que la fuente retiene todo el historial, cosa que ya no es cierta. En vez de
eso, ACUMULA de forma incremental sobre la última cifra confirmada: cada
consulta en vivo solo busca retiros con fecha POSTERIOR al último ya contado,
y los SUMA a la base. El total nunca se reemplaza, solo puede crecer — así
una fuente podada o degradada (que devuelve 0 resultados nuevos) simplemente
no aporta nada nuevo, en vez de contaminar el histórico con un cero falso.

Se prueban varias fuentes LCD en orden (con reintentos en cada una) porque
la disponibilidad/retención de cada nodo público es inconsistente.
"""
import urllib.request, json, os, time
from datetime import datetime, timezone

from blockchain import DIRECCION_COSMOS

_LCDS = [
    "https://cosmos-rest.publicnode.com",
    "https://rest.lavenderfive.com:443/cosmoshub",
]
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_FILE = os.path.join(_BASE_DIR, "logs", "historial_rewards.json")
_CACHE_TTL = 3600  # 1h — evita golpear el LCD en cada consulta del bot/dashboard
_REINTENTOS = 3
_ESPERA_REINTENTO = 3  # segundos; se duplica en cada reintento

# Base sembrada manualmente el 2026-09-06 tras la corrupción del caché.
# Origen: 69.17 ATOM / 41 retiros confirmados hasta 2026-08-03 (última cifra
# buena vista antes de que el caché se sobreescribiera con 0), + 1 retiro
# nuevo de 3.121859 ATOM el 2026-08-31 encontrado en rest.lavenderfive.com
# (verificado: no estaba contado en los 41 anteriores). Reconciliado contra
# el "ganado total" que muestra la app de Exodus (75.0349 ATOM = 72.29
# reclamado + 2.75 pendiente sin reclamar en ese momento — diferencia de
# solo 0.0045 ATOM, dentro del margen de la cifra aproximada de origen).
_SEED = {
    "total_atom":  72.291859,
    "num_claims":  42,
    "primera_fecha": "2025-12-15T20:23:31Z",
    "ultima_fecha":  "2026-08-31T14:37:54Z",
    "actualizado":   "2026-09-06T00:00:00",
}


def _fetch_pagina(lcd: str, offset: int, limit: int = 100) -> dict:
    url = (f"{lcd}/cosmos/tx/v1beta1/txs"
           f"?query=withdraw_rewards.delegator%3D%27{DIRECCION_COSMOS}%27"
           f"&pagination.limit={limit}&pagination.offset={offset}&order_by=ORDER_BY_DESC")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    # Una respuesta sin estos campos es una respuesta degradada/de error
    # disfrazada de 200 OK — no debe tratarse como "cero retiros reales".
    if "tx_responses" not in data or "total" not in data:
        raise ValueError(f"respuesta sin la estructura esperada: {data}")
    return data


def _fetch_pagina_con_reintentos(lcd: str, offset: int, limit: int = 100) -> dict:
    espera = _ESPERA_REINTENTO
    ultimo_error = None
    for intento in range(1, _REINTENTOS + 1):
        try:
            return _fetch_pagina(lcd, offset, limit)
        except Exception as e:
            ultimo_error = e
            print(f"⚠️ historial_rewards: {lcd} intento {intento}/{_REINTENTOS} falló ({e})")
            if intento < _REINTENTOS:
                time.sleep(espera)
                espera *= 2
    raise ultimo_error


def _buscar_retiros_nuevos(ultima_fecha_conocida: str | None) -> dict:
    """Recorre las fuentes LCD (en orden) y junta los retiros con fecha
    POSTERIOR a ultima_fecha_conocida. No exige que ninguna fuente tenga el
    historial completo — solo que alguna vea lo reciente."""
    limite_dt = None
    if ultima_fecha_conocida:
        limite_dt = datetime.fromisoformat(ultima_fecha_conocida.replace("Z", "+00:00"))

    errores = []
    for lcd in _LCDS:
        try:
            nuevo_uatom = 0
            nuevos_claims = 0
            ultima_fecha_vista = None
            offset, limit = 0, 100
            paginas = 0
            while paginas < 10:  # tope de seguridad, nunca deberíamos necesitar tantas
                data = _fetch_pagina_con_reintentos(lcd, offset, limit)
                tx_responses = data.get("tx_responses", [])
                if not tx_responses:
                    break
                detenerse = False
                for tr in tx_responses:
                    ts = tr.get("timestamp", "")
                    ts_dt = None
                    if ts:
                        try:
                            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        except ValueError:
                            ts_dt = None
                    if limite_dt and ts_dt and ts_dt <= limite_dt:
                        # order_by=DESC -> de aquí en adelante todo es más viejo, ya contado
                        detenerse = True
                        break
                    for ev in tr.get("events", []):
                        if ev.get("type") != "withdraw_rewards":
                            continue
                        attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
                        if attrs.get("delegator") != DIRECCION_COSMOS:
                            continue
                        amount = attrs.get("amount", "")
                        if amount.endswith("uatom"):
                            nuevo_uatom += int(amount[:-len("uatom")] or 0)
                            nuevos_claims += 1
                            if ts:
                                ultima_fecha_vista = max(ultima_fecha_vista or ts, ts)
                if detenerse:
                    break
                paginas += 1
                offset += limit
                if offset >= int(data.get("total", "0")):
                    break

            return {
                "fuente": lcd,
                "nuevo_atom": nuevo_uatom / 1_000_000,
                "nuevos_claims": nuevos_claims,
                "ultima_fecha_vista": ultima_fecha_vista,
            }
        except Exception as e:
            errores.append(f"{lcd}: {e}")
            continue

    raise RuntimeError(f"Todas las fuentes LCD fallaron: {'; '.join(errores)}")


def _cargar_cache() -> dict | None:
    if os.path.exists(_CACHE_FILE):
        try:
            return json.load(open(_CACHE_FILE))
        except Exception:
            return None
    return None


def obtener_historial_rewards(forzar: bool = False) -> dict:
    """Total histórico de ATOM reclamado por staking (rewards ya retirados).
    Acumula de forma incremental: nunca reemplaza el total, solo lo hace
    crecer con retiros nuevos verificados. Si la consulta en vivo falla o no
    encuentra nada nuevo, se conserva el último valor bueno conocido."""
    cache = _cargar_cache() or dict(_SEED)

    if not forzar:
        try:
            edad = time.time() - datetime.fromisoformat(cache["actualizado"]).timestamp()
            if edad < _CACHE_TTL:
                return cache
        except Exception:
            pass

    try:
        hallazgo = _buscar_retiros_nuevos(cache.get("ultima_fecha"))
        actualizado = dict(cache)
        if hallazgo["nuevos_claims"] > 0:
            actualizado["total_atom"] = cache.get("total_atom", 0.0) + hallazgo["nuevo_atom"]
            actualizado["num_claims"] = cache.get("num_claims", 0) + hallazgo["nuevos_claims"]
            actualizado["ultima_fecha"] = hallazgo["ultima_fecha_vista"] or cache.get("ultima_fecha")
            print(f"✅ historial_rewards: +{hallazgo['nuevo_atom']:.6f} ATOM nuevos "
                  f"({hallazgo['nuevos_claims']} retiro(s)) vía {hallazgo['fuente']}")
        actualizado["actualizado"] = datetime.now().isoformat()
        actualizado.pop("nota", None)
        actualizado.pop("error_ultima_consulta", None)
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump(actualizado, f, indent=2)
        return actualizado

    except Exception as e:
        print(f"⚠️ Error consultando histórico de rewards: {e}")
        resultado = dict(cache)
        try:
            edad_h = (time.time() - datetime.fromisoformat(cache["actualizado"]).timestamp()) / 3600
            edad_txt = f"hace {edad_h:.1f}h"
        except Exception:
            edad_txt = "de fecha desconocida"
        resultado["error_ultima_consulta"] = str(e)
        resultado["nota"] = (f"⚠️ Consulta en vivo falló — mostrando último dato confirmado "
                              f"({edad_txt}), no se perdió ni se sobrescribió el histórico.")
        return resultado


if __name__ == "__main__":
    print(json.dumps(obtener_historial_rewards(forzar=True), indent=2, ensure_ascii=False))
