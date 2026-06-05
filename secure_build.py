"""Encrypt the prediction model (code + parameters).

Creates:
  model.key    - the symmetric AES key (Fernet). Keep this secret!
  engine.enc   - AES-encrypted engine source code (the algorithm)
  params.enc   - AES-encrypted trained parameters (attack/defense, GBM, rho...)

Usage:
  python secure_build.py            # build encrypted artifacts
  python secure_build.py --purge    # also delete the plaintext source/params

The app loads engine.enc + params.enc at runtime via secure.py, decrypting with
the key from the WORLDCUP_KEY env var or the model.key file.

NOTE: runtime decryption is obfuscation, not unbreakable DRM — whoever can run
the app can in principle recover the key. It deters casual copying of your model
and keeps the algorithm/tuning out of plain sight in the shipped files.
"""

from __future__ import annotations

import os
import sys

from cryptography.fernet import Fernet

KEY_FILE = "model.key"
ENGINE_SRC = "engine_source.py"
PARAMS_SRC = "model_params.pkl"
ENGINE_ENC = "engine.enc"
PARAMS_ENC = "params.enc"


def get_or_create_key() -> bytes:
    env = os.environ.get("WORLDCUP_KEY")
    if env:
        return env.encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    print(f"Generated new key -> {KEY_FILE}")
    return key


def main():
    key = get_or_create_key()
    f = Fernet(key)

    with open(ENGINE_SRC, "rb") as fh:
        f_engine = f.encrypt(fh.read())
    with open(ENGINE_ENC, "wb") as fh:
        fh.write(f_engine)
    print(f"Encrypted {ENGINE_SRC} -> {ENGINE_ENC} ({len(f_engine)} bytes)")

    with open(PARAMS_SRC, "rb") as fh:
        f_params = f.encrypt(fh.read())
    with open(PARAMS_ENC, "wb") as fh:
        fh.write(f_params)
    print(f"Encrypted {PARAMS_SRC} -> {PARAMS_ENC} ({len(f_params)} bytes)")

    if "--purge" in sys.argv:
        for p in (ENGINE_SRC, PARAMS_SRC):
            if os.path.exists(p):
                os.remove(p)
                print(f"Purged plaintext {p}")
        print("Plaintext removed. Keep model.key safe and back up the sources elsewhere.")
    else:
        print("\nKept plaintext sources. Run with --purge to remove them for distribution.")


if __name__ == "__main__":
    main()
