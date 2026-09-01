# TapTalent — Real-Time AI Voice Interview Platform

TapTalent is a real-time voice interview platform powered by **LiveKit Agents**. It conducts structured, automated candidate technical interviews using real-time Speech-to-Text (STT), Large Language Models (LLM), and Text-to-Speech (TTS), providing live visual status, real-time transcription, and post-interview recording playback.

---

## 1. System Architecture

TapTalent uses a decoupled, three-tier architecture coordinated over WebRTC:

```
┌─────────────────┐       WebRTC Audio & Data Channels       ┌────────────────────────┐
│                 │ ◄──────────────────────────────────────► │                        │
│ React / Vite UI │                                          │  Python Agent Worker   │
│ (Candidate Web) │ ──┐                                  ┌── │  (LiveKit Agents)      │
│                 │   │                                  │   │                        │
└─────────────────┘   │                                  │   └────────────────────────┘
                      │ HTTP (Token, State, Transcripts) │               │
                      ▼                                  ▼               ▼
        ┌───────────────────────────┐                 ┌─────────────────────────────┐
        │   Node.js / Express API   │                 │   LiveKit Cloud Inference   │
        │  (Token Minting & Store)  │                 │  (STT, LLM, TTS Gateway)    │
        └───────────────────────────┘                 └─────────────────────────────┘
```

### Component Roles

| Layer | Technology | Responsibilities |
|---|---|---|
| **Frontend** | React 18, Vite, `livekit-client` | Clean candidate interface, microphone permission handling, audio streaming, live progress tracking, and post-interview transcript/audio review. |
| **Backend API** | Node.js, Express, `livekit-server-sdk` v2 | JWT access token minting, room creation with metadata injection via `RoomServiceClient`, in-memory & file-based state persistence (`transcripts/`), and audio serving (`recordings/`). |
| **Agent Worker** | Python 3.11, `livekit-agents` 1.7.1 | Joins the room via `AgentServer`, listens for candidate speech via Silero VAD, streams speech to STT, generates concise acknowledgements with LLM, speaks questions via TTS, and maintains state. |
| **AI Inference** | LiveKit Cloud Inference Gateway | Cloud-hosted STT, LLM, and TTS models accessed using a single LiveKit API key with zero data retention. |

---

## 2. AI Provider Choices & Reasoning

Rather than managing separate accounts, rate limits, and billing contracts for multiple AI vendors, this project uses **LiveKit Inference** to route all voice and model workloads through LiveKit Cloud:

| Pipeline Step | Selected Model | Technical Justification |
|---|---|---|
| **STT (Speech-to-Text)** | `deepgram/nova-3` | Sub-300ms streaming transcription latency, high accuracy for technical terms, and native WebSocket stream integration. |
| **LLM (Reasoning)** | `openai/gpt-4.1-mini` | Low Time-to-First-Token (~200ms TTFT), strong instruction adherence for concise 1-sentence acknowledgements without hallucinating extra questions. |
| **TTS (Text-to-Speech)** | `cartesia/sonic-3` (`voice: 9626c31c-...`) | Ultra-low latency voice synthesis designed specifically for conversational voice agents. |
| **VAD (Voice Activity Detection)** | `Silero VAD` (`livekit.plugins.silero`) | Local ONNX-based acoustic voice detection to reliably detect start and end of candidate speech boundaries. |
| **Turn Detection** | `inference.TurnDetector` | Semantic End-of-Turn (EOT) classification to distinguish between natural speaking pauses and completed answers. |

---

## 3. Real-Time Voice Turn-Taking Flow

