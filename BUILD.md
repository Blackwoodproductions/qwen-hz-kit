# qwen-hz-kit — build & deploy on Akash

The **r11 humanizer kit** (Qwen2.5-7B r11 + judge; 6-draft → fact-check → judge) packaged as a
containerized HTTP service for the Akash GPU network. Once it's live, hashtag.org routes Fernando's
`POST /api/humanize/v1` straight to it (the geo-portal bridge is already staged).

## Files in this folder
| file | what it is |
|---|---|
| `Dockerfile` | the image — Ollama + Python + the kit API |
| `entrypoint.sh` | boot: start ollama → pull + warm both models → launch the API on :8000 |
| `server.py` | reference kit API (`POST /humanize`, 6-draft/fact-check/judge). **Replace with your real kit if you have it** — the only contract is a uvicorn app `server:app` on :8000 |
| `requirements.txt` | Python deps |
| `Modelfile` | fallback for building r11 from raw HF weights (bakes the Qwen2.5 rope fix) |
| `qwen-hz-kit-akash.sdl.yaml` | the Akash deployment manifest |

## Prerequisites
- Docker (to build/push — **no GPU needed to build**)
- A container registry you can push to (GHCR or Docker Hub)
- A HuggingFace token (to pull `SEOlocal/qwen-hz-node` + the judge)
- An Akash wallet with a little **AKT + USDC**, and **console.akash.network** (or the Akash CLI)

---

## Step 1 — provision the model (pick ONE)
**A) BEST — reuse the model that already produced 89%.** You already have r11 working in Ollama on the
4090. Make it pullable so the container just grabs it as-is (no rebuild, no risk):
```
ollama cp <local-r11-tag> <registry>/qwen-hz-node   # or `ollama push` to the Ollama library
```
→ set `HZ_MODEL` to that ref in the SDL. Do the same for the judge model.

**B) GGUF on HuggingFace** → set `HZ_MODEL=hf.co/SEOlocal/qwen-hz-node`; the entrypoint pulls it. No Modelfile.

**C) Only raw fp16/safetensors on HF** → build it once with the Modelfile (this fixes the rope word-salad):
```
huggingface-cli download SEOlocal/qwen-hz-node --local-dir ./qwen-hz-node   # (uncomment the dir FROM in Modelfile)
ollama create qwen-hz-node -f Modelfile
```
then push it (option A).

## Step 2 — (optional) drop in your real kit
If you already have the exact 6-draft/fact-check/judge code, **replace `server.py`** with it. Keep the
contract: `server:app` on :8000, `POST /humanize {text, system_prompt?, tone?} -> {text}`, and
`KIT_API_KEY` auth. Everything else in the image is model-agnostic.

## Step 3 — build
```
docker build -t <registry>/qwen-hz-kit:r11 .
```

## Step 4 — push
```
echo "$REG_TOKEN" | docker login <registry> -u <user> --password-stdin
docker push <registry>/qwen-hz-kit:r11
```

## Step 5 — fill the SDL (`qwen-hz-kit-akash.sdl.yaml`)
- `image:` → `<registry>/qwen-hz-kit:r11`
- `HF_TOKEN=` → your HuggingFace token
- `HZ_MODEL` / `JUDGE_MODEL` → the refs from Step 1
- `KIT_API_KEY=` → a long random secret  **(REQUIRED — the endpoint is public)**
- GPU is already set: A100 40GB primary, RTX 4090 fallback.

## Step 6 — deploy on Akash
Console → **Deploy** → paste the SDL → review bids → pick a provider → **create lease**.
When it's up, the **Leases / URIs** panel shows your public endpoint, e.g.
`https://<provider>.akash.pub:<port>`.
(CLI alternative: `akash tx deployment create <sdl>` → `akash tx market lease create …`.)

## Step 7 — smoke test
```
curl https://<provider>.akash.pub:<port>/health
curl -s https://<provider>.akash.pub:<port>/humanize \
  -H "authorization: Bearer <KIT_API_KEY>" -H "content-type: application/json" \
  -d '{"text":"<an AI-sounding paragraph>","system_prompt":"Rewrite so it reads human."}'
```
The first call warms both models (slow); subsequent calls are fast.

## Step 8 — hand off to wire hashtag.org
Send Rob/GIGI **the public URL + the KIT_API_KEY**. The bridge is already staged
(`lib/humanizer/kit.ts` + `/root/staged-kit-bridge/` on the prod box). GIGI sets
`HUMANIZER_KIT_URL` + `HUMANIZER_KIT_KEY` in geo-portal `.env` + deploy-atomic → Fernando's
`/api/humanize/v1` runs the kit. Ember re-runs GPTZero to confirm ~89%.

---

## Security / ops
- **Never commit** `KIT_API_KEY` / `HF_TOKEN` — they live only in the SDL env.
- The endpoint is global/public → the `KIT_API_KEY` gate is the only thing stopping strangers from
  burning the GPU. Use a long random value.
- Weights sit on the **100Gi persistent volume** → survive restarts, no re-download.
- Never use `:latest` (image or base tag) — Akash best practice + reproducibility.
- **Close the lease** when not in use to stop paying (A100 ~$1.5–2.5/hr, 4090 ~$0.5–1.5/hr).
