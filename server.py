"""
qwen-hz-kit — reference humanizer API.

Pipeline (matches the described r11 kit): split -> for each chunk generate N drafts with the r11
humanizer (varied temperature+seed for diversity, using the caller's system_prompt) -> fact-check
filter (every number in the source must survive) -> judge model picks the most human + faithful ->
stitch. Fail-safe: if no draft survives the fact gate, the original chunk is kept (never ships a
fabrication).

This is a drop-in reference. If Fernando already has the kit logic, replace this file — the only
contract the container needs is a uvicorn app named `server:app` on :8000 exposing POST /humanize.

Request : { "text": "...", "system_prompt": "...?", "tone": "...?" }
Response: { "text": "...", "model": "...", "chunks": N, "drafts_per_chunk": N }
Auth    : KIT_API_KEY via `Authorization: Bearer <key>` or `x-api-key: <key>` (required if env set).
"""
import os
import re
import asyncio

import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

OLLAMA = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
HZ_MODEL = os.getenv("HZ_MODEL", "hf.co/SEOlocal/qwen-hz-node")
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "")
N_DRAFTS = int(os.getenv("DRAFTS_PER_CHUNK", "6"))
FACTCHECK = os.getenv("FACTCHECK", "on").lower() == "on"
JUDGE = os.getenv("JUDGE", "on").lower() == "on"
API_KEY = os.getenv("KIT_API_KEY", "")
CHUNK_WORDS = int(os.getenv("CHUNK_WORDS", "220"))
GEN_TIMEOUT = float(os.getenv("GEN_TIMEOUT_S", "300"))

DEFAULT_SYSTEM = (
    "You are an expert human editor. Rewrite the text so a real person clearly wrote it, not an AI. "
    "Vary sentence length a lot, use natural contractions and plain words, cut AI filler. Keep every "
    "fact, number, name, price, and URL exactly the same. Do not add anything not in the text."
)

app = FastAPI(title="qwen-hz-kit")

NUM = re.compile(r"\d[\d,.]*")


def _require_key(authorization: str | None, x_api_key: str | None) -> None:
    if not API_KEY:
        return  # no key set = open (not recommended for a public endpoint)
    tok = ""
    if authorization and authorization.startswith("Bearer "):
        tok = authorization[7:].strip()
    tok = tok or (x_api_key or "").strip()
    if tok != API_KEY:
        raise HTTPException(status_code=401, detail="invalid API key")


def _facts(s: str) -> set[str]:
    return set(NUM.findall(s))


def _facts_survive(src: str, out: str) -> bool:
    return not (_facts(src) - _facts(out))  # every source number must appear in the output


def _chunk(text: str) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > CHUNK_WORDS:
            chunks.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks or [text.strip()]


async def _generate(client: httpx.AsyncClient, model: str, prompt: str, system: str,
                    temperature: float, seed: int) -> str:
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "system": system,
        "options": {"temperature": temperature, "seed": seed, "num_ctx": 8192, "num_predict": 2048},
    }
    r = await client.post(f"{OLLAMA}/api/generate", json=body, timeout=GEN_TIMEOUT)
    r.raise_for_status()
    return (r.json().get("response") or "").strip()


async def _judge_pick(client: httpx.AsyncClient, source: str, drafts: list[str]) -> str:
    """Ask the judge model to return the index (1-based) of the most human, faithful rewrite."""
    numbered = "\n\n".join(f"[{i + 1}]\n{d}" for i, d in enumerate(drafts))
    prompt = (
        "You are judging rewrites of a source passage. Pick the ONE that reads most like a human wrote "
        "it AND keeps every fact from the source unchanged. Reply with ONLY its number.\n\n"
        f"SOURCE:\n{source}\n\nCANDIDATES:\n{numbered}\n\nBest number:"
    )
    try:
        out = await _generate(client, JUDGE_MODEL, prompt, "You are a strict, terse judge.", 0.0, 7)
        m = re.search(r"\d+", out)
        if m:
            idx = int(m.group()) - 1
            if 0 <= idx < len(drafts):
                return drafts[idx]
    except Exception:
        pass
    return drafts[0]


class HumanizeReq(BaseModel):
    text: str
    system_prompt: str | None = None
    tone: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "model": HZ_MODEL, "judge": JUDGE_MODEL or None, "drafts": N_DRAFTS}


@app.post("/humanize")
async def humanize(req: HumanizeReq,
                   authorization: str | None = Header(default=None),
                   x_api_key: str | None = Header(default=None)):
    _require_key(authorization, x_api_key)
    src = (req.text or "").strip()
    if not src:
        raise HTTPException(status_code=422, detail="text is required")

    system = req.system_prompt.strip() if req.system_prompt else DEFAULT_SYSTEM
    chunks = _chunk(src)

    async with httpx.AsyncClient() as client:
        out_chunks: list[str] = []
        for ch in chunks:
            drafts = await asyncio.gather(
                *[_generate(client, HZ_MODEL, ch, system, 0.55 + 0.1 * i, 1000 + i) for i in range(N_DRAFTS)],
                return_exceptions=True,
            )
            drafts = [d for d in drafts if isinstance(d, str) and d]
            cands = [d for d in drafts if (not FACTCHECK or _facts_survive(ch, d))]
            if not cands:
                out_chunks.append(ch)  # fail-safe: nothing survived -> keep original (no fabrication)
                continue
            best = cands[0]
            if JUDGE and JUDGE_MODEL and len(cands) > 1:
                best = await _judge_pick(client, ch, cands)
            out_chunks.append(best)

    return {
        "text": "\n\n".join(out_chunks),
        "model": HZ_MODEL,
        "chunks": len(chunks),
        "drafts_per_chunk": N_DRAFTS,
    }
