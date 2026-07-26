"""
blockchain.py — Consulta de wallet ATOM en Cosmos + DOT en Binance.
"""
import urllib.request
import json
from datetime import datetime, timezone, timedelta

# ════════════════════════════════════════════
#  ATOM — COSMOS
# ════════════════════════════════════════════

DIRECCION_COSMOS = "cosmos10a7ltaarzfclmk8mdthcrpafseqeerekzlxln4"
DIAS_UNBONDING   = 21  # Cosmos Hub tiene 21 días de unbonding

def consultar_saldos_blockchain_atom() -> dict:
    """Consulta disponible, staking, rewards, unbonding y validadores."""
    disponible = 0.0
    staking    = 0.0
    rewards    = 0.0
    unbonding  = 0.0
    unbonding_fin = None
    validadores   = []
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        # 1. Balance disponible
        url = f"https://rest.cosmos.directory/cosmoshub/cosmos/bank/v1beta1/balances/{DIRECCION_COSMOS}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            data = json.loads(r.read())
            for b in data.get("balances", []):
                if b["denom"] == "uatom":
                    disponible = float(b["amount"]) / 1_000_000

        # 2. Delegaciones (staking) y validadores
        url = f"https://rest.cosmos.directory/cosmoshub/cosmos/staking/v1beta1/delegations/{DIRECCION_COSMOS}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            data = json.loads(r.read())
            for d in data.get("delegation_responses", []):
                staking += float(d["balance"]["amount"]) / 1_000_000
                val_addr = d.get("delegation", {}).get("validator_address", "")
                if val_addr:
                    validadores.append(val_addr)

        # 3. Rewards pendientes
        url = f"https://rest.cosmos.directory/cosmoshub/cosmos/distribution/v1beta1/delegators/{DIRECCION_COSMOS}/rewards"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            data = json.loads(r.read())
            for res in data.get("total", []):
                if res["denom"] == "uatom":
                    rewards = float(res["amount"]) / 1_000_000

        # 4. Unbonding (unstaking en proceso)
        url = f"https://rest.cosmos.directory/cosmoshub/cosmos/staking/v1beta1/delegators/{DIRECCION_COSMOS}/unbonding_delegations"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            data = json.loads(r.read())
            for ub in data.get("unbonding_responses", []):
                for entry in ub.get("entries", []):
                    unbonding += float(entry.get("balance", 0)) / 1_000_000
                    # Fecha de completion
                    completion = entry.get("completion_time", "")
                    if completion:
                        try:
                            # Formato: "2026-04-23T14:30:00Z"
                            dt = datetime.fromisoformat(
                                completion.replace("Z", "+00:00")
                            )
                            if unbonding_fin is None or dt < unbonding_fin:
                                unbonding_fin = dt
                        except Exception:
                            pass

        # 5. Nombres de validadores
        nombres_val = []
        for val_addr in validadores[:3]:
            try:
                url_v = f"https://rest.cosmos.directory/cosmoshub/cosmos/staking/v1beta1/validators/{val_addr}"
                with urllib.request.urlopen(
                    urllib.request.Request(url_v, headers=headers), timeout=8
                ) as r:
                    vdata = json.loads(r.read())
                    moniker = vdata.get("validator", {}).get("description", {}).get("moniker", val_addr[:12])
                    nombres_val.append(moniker)
            except Exception:
                nombres_val.append(val_addr[:12] + "...")
        validadores = nombres_val

    except Exception as e:
        print(f"⚠️ Error consultando blockchain ATOM: {e}")

    return {
        "disponible":    disponible,
        "staking":       staking,
        "rewards":       rewards,
        "unbonding":     unbonding,
        "unbonding_fin": unbonding_fin,
        "validadores":   nombres_val if 'nombres_val' in locals() else [],
    }


def consultar_ultimas_txs_atom(n: int = 3) -> list:
    """Transacciones temporalmente no disponibles — APIs públicas de Cosmos
    no soportan búsqueda por eventos en este momento."""
    return []


def obtener_precio_atom_usd() -> float | None:
    """Precio ATOM en USD desde Binance."""
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=ATOMUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return float(data["price"])
    except Exception:
        return None


# ════════════════════════════════════════════
#  TIPO DE CAMBIO USD → MXN
# ════════════════════════════════════════════

_tc_cache = {"valor": None, "ts": 0}

def obtener_tipo_cambio_mxn() -> float:
    import time
    ahora = time.time()
    if _tc_cache["valor"] and (ahora - _tc_cache["ts"]) < 300:
        return _tc_cache["valor"]
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        req = urllib.request.Request(
            "https://api.bitso.com/v3/ticker?book=usd_mxn", headers=headers
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            tc = float(json.loads(r.read())["payload"]["last"])
            _tc_cache["valor"] = tc
            _tc_cache["ts"]    = ahora
            return tc
    except Exception:
        return _tc_cache["valor"] or 17.50

def usd_a_mxn(usd: float) -> float:
    return round(usd * obtener_tipo_cambio_mxn(), 2)


# ════════════════════════════════════════════
#  DOT — POLKADOT
# ════════════════════════════════════════════

def obtener_precio_dot_usd() -> float | None:
    try:
        url = "https://api.binance.com/api/v3/ticker/price?symbol=DOTUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return float(data["price"])
    except Exception:
        return None

def obtener_stats_dot_24h() -> dict:
    try:
        url = "https://api.binance.com/api/v3/ticker/24hr?symbol=DOTUSDT"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            return {
                "cambio_pct": float(data["priceChangePercent"]),
                "precio_max": float(data["highPrice"]),
                "precio_min": float(data["lowPrice"]),
                "volumen":    float(data["volume"]),
            }
    except Exception:
        return {}
