"""Print the secret env vars needed to host the model (model stays out of git).

Run locally where your model files exist:

    python make_deploy_env.py

Copy the three values into your hosting platform's *secret/environment* settings
(Render, Railway, Fly.io, etc.) — NEVER commit them. With these set, the hosted
app loads the encrypted model from the environment, so it runs fully while the
model files never enter the GitHub repo.
"""

from __future__ import annotations

import base64
import os
import sys

KEY_FILE = "model.key"
ENGINE_ENC = "engine.enc"
PARAMS_ENC = "params.enc"


def _need(path: str) -> bytes:
    if not os.path.exists(path):
        sys.exit(f"Missing {path} — run train_model.py then secure_build.py first.")
    with open(path, "rb") as f:
        return f.read()


def main():
    key = _need(KEY_FILE).strip().decode()
    engine_b64 = base64.b64encode(_need(ENGINE_ENC)).decode()
    params_b64 = base64.b64encode(_need(PARAMS_ENC)).decode()

    print("# ── Set these as SECRET environment variables on your host ──")
    print("# (do not commit; the model never enters the repo)\n")
    print(f"WORLDCUP_KEY={key}\n")
    print(f"ENGINE_ENC_B64={engine_b64}\n")
    print(f"PARAMS_ENC_B64={params_b64}")


if __name__ == "__main__":
    main()
