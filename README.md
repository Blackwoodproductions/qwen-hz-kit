# qwen-hz-kit

The **r11 humanizer kit** — Qwen2.5-7B (round 11) + a judge model, run as a **6-draft → fact-check →
judge** pipeline — packaged as a containerized HTTP service for the **Akash** GPU network.

This is the kit that produced Rob's **~89% human** result (run directly on the 4090). Hosting it on a
public GPU fixes the 4090's CGNAT wall. Once it's live, hashtag.org routes Fernando's
`POST /api/humanize/v1` straight to it — the geo-portal bridge is already shipped and gated (it stays
off until `HUMANIZER_KIT_URL` is set, so production is unchanged until the kit is up).

## What's here
| file | what it is |
|---|---|
| **`BUILD.md`** | **full build + deploy guide (start here)** — provision the model, build, push, fill the SDL, deploy on Akash, smoke-test, hand off |
| `Dockerfile` | the image: Ollama + Python + the kit API |
| `entrypoint.sh` | boot: start ollama → pull + warm both models → launch the API on `:8000` |
| `server.py` | reference kit API — **drop-in replaceable with Fernando's real kit** (only contract: a uvicorn app `server:app` on `:8000`) |
| `Modelfile` | fallback for building r11 from raw HF weights (bakes the Qwen2.5 rope fix) |
| `requirements.txt` | Python deps |
| `qwen-hz-kit-akash.sdl.yaml` | the Akash deployment manifest (A100 40GB primary, RTX 4090 fallback) |

## API contract
```
POST /humanize
  headers: authorization: Bearer <KIT_API_KEY>   (or  x-api-key: <KIT_API_KEY>)
  body   : { "text": "...", "system_prompt": "...?", "tone": "...?" }
  reply  : { "text": "...", "model": "...", "chunks": N, "drafts_per_chunk": N }

GET /health -> { "ok": true }
```
The pipeline splits the text, generates N drafts per chunk (varied temp + seed, using the caller's
`system_prompt`), drops any draft that changes a number/name/URL (fact-check), has the judge pick the
most human + faithful, and stitches. If no draft survives the fact gate, the original chunk is kept —
it never ships a fabrication.

## Quick start
See **[BUILD.md](BUILD.md)** for the full walkthrough. In short:
1. Make the r11 model + judge pullable (reuse the working 4090 model, or pull from HuggingFace).
2. `docker build -t <registry>/qwen-hz-kit:r11 .` → push.
3. Fill the 4 `<PLACEHOLDER>`s in `qwen-hz-kit-akash.sdl.yaml` (`image`, `HF_TOKEN`, `JUDGE_MODEL`,
   `KIT_API_KEY`).
4. Deploy on **console.akash.network** → create a lease → copy the public URL.
5. Send Rob/GIGI the **public URL + KIT_API_KEY**; GIGI sets `HUMANIZER_KIT_URL`/`KEY` and redeploys.

## Security / ops
- **Never commit** `KIT_API_KEY` or `HF_TOKEN` — they live only in the SDL env (`.gitignore` excludes `.env`).
- The endpoint is **public** → `KIT_API_KEY` is the only thing stopping strangers from burning the GPU. Use a long random value.
- Weights sit on a 100Gi persistent volume (survive restarts, no re-download).
- Never use `:latest`. **Close the lease** when idle (A100 ≈ $1.5–2.5/hr).
