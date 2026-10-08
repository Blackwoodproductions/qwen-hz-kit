#!/usr/bin/env bash
# Boot the kit: start ollama, pull + warm BOTH models, then launch the kit API on :8000.
set -euo pipefail

HZ_MODEL="${HZ_MODEL:?set HZ_MODEL (e.g. hf.co/SEOlocal/qwen-hz-node or a custom ollama tag)}"
JUDGE_MODEL="${JUDGE_MODEL:-}"

# 1) ollama in the background (GPU auto-detected in the ollama/ollama image)
ollama serve &

# 2) wait for the ollama API
echo "[boot] waiting for ollama..."
for i in $(seq 1 90); do
  curl -sf http://127.0.0.1:11434/api/tags >/dev/null 2>&1 && break
  sleep 1
done

# 3) pull the models.
#    - HuggingFace GGUF repo  -> HZ_MODEL=hf.co/SEOlocal/qwen-hz-node
#    - a custom ollama tag    -> HZ_MODEL=qwen-hz-r11
#    If your HF repo ships safetensors/fp16 (not GGUF), convert + `ollama create` from a Modelfile
#    at build time instead; ollama pull only takes GGUF repos / registry tags.
echo "[boot] pulling $HZ_MODEL ..."
ollama pull "$HZ_MODEL"
if [ -n "$JUDGE_MODEL" ]; then
  echo "[boot] pulling $JUDGE_MODEL ..."
  ollama pull "$JUDGE_MODEL"
fi

# 4) warm both so they're resident before traffic (KEEP_ALIVE=-1 keeps them pinned)
echo "[boot] warming models..."
ollama run "$HZ_MODEL" "ok" >/dev/null 2>&1 || true
[ -n "$JUDGE_MODEL" ] && ollama run "$JUDGE_MODEL" "ok" >/dev/null 2>&1 || true

# 5) kit API in the foreground — the container lives as long as this runs
echo "[boot] starting kit API on :8000"
exec uvicorn server:app --host 0.0.0.0 --port 8000 --workers 1