```
[Candidate Joins Room]
         │
         ▼
[Agent Welcomes Candidate & Plays Intro]
         │
         ▼
   ┌────► [Agent Asks Question N via TTS]
   │     │
   │     ▼
   │  [Candidate Speaks Answer]
   │     │  ├── Silero VAD detects acoustic activity
   │     │  ├── Deepgram Nova-3 streams interim & final STT
   │     │  └── Speech debounce timer (1.8s) waits for true silence
   │     ▼
   │  [Candidate Finishes Answer]
   │     │  ├── Append Candidate Turn to State
   │     │  ├── Persist state incrementally to disk & backend (F-02)
   │     │  └── LLM generates 1-sentence acknowledgement
   │     ▼
   │  [Agent Plays LLM Acknowledgement via TTS]
   │     │
   └─────┴──── (Next Question / If last question, proceed)
         │
         ▼
[Agent Plays Closing Message & Concludes]
         │
         ▼
[Room Disconnected & Audio Saved for Playback]
```

### Key Turn-Taking Optimizations

1. **Suppression of Loop Contention:** `InterviewerAgent.on_user_turn_completed` raises `StopResponse()` so that the session's background conversational pipeline does not collide with the structured interview question loop.
2. **Speech Activity Debounce:** An active silence debounce mechanism (`SILENCE_GAP = 1.8s`) continuously tracks all streaming transcript events (both interim and final). This prevents the agent from cutting off candidates during brief mid-sentence pauses.
3. **Queue Draining & Echo Suppression:** Before and after question playback, audio queues are purged and an echo grace window (`0.3s`) is applied so the agent never transcribes its own synthesized voice.
4. **Strict Acknowledgement Scoping:** The LLM prompt is strictly constrained to **1-sentence acknowledgement only** without asking subsequent questions. The sequential python loop remains the single source of truth for question delivery.

---

## 4. Failure Mode Handling

Robust handling for distributed and external service failure modes is built in:

| Failure Scenario | Mitigation Strategy | PRD Ref |
|---|---|---|
| **STT Silence / Timeout** | If no transcript is received after 60s, the agent prompts: *"Sorry, I didn't catch that — could you repeat your answer?"*. If still silent after 45s, records `[inaudible]` and advances. | `F-01` |
| **LLM Failure** | Candidate turn is committed to `InterviewState` and persisted **before** calling the LLM. If the LLM call fails, the agent retries once, then falls back to a deterministic acknowledgement (*"Thanks for that, {name} — let's continue."*). | `F-02` |
| **TTS Synthesis Failure** | If TTS audio generation fails, the agent publishes the text payload over the LiveKit WebRTC reliable data channel (`reliable=True`) so the candidate UI displays the message and transitions cleanly. | `F-03` |
| **Candidate Disconnect** | An `on("participant_disconnected")` listener detects unexpected candidate departures, immediately calculates final duration, marks status as `abandoned`, and shuts down gracefully. | `A-05` |
| **Invalid Configuration** | If required fields (`candidateName`, `jobTitle`, `questions`) are missing or empty, config validation flags the error, sets status to `failed`, and exits cleanly. | `C-01` |

---

## 5. Repository Structure

```
taptalent/
├── agent/                  # LiveKit Agent Worker (Python)
│   ├── agent.py            # AgentServer entrypoint & interview turn loop
│   ├── config.py           # Structured InterviewConfig loader & validator
│   ├── prompts.py          # System prompts & message templates
│   ├── state.py            # InterviewState dataclass & local/remote persistence
│   ├── requirements.txt    # Python dependencies (livekit-agents 1.7.1)
│   ├── Dockerfile          # Agent container specification
│   └── .env.example        # Agent environment template
├── backend/                # API & Token Server (Node.js/TypeScript)
│   ├── src/
│   │   ├── server.ts       # Express server & REST endpoints
│   │   ├── livekit.ts      # AccessToken minting & RoomServiceClient
│   │   ├── interviews.ts   # Interview record storage & file operations
│   │   └── types.ts        # TypeScript data models
│   ├── package.json        # Backend dependencies
│   ├── tsconfig.json       # TypeScript configuration
│   └── .env.example        # Backend environment template
├── frontend/               # Web Application UI (React / Vite)
│   ├── src/
│   │   ├── App.tsx         # Main application flow (Setup, Live, Result)
│   │   ├── components/
│   │   │   ├── InterviewRoom.tsx    # LiveKit room audio connector & visualizer
│   │   │   ├── TranscriptView.tsx   # Live & post-interview conversation view
│   │   │   └── AudioPlayer.tsx      # Web audio recording playback
│   │   ├── styles.css      # Custom UI design system
│   │   └── types.ts        # Frontend type definitions
│   ├── index.html          # HTML entrypoint
│   ├── package.json        # Frontend dependencies
│   └── .env.example        # Frontend environment template
├── recordings/             # Runtime interview audio files (*.webm)
├── transcripts/            # Runtime interview JSON transcript records
├── dev.py                  # Unified multi-process launcher (Python)
├── package.json            # Root package scripts (npm run dev)
├── .gitignore              # Strict secret & runtime artifact filter
└── README.md               # Technical documentation
```

