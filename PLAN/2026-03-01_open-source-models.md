# Open-Source Models — Migration Plan

## Current Proprietary Stack

| Component | Current | Provider |
|---|---|---|
| STT | `deepgram/nova-3` | Deepgram (proprietary cloud API) |
| LLM | `openai/gpt-4.1-mini` | OpenAI (proprietary cloud API) |
| TTS | `inworld/inworld-tts-1` (voice: Olivia) | Inworld (proprietary cloud API) |
| VAD | `silero` | **Already open-source, runs locally ✅** |
| Embeddings | ChromaDB default (`all-MiniLM-L6-v2`) | **Already open-source, runs locally ✅** |

Only STT, LLM, and TTS need replacing.

---

## Open-Source Replacements Per Component

### STT

| Option | Model | Notes |
|---|---|---|
| **Groq API** | `whisper-large-v3-turbo` | Cloud API, open weights; `livekit-plugins-groq` (official). Very fast. |
| **Local faster-whisper** | `small.en` / `base.en` | Self-hosted via [faster-whisper-server](https://github.com/fedirz/faster-whisper-server); OpenAI-compatible API; use `livekit-plugins-openai` with custom `base_url` |

Whisper does not support audio streaming — requires VAD + `StreamAdapter` buffering. LiveKit's Groq plugin handles this transparently; local setup needs extra wiring.

### LLM

| Option | Model | Notes |
|---|---|---|
| **Groq API** | `llama-3.3-70b-versatile` | Cloud API, open weights (Meta Llama); `livekit-plugins-groq` (official). Fastest inference available. |
| **Ollama (local)** | `qwen2.5:7b`, `llama3.2:3b` | Fully local; `openai.LLM.with_ollama(model=..., base_url=...)`. No extra plugin needed. On M2+ MacBook, 7B models run at ~15 tok/s. |
| **Together.ai** | Llama 3.1 405B, Mistral, etc. | OpenAI-compatible API; use `livekit-plugins-openai` with custom `base_url`. Wider model selection than Groq. |

### TTS

| Option | Model | Notes |
|---|---|---|
| **Kokoro (local)** | `kokoro-v1` | Community LiveKit plugin: [`livekit-kokoro`](https://github.com/taresh18/livekit-kokoro). ~80ms TTFT, runs on CPU, high quality. Multiple voice styles. |
| **openedai-speech (local)** | Kokoro / Piper backend | Self-hosted OpenAI-compatible TTS server; use `livekit-plugins-openai` TTS with custom `base_url`. Easier if `livekit-kokoro` proves unstable. |
| **Piper (local)** | `en_US-lessac-medium` | Very lightweight, lower quality than Kokoro. Good fallback for low-resource environments. |

---

## Hosting Options

### Option A — Fully Local (Mac M-series)

All three services run on the same machine as the LiveKit agent.

```
Agent (Mac) → Ollama (LLM, localhost:11434)
           → faster-whisper-server (STT, localhost:8000)
           → Kokoro via livekit-kokoro (TTS, in-process)
```

**Pros:** Zero API cost, fully private, works offline.
**Cons:** Ties up Mac resources during sessions; 7B LLM inference is noticeably slower than cloud (~2-3× latency vs Groq); need to keep Ollama and whisper-server running.
**Cost:** $0 (electricity only)
**Best for:** Privacy-first, infrequent use.

---

### Option B — Groq Cloud + Local Kokoro TTS *(Recommended)*

LLM and STT run on Groq's LPU cloud (open weights, very fast). TTS runs locally via Kokoro.

```
Agent (Mac) → Groq API (LLM: llama-3.3-70b-versatile + STT: whisper-large-v3-turbo)
           → Kokoro via livekit-kokoro (TTS, in-process)
```

**Pros:** Simplest migration (official Groq plugin); inference speed on par with current stack; free tier available; only one new API key.
**Cons:** Still depends on one cloud API; TTS requires community plugin setup.
**Cost:** ~$0.01–0.05 per 30-min session (Groq free tier covers light usage).
**Best for:** Balance of quality, effort, and cost. Good starting point.

---

### Option C — Self-Hosted GPU (RunPod / vast.ai)

All three services deployed on a single on-demand GPU instance. Agent on Mac connects to the remote services.

```
Agent (Mac) → vLLM (LLM, GPU instance — Llama-3.1-8B or Qwen2.5-14B)
           → faster-whisper-server (STT, same instance)
           → Kokoro TTS server (TTS, same instance — openedai-speech)
```

**Providers:** RunPod, vast.ai (cheapest), Lambda Labs (most stable).
**Recommended GPU:** A10G (24 GB VRAM) — fits Llama-3.1-8B + whisper-large comfortably.

**Pros:** Full control; can run 14–70B models; not tied to Mac; separates compute from client.
**Cons:** Needs infrastructure management (Dockerfile, startup scripts); costs money when running; cold-start lag if using on-demand instances.
**Cost:** ~$0.20–0.50/hr (A10G on RunPod). For a 30-min daily session: ~$0.10–0.25/day.
**Best for:** Higher model quality (14B+), portable setup, or when Mac is unavailable.

---

### Option D — Fully Managed Open-Model APIs (Together.ai / Fireworks)

LLM via Together.ai or Fireworks (OpenAI-compatible, open weights). STT via local whisper. TTS via Kokoro.

```
Agent (Mac) → Together.ai / Fireworks (LLM — Llama 3.1 405B, Mixtral)
           → faster-whisper-server (STT, localhost)
           → Kokoro (TTS, in-process)
```

**Pros:** Access to the largest open models (405B) cheaply; pay-per-token.
**Cons:** Local STT setup needed; slightly more complex than Groq.
**Cost:** Together.ai: ~$0.18/1M tokens (Llama 3.1 8B), ~$3.50/1M (Llama 3.1 405B).
**Best for:** When largest model quality matters more than simplicity.

---

## Implementation Steps

### Phase 1 — LLM + STT via Groq (low effort, ~1 hour)

1. Add `livekit-agents[groq]` to `pyproject.toml`
2. Add `groq_api_key: str = ""` to `src/core/config.py`
3. Add `GROQ_API_KEY=...` to `.env` and `.env.example`
4. Update `src/agent/agent.py` `AgentSession`:
   ```python
   stt="groq/whisper-large-v3-turbo",
   llm="groq/llama-3.3-70b-versatile",
   ```
5. Remove (or make optional) `openai_api_key` and `deepgram_api_key` from config

### Phase 2 — TTS via Kokoro (medium effort, ~2-3 hours)

Two sub-options:

**2a. livekit-kokoro community plugin**
1. Pin `livekit-kokoro` from GitHub in `pyproject.toml`
2. Download Kokoro model weights (`kokoro-v1_0.pth`)
3. Update `agent.py` to use Kokoro TTS plugin
4. Choose a voice from available presets (closest to "Olivia": `af_sarah`, `bf_emma`)

**2b. openedai-speech server (more stable)**
1. Run `openedai-speech` Docker container (Kokoro backend)
2. Use `livekit-plugins-openai` TTS with `base_url="http://localhost:8000/v1"`
3. Eliminates dependency on community plugin; easier to upgrade

Remove `elevenlabs_api_key` from config once TTS is confirmed working.

### Phase 3 — Optional: Fully Local (if Groq dependency is unwanted)

1. Install Ollama: `brew install ollama && ollama pull qwen2.5:7b`
2. Install faster-whisper-server
3. Update `agent.py` to use local endpoints:
   ```python
   stt=openai.STT(base_url="http://localhost:8000/v1", model="whisper-1"),
   llm=openai.LLM.with_ollama(model="qwen2.5:7b"),
   ```
4. Add a `poe local` task that starts both servers before launching the agent

---

## Priority / Recommendation

| Priority | Task | Effort | Value |
|---|---|---|---|
| 1 | LLM + STT → Groq | 1 hr | Open weights, no quality loss, minimal code change |
| 2 | TTS → Kokoro (openedai-speech) | 2–3 hr | Eliminates last paid API, fully local TTS |
| 3 | LLM → Ollama local | 1 hr | Removes last cloud dependency (if privacy matters) |
| 4 | STT → faster-whisper local | 2–3 hr | Fully offline setup |
| 5 | GPU hosting (RunPod) | 1 day | Better model quality (14B+), portable |

**Recommended starting point:** Option B (Groq + local Kokoro). Implement Phase 1 first to validate, then add Phase 2 for TTS. Total migration to fully open: 3–4 hours across two sessions.
