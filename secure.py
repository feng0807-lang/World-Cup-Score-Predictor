"""Runtime loader for the encrypted prediction model.

Decrypts engine.enc (algorithm) and params.enc (trained parameters) using the
key from the WORLDCUP_KEY environment variable or the model.key file, then
exposes the prediction functions. Everything is cached after first load.
"""

from __future__ import annotations

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


def available() -> bool:
    """True if the encrypted model + key are all present (without decrypting)."""
    try:
        _load_key()
    except RuntimeError:
        return False
    return os.path.exists(ENGINE_ENC) and os.path.exists(PARAMS_ENC)


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
    if not (os.path.exists(ENGINE_ENC) and os.path.exists(PARAMS_ENC)):
        raise ModelUnavailable(
            "Encrypted model not found (engine.enc / params.enc). This repo ships "
            "without the proprietary model — add your own model files + key to enable "
            "predictions."
        )
    fernet = Fernet(_load_key())

    with open(ENGINE_ENC, "rb") as f:
        src = fernet.decrypt(f.read()).decode("utf-8")
    mod = types.ModuleType("worldcup_engine")
    exec(compile(src, "<engine>", "exec"), mod.__dict__)
    _engine = mod

    with open(PARAMS_ENC, "rb") as f:
        _params = pickle.loads(fernet.decrypt(f.read()))


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