---

## 6. Getting Started

### Prerequisites

- **Node.js** 18.0+ and `npm`
- **Python** 3.10+ and `pip`
- **LiveKit Cloud Account:** URL, API Key, and API Secret from [cloud.livekit.io](https://cloud.livekit.io/)

### 1. Environment Configuration

Copy the example environment files for each service:

```bash
# Root & Backend
cp backend/.env.example backend/.env

# Agent
cp agent/.env.example agent/.env

# Frontend
cp frontend/.env.example frontend/.env
```

Configure your LiveKit credentials in `backend/.env` and `agent/.env`:

```ini
LIVEKIT_URL=wss://<your-subdomain>.livekit.cloud
LIVEKIT_API_KEY=<your-api-key>
LIVEKIT_API_SECRET=<your-api-secret>
```

And in `frontend/.env`:

```ini
VITE_LIVEKIT_URL=wss://<your-subdomain>.livekit.cloud
VITE_BACKEND_URL=http://localhost:3000
```

---

### 2. Installation

Install dependencies for all components:

```bash
# Root & subpackages
npm run install:all

# Python agent dependencies
cd agent && pip install -r requirements.txt && cd ..
```

---

### 3. Running the Application

You can launch all 3 services (Backend, Frontend, Agent) simultaneously using either the Python runner or npm:

```bash
# Option A: Unified Python runner
python dev.py

# Option B: Root npm runner
npm run dev
```

Alternatively, you can run each service in separate terminals:

```bash
# Terminal 1: Backend (Port 3000)
cd backend && npm run dev

# Terminal 2: Frontend (Port 5173)
cd frontend && npm run dev

# Terminal 3: Agent Worker
cd agent && python agent.py dev
```

---

## 7. Testing & Verification

### Smoke Test Suite

Verify end-to-end token minting, room creation, transcript persistence, and audio endpoints:

```bash
node scratch/smoke_test.js
```

### Manual Interview Verification

1. Open **[http://localhost:5173/](http://localhost:5173/)** in your browser.
2. Fill in the candidate name, target job role, and customize or keep the 3 default interview questions.
3. Click **Start Interview** and grant microphone permissions when prompted.
4. Listen to the AI interviewer welcome you and ask the first question.
5. Answer naturally through your microphone — the agent will wait for your complete answer, acknowledge it, and proceed through the question list.
6. Upon completion, review the formatted transcript and listen to the audio recording.

---

## 8. Technical Decisions & Assumptions

- **Single Provider Footprint via LiveKit Inference:** Model inference for STT, LLM, and TTS is consolidated under LiveKit Cloud, removing the overhead of managing separate provider SDKs and credential vaults.
- **Local Storage:** Per assignment specification (PRD §4, §9), recordings and transcripts are persisted to the local file system (`recordings/` and `transcripts/`), eliminating cloud bucket dependencies for local development.
- **Ephemeral Worker Dispatch:** Each interview room triggers an ephemeral `rtc_session` worker instance that automatically exits upon room termination or participant disconnection.
- **Explicit Scope Boundaries:** Candidate scoring, automated cheating detection, authentication, billing, and distributed container orchestrators were omitted in accordance with the assignment guidelines (PRD §14–15).
