# Portable container — works on Fly.io, Railway, Render (Docker), or any host.
# The model is NOT baked in; supply it at runtime via env vars
# (WORLDCUP_KEY / ENGINE_ENC_B64 / PARAMS_ENC_B64).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# server.py auto-binds 0.0.0.0:$PORT when PORT is set by the platform.
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000

CMD ["python", "server.py"]
