"""
historial_rewards.py — Histórico de rewards de staking ATOM ya reclamados.

Los rewards de esta wallet se retiran vía un servicio de auto-restake
(authz: MsgExec → MsgWithdrawDelegatorReward + MsgDelegate), no manualmente.
cosmos.directory no soporta búsqueda de txs por eventos (ver blockchain.py),
así que aquí se usa un LCD que sí la soporta y se filtra el evento
"withdraw_rewards" por el atributo delegator, ya que cada tx del restake
agrupa los reclamos de muchos delegadores.
"""
import urllib.request, json, os, time
from datetime import datetime

from blockchain import DIRECCION_COSMOS

_LCD = "https://cosmos-rest.publicnode.com"
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_FILE = os.path.join(_BASE_DIR, "logs", "historial_rewards.json")
_CACHE_TTL = 3600  # 1h — evita golpear el LCD en cada consulta del bot/dashboard


def _fetch_pagina(offset: int, limit: int = 100) -> dict:
    url = (f"{_LCD}/cosmos/tx/v1beta1/txs"
           f"?query=withdraw_rewards.delegator%3D%27{DIRECCION_COSMOS}%27"
           f"&pagination.limit={limit}&pagination.offset={offset}&order_by=ORDER_BY_DESC")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())


def _calcular_historial() -> dict:
    total_uatom = 0
    num_claims = 0
    primera_fecha = None
    ultima_fecha = None
    offset, limit = 0, 100

    while True:
        data = _fetch_pagina(offset, limit)
        tx_responses = data.get("tx_responses", [])
        if not tx_responses:
            break
        for tr in tx_responses:
            ts = tr.get("timestamp", "")
            for ev in tr.get("events", []):
                if ev.get("type") != "withdraw_rewards":
                    continue
                attrs = {a["key"]: a["value"] for a in ev.get("attributes", [])}
                if attrs.get("delegator") != DIRECCION_COSMOS:
                    continue
                amount = attrs.get("amount", "")
                if amount.endswith("uatom"):
                    total_uatom += int(amount[:-len("uatom")] or 0)
                    num_claims += 1
                    if ts:
                        ultima_fecha = ultima_fecha or ts
                        primera_fecha = ts

        offset += limit
        if offset >= int(data.get("total", "0")):
            break

    return {
        "total_atom":    total_uatom / 1_000_000,
        "num_claims":    num_claims,
        "primera_fecha": primera_fecha,
        "ultima_fecha":  ultima_fecha,
        "actualizado":   datetime.now().isoformat(),
    }


def obtener_historial_rewards(forzar: bool = False) -> dict:
    """Total histórico de ATOM reclamado por staking (rewards ya retirados)."""
    if not forzar and os.path.exists(_CACHE_FILE):
        try:
            cache = json.load(open(_CACHE_FILE))
            edad = time.time() - datetime.fromisoformat(cache["actualizado"]).timestamp()
            if edad < _CACHE_TTL:
                return cache
        except Exception:
            pass

    try:
        historial = _calcular_historial()
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        with open(_CACHE_FILE, "w") as f:
            json.dump(historial, f, indent=2)
        return historial
    except Exception as e:
        print(f"⚠️ Error consultando histórico de rewards: {e}")
        if os.path.exists(_CACHE_FILE):
            try:
                return json.load(open(_CACHE_FILE))
            except Exception:
                pass
        return {"total_atom": 0.0, "num_claims": 0, "primera_fecha": None, "ultima_fecha": None}


if __name__ == "__main__":
    print(json.dumps(obtener_historial_rewards(forzar=True), indent=2))
