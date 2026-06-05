"""Runtime loader for the encrypted prediction model.

Decrypts engine.enc (algorithm) and params.enc (trained parameters) using the
key from the WORLDCUP_KEY environment variable or the model.key file, then
exposes the prediction functions. Everything is cached after first load.
"""

from __future__ import annotations

import base64
import os
import pickle
import types

from cryptography.fernet import Fernet

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, "model.key")
ENGINE_ENC = os.path.join(HERE, "engine.enc")
PARAMS_ENC = os.path.join(HERE, "params.enc")

_engine = None   # decrypted engine module
_params = None   # decrypted parameter dict


class ModelUnavailable(RuntimeError):
    """Raised when the encrypted model files / key are not present."""


def _read_artifact(env_b64: str, path: str) -> bytes | None:
    """Encrypted artifact bytes, from a base64 env var (for hosting) or a file."""
    blob = os.environ.get(env_b64)
    if blob:
        return base64.b64decode(blob)
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    return None


def available() -> bool:
    """True if key + both encrypted artifacts are reachable (file OR env)."""
    try:
        _load_key()
    except RuntimeError:
        return False
    return (_read_artifact("ENGINE_ENC_B64", ENGINE_ENC) is not None
            and _read_artifact("PARAMS_ENC_B64", PARAMS_ENC) is not None)


def _load_key() -> bytes:
    env = os.environ.get("WORLDCUP_KEY")
    if env:
        return env.encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    raise RuntimeError(
        "No model key found. Set WORLDCUP_KEY or provide model.key "
        "(run secure_build.py to create the encrypted model)."
    )


def _ensure_loaded():
    global _engine, _params
    if _engine is not None and _params is not None:
        return
    engine_bytes = _read_artifact("ENGINE_ENC_B64", ENGINE_ENC)
    params_bytes = _read_artifact("PARAMS_ENC_B64", PARAMS_ENC)
    if engine_bytes is None or params_bytes is None:
        raise ModelUnavailable(
            "Encrypted model not found. Provide engine.enc/params.enc (+ key), or set "
            "ENGINE_ENC_B64 / PARAMS_ENC_B64 / WORLDCUP_KEY env vars when hosting. This "
            "public repo ships without the proprietary model."
        )
    fernet = Fernet(_load_key())

    src = fernet.decrypt(engine_bytes).decode("utf-8")
    mod = types.ModuleType("worldcup_engine")
    exec(compile(src, "<engine>", "exec"), mod.__dict__)
    _engine = mod

    _params = pickle.loads(fernet.decrypt(params_bytes))


def expected_goals(home, away, delta_home=0.0, delta_away=0.0, neutral=True):
    _ensure_loaded()
    return _engine.expected_goals(_params, home, away, delta_home, delta_away, neutral)


def scoreline_grid(home, away, delta_home=0.0, delta_away=0.0, neutral=True):
    _ensure_loaded()
    return _engine.scoreline_grid(_params, home, away, delta_home, delta_away, neutral)


def trained_elo(team, default=1500.0):
    _ensure_loaded()
    return _params["elo"].get(team, default)


def model_info() -> dict:
    if not available():
        return {"available": False, "encrypted": True}
    _ensure_loaded()
    return {
        "available": True,
        "teams_rated": len(_params["dc"]["attack"]),
        "rho": round(_params.get("rho", 0.0), 4),
        "blend_dc": _params.get("blend_dc"),
        "has_gbm": _params.get("gbm") is not None,
        "encrypted": True,
    }
