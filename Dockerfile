# qwen-hz-kit — r11 humanizer (Qwen2.5-7B) + judge, 6-draft + fact-check + judge pipeline.
# Base = official Ollama image (Ubuntu + CUDA + ollama). PIN the tag — never :latest.
FROM ollama/ollama:0.12.3            # <-- verify/raise to a current release at hub.docker.com/r/ollama/ollama/tags

# Python for the kit API server (the ollama image is Ubuntu-based)
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# The kit API. Replace server.py with Fernando's actual kit server if he has one — the entrypoint
# just needs a uvicorn app named `server:app` listening on :8000.
COPY server.py entrypoint.sh ./
RUN chmod +x entrypoint.sh

EXPOSE 8000

# Override the base image's `ollama serve` entrypoint: our script starts ollama, pulls + warms
# both models, then launches the kit API in the foreground.
ENTRYPOINT ["/app/entrypoint.sh"]
