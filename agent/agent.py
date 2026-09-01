"""
TapTalent Interviewer Agent — LiveKit Agents worker (agents.md §2, PRD §3).

Implements LiveKit Inference only (no separate STT/LLM/TTS providers):
  - AgentServer + @server.rtc_session() (livekit-agents)
  - AgentSession(stt=inference.STT(...), llm=inference.LLM(...), tts=inference.TTS(...), vad=inference.VAD(), turn_handling={...})
    All billed via LiveKit Cloud — no Deepgram/Groq/ElevenLabs keys needed.
  - turn handling via inference.TurnDetector() + inference.VAD() (built-in 1.6.1+/1.7.x)
  - session.generate_reply(instructions=...) + session.shutdown() + user_input_transcribed

Lifecycle: A-01 join → A-02/A-03 intro → T-01..T-05 turn loop (C-03 ordered, C-02 config-driven)
           → E-01 closing → E-02 completed → A-04 shutdown
           → A-05 abandoned on participant_disconnected

Failure handling (F-01..F-04): simple, explicit, 1 LLM retry max, no backoff.
State ordering for F-02: Candidate turn appended BEFORE LLM call via user_input_transcribed handler.

Run:
  python agent.py dev                    # AgentServer dev mode — auto-joins on room creation
  python agent.py start                  # production (same entrypoint)
  lk agent dev / lk agent start          # via LiveKit CLI

Env: only LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET required.
Optional overrides: INFERENCE_STT_MODEL, INFERENCE_LLM_MODEL, INFERENCE_TTS_MODEL, INFERENCE_TTS_VOICE
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------- logging
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("taptalent-agent")

# ---------------------------------------------------------------- local imports
from config import InterviewConfig  # noqa: E402
from prompts import (  # noqa: E402
    build_system_prompt,
    build_user_message,
    closing_message,
    fallback_ack,
    intro_message,
    stt_reprompt,
)
from state import InterviewState, Turn, persist  # noqa: E402

# ---------------------------------------------------------------- LiveKit Agents imports (with graceful fallback for scaffold check without deps)
try:
    from livekit.agents import Agent, AgentSession, JobContext, AgentServer, cli

    LIVEKIT_AVAILABLE = True
except ImportError as e:
    LIVEKIT_AVAILABLE = False
    log.warning("livekit-agents not installed (scaffold mode): %s", e)
    Agent = object  # type: ignore
    AgentSession = object  # type: ignore
    JobContext = object  # type: ignore
    AgentServer = object  # type: ignore  # type: ignore

# Inference + VAD + TurnDetector (LiveKit Inference, built-in 1.7.1)
try:
    from livekit.agents import inference  # type: ignore

    _HAS_INFERENCE = True
except ImportError:
    inference = None  # type: ignore
    _HAS_INFERENCE = False

# TurnHandlingOptions location changed in 1.7.x (was livekit.agents.voice, now livekit.agents)
try:
    from livekit.agents import TurnHandlingOptions  # type: ignore

    _HAS_TURN_HANDLING = True
except ImportError:
    try:
        from livekit.agents.voice.turn import TurnHandlingOptions  # type: ignore

        _HAS_TURN_HANDLING = True
    except ImportError:
        TurnHandlingOptions = None  # type: ignore
        _HAS_TURN_HANDLING = False

# Silero fallback (optional) — preferred is inference.VAD (livekit-local-inference)
try:
    from livekit.plugins import silero as silero_plugin  # type: ignore

    _HAS_SILERO = True
except ImportError:
    silero_plugin = None  # type: ignore
    _HAS_SILERO = False


# ---------------------------------------------------------------- helpers
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_room_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "taptalent-interview"


def _resolve_config(ctx: JobContext | None) -> InterviewConfig:
    """Resolve InterviewConfig from room metadata → participant metadata → job metadata → env."""
    metadata = None
    room_name = None
    if ctx is not None:
        try:
            room_name = getattr(ctx.room, "name", None) if hasattr(ctx, "room") else None
            metadata = getattr(ctx.room, "metadata", None) if hasattr(ctx, "room") else None
            # Fallback: check remote participants' metadata (frontend sets it on the candidate token)
            if not metadata and hasattr(ctx, "room") and hasattr(ctx.room, "remote_participants"):
                for p in ctx.room.remote_participants.values():
                    p_meta = getattr(p, "metadata", None)
                    if p_meta:
                        metadata = p_meta
                        log.info("config from participant metadata identity=%s", getattr(p, "identity", "?"))
                        break
            if not metadata and hasattr(ctx, "job"):
                metadata = getattr(ctx.job, "metadata", None)
        except Exception:
            pass
    cfg = InterviewConfig.from_room_metadata(metadata, room_name=room_name)
    if ctx is None or not room_name:
        env_cfg = InterviewConfig.from_env()
        if room_name:
            env_cfg.roomName = room_name
        if not cfg.candidateName:
            cfg = env_cfg
    return cfg


# ---------------------------------------------------------------- Agent definition
if LIVEKIT_AVAILABLE:
    server = AgentServer()

    class InterviewerAgent(Agent):
        """LiveKit Agents Agent — conducts the structured interview.

        We suppress the automatic LLM reply for user turns (on_user_turn_completed)
        so the manual interview loop in entrypoint can drive questions sequentially
        and avoid double-generation / loop contention.
        """

        def __init__(self, config: InterviewConfig, state: InterviewState, interview_id: str):
            super().__init__(
                instructions=build_system_prompt(
                    candidateName=config.candidateName,
                    jobTitle=config.jobTitle,
                    currentQuestionIndex=state.currentQuestionIndex,
                    questions=config.questions,
                )
            )
            self.config = config
            self.state = state
            self.interview_id = interview_id

        async def on_user_turn_completed(self, turn_ctx, new_message):  # type: ignore[override]
            # Suppress automatic per-turn LLM generation — interview loop drives
            # acknowledgements manually via session.generate_reply(instructions=user_prompt)
            # This prevents "skipping reply to user input, current speech generation
            # cannot be interrupted" contention when we are already speaking a question.
            try:
                from livekit.agents.llm import StopResponse

                raise StopResponse()
            except ImportError:
                # Fallback: if StopResponse not available, just return without generating
                return

    # ---------------------------------------------------------------- entrypoint
    @server.rtc_session()
    async def entrypoint(ctx: JobContext):
        await ctx.connect()
        log.info("job received room=%s", getattr(ctx.room, "name", "?"))

        config = _resolve_config(ctx)
        log.info(
            "resolved config room=%s candidate=%r job=%r questions=%d",
            config.roomName,
            config.candidateName,
            config.jobTitle,
            len(config.questions),
        )

        # Use backend-generated interview ID from metadata if available (fixes frontend polling mismatch)
        interview_id = config.interviewId if config.interviewId else (
            _sanitize_room_name(ctx.room.name) + "-" + uuid.uuid4().hex[:6]
        )
        state = InterviewState(
            candidateName=config.candidateName,
            jobTitle=config.jobTitle,
            questions=list(config.questions),
            currentQuestionIndex=0,
            conversationHistory=[],
            status="in_progress",
            startedAt=_now_iso(),
        )
        state.audioRecordingPath = f"recordings/{interview_id}.webm"

        # Validate config (C-01) — exit gracefully if invalid (agents.md §2.2)
        errors = config.validate()
        if errors:
            log.error("invalid config id=%s errors=%s — aborting", interview_id, errors)
            state.status = "failed"
            await persist(state, interview_id)
            try:
                await ctx.room.disconnect()
            except Exception:
                pass
            return

        # --- LiveKit Inference wiring (single provider, no Deepgram/Groq/ElevenLabs keys) ---
        # Models via LiveKit Inference — billed via LiveKit Cloud, zero data retention.
        # See https://docs.livekit.io/agents/models/inference/ and https://livekit.com/products/inference
        # NOTE: We reference Deepgram/Cartesia model NAMES (e.g. deepgram/nova-3, cartesia/sonic-3)
        # but they are NOT separate Deepgram/Cartesia accounts — they are routed & billed
        # solely through LiveKit Cloud via your LIVEKIT_API_KEY/SECRET. No DEEPGRAM_API_KEY needed.
        stt_model = os.getenv("INFERENCE_STT_MODEL", "deepgram/nova-3")
        llm_model = os.getenv("INFERENCE_LLM_MODEL", "openai/gpt-4.1-mini")
        tts_model = os.getenv("INFERENCE_TTS_MODEL", "cartesia/sonic-3")
        tts_voice = os.getenv("INFERENCE_TTS_VOICE", "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc")
        stt_language = os.getenv("INFERENCE_STT_LANGUAGE", "en")

        log.info(
            "inference interview_id=%s stt=%s llm=%s tts=%s voice=%s",
            interview_id,
            stt_model,
            llm_model,
            tts_model,
            tts_voice,
        )

        # Build STT / LLM / TTS via LiveKit Inference (no separate plugin packages)
        stt = llm = tts = None  # type: ignore
        if _HAS_INFERENCE:
            try:
                try:
                    stt = inference.STT(model=stt_model, language=stt_language)  # type: ignore
                except TypeError:
                    stt = f"{stt_model}"  # type: ignore
                    log.info("using STT string shortcut %s", stt)
            except Exception as e:
                log.warning("inference.STT init failed (%s) — trying string shortcut", e)
                stt = stt_model  # fallback string
            try:
                llm = inference.LLM(model=llm_model)  # type: ignore
            except Exception as e:
                log.warning("inference.LLM init failed (%s) — trying string shortcut", e)
                llm = llm_model  # fallback string
            try:
                try:
                    tts = inference.TTS(model=tts_model, voice=tts_voice)  # type: ignore
                except TypeError:
                    tts = f"{tts_model}:{tts_voice}" if tts_voice else tts_model  # type: ignore
                    log.info("using TTS string shortcut %s", tts)
            except Exception as e:
                log.warning("inference.TTS init failed (%s) — trying string shortcut", e)
                tts = f"{tts_model}:{tts_voice}" if tts_voice else tts_model
        else:
            stt = stt_model  # type: ignore
            llm = llm_model  # type: ignore
            tts = f"{tts_model}:{tts_voice}" if tts_voice else tts_model  # type: ignore
            log.warning("inference module not available — using string shortcuts stt=%s llm=%s tts=%s", stt, llm, tts)

        # --- VAD + TurnDetector wiring (fixes "turn_detection is set to 'vad', but no VAD model" warning) ---
        # VAD is required for accurate turn boundaries; inference.VAD uses livekit-local-inference
        # (no separate silero plugin needed). We also support silero.VAD as fallback.
        vad = None
        vad_source = "none"
        if _HAS_INFERENCE:
            try:
                vad = inference.VAD()  # type: ignore # defaults to silero via livekit-local-inference
                vad_source = "inference.VAD"
                log.info("vad: inference.VAD (built-in, livekit-local-inference)")
            except Exception as e:
                log.warning("inference.VAD init failed: %s", e)
        if vad is None and _HAS_SILERO:
            try:
                vad = silero_plugin.VAD.load()  # type: ignore
                vad_source = "silero.VAD"
                log.info("vad: silero.VAD (fallback plugin)")
            except Exception as e:
                log.warning("silero.VAD.load failed: %s", e)
        if vad is None:
            log.warning("no VAD available — turn detection will be degraded; install livekit-agents + livekit-local-inference")

        # TurnDetector — semantic EOT model (cloud + local fallback), requires VAD
        turn_detector = None
        if _HAS_INFERENCE:
            try:
                # inference.TurnDetector is the built-in 1.6.1+ detector (requires vad)
                if vad is not None and hasattr(inference, "TurnDetector"):
                    turn_detector = inference.TurnDetector()  # type: ignore
                    log.info("turn_detector: inference.TurnDetector (built-in)")
                elif hasattr(inference, "TurnDetector"):
                    # Still create but will warn if vad missing — we handle fallback below
                    turn_detector = inference.TurnDetector()  # type: ignore
                    log.warning("TurnDetector created without VAD — will fallback if needed")
            except Exception as e:
                log.warning("TurnDetector init failed: %s", e)
                turn_detector = None

        # --- AgentSession with correct TurnHandlingOptions (fixes loop contention) ---
        # Key fixes for the two reported warnings:
        # 1. VAD missing → now we provide vad=inference.VAD() so TurnDetector has required VAD
        # 2. Loop contention (allow_interruptions=False + fragmented STT) → disable interruptions
        #    via turn_handling["interruption"]["enabled"]=False AND disable preemptive_generation
        #    so the session doesn't try to generate while previous speech is playing.
        #    Also increase endpointing min_delay to avoid cutting off candidate mid-pause.
        session = None  # type: ignore
        try:
            if turn_detector is not None and vad is not None:
                # Modern 1.7.x path: vad + TurnDetector with full TurnHandlingOptions dict
                turn_handling = {
                    "turn_detection": turn_detector,
                    "endpointing": {"min_delay": 0.9, "max_delay": 3.5},
                    "interruption": {"enabled": False},
                    "preemptive_generation": {"enabled": False},
                }
                session = AgentSession(stt=stt, llm=llm, tts=tts, vad=vad, turn_handling=turn_handling)  # type: ignore
                log.info("AgentSession: vad=%s turn_detector=TurnDetector endpointing=0.9/3.5 interruption=off preemptive=off", vad_source)
            elif turn_detector is not None:
                turn_handling = {
                    "turn_detection": turn_detector,
                    "endpointing": {"min_delay": 0.9, "max_delay": 3.5},
                    "interruption": {"enabled": False},
                    "preemptive_generation": {"enabled": False},
                }
                session = AgentSession(stt=stt, llm=llm, tts=tts, turn_handling=turn_handling)  # type: ignore
                log.info("AgentSession: turn_detector only (no vad), endpointing=0.9/3.5")
            elif vad is not None:
                turn_handling = {
                    "endpointing": {"min_delay": 0.9, "max_delay": 3.5},
                    "interruption": {"enabled": False},
                    "preemptive_generation": {"enabled": False},
                }
                session = AgentSession(stt=stt, llm=llm, tts=tts, vad=vad, turn_handling=turn_handling)  # type: ignore
                log.info("AgentSession: vad only, endpointing=0.9/3.5")
            else:
                # Fallback: string models without explicit vad/turn_detector — AgentSession will default to inference.VAD internally (1.7.1)
                session = AgentSession(stt=stt, llm=llm, tts=tts, turn_handling={"endpointing": {"min_delay": 0.9}, "interruption": {"enabled": False}, "preemptive_generation": {"enabled": False}})  # type: ignore
                log.info("AgentSession: fallback without explicit vad/turn_detector")
        except Exception as e:
            log.warning("AgentSession with VAD/TurnDetector failed: %s — trying plain", e, exc_info=True)
            try:
                session = AgentSession(stt=stt, llm=llm, tts=tts, vad=vad) if vad is not None else AgentSession(stt=stt, llm=llm, tts=tts)  # type: ignore
            except Exception as e2:
                log.error("AgentSession creation failed: %s", e2, exc_info=True)
                state.status = "failed"
                await persist(state, interview_id)
                return  # type: ignore

        if session is None:
            try:
                session = AgentSession(stt=stt, llm=llm, tts=tts, vad=vad) if vad is not None else AgentSession(stt=stt, llm=llm, tts=tts)  # type: ignore
            except Exception as e:
                log.error("AgentSession creation failed: %s", e, exc_info=True)
                state.status = "failed"
                await persist(state, interview_id)
                return

        # --- State: transcript queue + F-02 handler (agents.md §2.6) ---
        transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        # Tracks last time ANY transcript (final or interim) arrived — used to avoid
        # cutting off mid-sentence when Deepgram sends a premature final=True
        # followed by interim continuations (e.g. "I am out of" final, then
        # "I am a software engineer..." interim). Silence timer resets on interim.
        last_speech_time: list[float] = [0.0]

        @session.on("user_input_transcribed")  # type: ignore
        def on_transcript(ev):  # type: ignore
            try:
                transcript = getattr(ev, "transcript", None) or getattr(ev, "text", None) or str(ev)
                transcript = str(transcript).strip()
                if not transcript:
                    return
                is_final = getattr(ev, "is_final", True)  # default to final if attribute missing
                log.info("transcript interview_id=%s idx=%d final=%s text=%r", interview_id, state.currentQuestionIndex, is_final, transcript[:120])
                # Update speech activity timestamp on ANY transcript (final or interim)
                # so silence detection accounts for ongoing streaming speech.
                try:
                    last_speech_time[0] = asyncio.get_event_loop().time()
                except Exception:
                    import time as _t

                    last_speech_time[0] = _t.monotonic()
                # Only enqueue final transcripts; interim is used only to extend silence window
                if is_final:
                    transcript_queue.put_nowait(transcript)
            except Exception as e:
                log.error("on_transcript handler error: %s", e, exc_info=True)

        # Capture AI turns via conversation_item_added (for LLM-generated acks)
        # Deterministic questions/intro/closing are already appended via say_with_fallback
        @session.on("conversation_item_added")  # type: ignore
        def on_conversation_item(ev):  # type: ignore
            try:
                item = getattr(ev, "item", None)
                if item is None:
                    return
                role = getattr(item, "role", None)
                # Only care about assistant messages that are LLM-generated acks
                if role != "assistant":
                    return
                text = ""
                try:
                    text = str(item.text_content or "").strip()  # type: ignore
                    if not text:
                        text = str(getattr(item, "raw_text_content", "") or "").strip()
                except Exception:
                    text = str(getattr(item, "content", "") or "").strip()
                if not text:
                    return
                # Filter out our deterministic messages already in history to avoid duplicates
                # If last AI turn already equals this text (e.g. question), skip
                if state.conversationHistory and state.conversationHistory[-1].speaker == "AI" and state.conversationHistory[-1].text == text:
                    return
                # Only log here; actual persistence is handled after generate_reply returns
                # We append asynchronously to avoid blocking event loop
                log.info("ai_conversation_item interview_id=%s text=%r", interview_id, text[:100])
                # Don't auto-append here to avoid race with say_with_fallback; instead let the ack loop handle it
                # But keep for observability
            except Exception as e:
                log.debug("on_conversation_item error: %s", e)

        # --- A-05: disconnect handler — must not throw (agents.md §2.7) ---
        try:
            @ctx.room.on("participant_disconnected")  # type: ignore
            def _on_disconnected(participant):  # type: ignore
                try:
                    if participant.identity == ctx.room.local_participant.identity:
                        return
                    log.warning(
                        "participant_disconnected interview_id=%s participant=%s — marking abandoned",
                        interview_id,
                        participant.identity,
                    )
                    state.status = "abandoned"
                    state.durationSeconds = state.compute_duration()
                    asyncio.create_task(persist(state, interview_id))
                except Exception as e:
                    log.error("disconnect handler error: %s", e)
        except Exception as e:
            log.warning("failed to register participant_disconnected handler: %s", e)

        # --- Wait for participant then connect session ---
        agent = InterviewerAgent(config=config, state=state, interview_id=interview_id)

        # Wait for the candidate to join so the session knows whose audio to listen to
        participant = None
        try:
            participant = await ctx.wait_for_participant()  # blocks until a remote participant connects
            log.info("participant connected identity=%s", participant.identity)
        except Exception as e:
            log.warning("wait_for_participant failed (%s) — starting session without explicit participant", e)

        try:
            if participant is not None:
                await session.start(room=ctx.room, agent=agent)  # type: ignore
            else:
                await session.start(room=ctx.room, agent=agent)  # type: ignore
        except Exception as e:
            log.error("session.start failed: %s", e, exc_info=True)
            state.status = "failed"
            await persist(state, interview_id)
            return

        # Helper: generate_reply with TTS fallback (F-03) + AI turn append
        async def say_with_fallback(text: str, tag: str = "AI") -> bool:
            try:
                await session.generate_reply(instructions=text)  # type: ignore
                state.conversationHistory.append(Turn(speaker="AI", text=text, timestamp=_now_iso()))
                await persist(state, interview_id)
                return True
            except Exception as e:
                log.error(
                    "TTS/generate_reply failed interview_id=%s idx=%d text=%r error=%s",
                    interview_id,
                    state.currentQuestionIndex,
                    text[:80],
                    e,
                    exc_info=True,
                )
                # F-03: text-only fallback via data channel so candidate still sees transition
                try:
                    if hasattr(ctx.room, "local_participant") and ctx.room.local_participant:
                        await ctx.room.local_participant.publish_data(
                            json.dumps({"type": "transcript", "speaker": "AI", "text": text, "fallback": "tts_failed"}).encode(),
                            reliable=True,
                        )
                except Exception:
                    pass
                state.conversationHistory.append(Turn(speaker="AI", text=text, timestamp=_now_iso()))
                await persist(state, interview_id)
                return False

        # Helper: drain stale transcripts before asking next question
        def _drain_queue():
            count = 0
            while not transcript_queue.empty():
                try:
                    transcript_queue.get_nowait()
                    count += 1
                except Exception:
                    break
            if count:
                log.info("drained %d stale transcripts before Q%d", count, state.currentQuestionIndex + 1)
            # Reset speech activity so next answer's silence window starts fresh
            try:
                last_speech_time[0] = asyncio.get_event_loop().time()
            except Exception:
                import time as _t

                last_speech_time[0] = _t.monotonic()

        # Helper: wait for transcript with VAD-aware debounce + F-01 reprompt logic
        # SILENCE_GAP counts from last ANY speech (final or interim) — interim
        # resets the timer so premature final=True ("I am out of") doesn't cut off
        # the ongoing utterance while Deepgram still streams interim.
        SILENCE_GAP = 1.8  # seconds of silence after last speech activity before considering answer complete

        async def _collect_fragments(timeout: float) -> str:
            """Drain transcript queue, accumulating final fragments until SILENCE_GAP silence since last ANY speech."""
            fragments: list[str] = []
            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break
                if not fragments:
                    wait_time = remaining
                else:
                    # Silence must be SILENCE_GAP since last ANY transcript (final or interim)
                    elapsed_since_speech = loop.time() - last_speech_time[0]
                    silence_remaining = SILENCE_GAP - elapsed_since_speech
                    if silence_remaining <= 0:
                        break
                    wait_time = min(silence_remaining, remaining)
                try:
                    fragment = await asyncio.wait_for(transcript_queue.get(), timeout=wait_time)
                    if fragment and fragment.strip():
                        fragments.append(fragment.strip())
                        log.debug("fragment collected: %r (total=%d)", fragment[:60], len(fragments))
                except asyncio.TimeoutError:
                    if fragments:
                        # Only finish if we've had true silence since last speech activity
                        if loop.time() - last_speech_time[0] >= SILENCE_GAP:
                            break
                        # Interim arrived recently — keep waiting for next final
                        continue
                    if not fragments and (deadline - loop.time()) <= 0:
                        break
                    # No fragments yet but deadline not reached — keep waiting for first final
                    if not fragments:
                        continue
                except Exception as e:
                    log.error("_collect_fragments error: %s", e)
                    break
            return " ".join(fragments) if fragments else ""

        async def wait_for_answer(timeout: float = 60.0) -> str:
            answer = await _collect_fragments(timeout)
            if answer:
                # Append candidate turn and persist (F-02: before LLM call)
                state.conversationHistory.append(Turn(speaker="Candidate", text=answer, timestamp=_now_iso()))
                asyncio.create_task(persist(state, interview_id))
                return answer

            # Empty/timeout → F-01: reprompt once via generate_reply
            log.warning("STT empty/timeout interview_id=%s idx=%d — reprompting (F-01)", interview_id, state.currentQuestionIndex)
            try:
                await say_with_fallback(stt_reprompt())
            except Exception:
                pass
            answer2 = await _collect_fragments(45.0)
            if answer2:
                state.conversationHistory.append(Turn(speaker="Candidate", text=answer2, timestamp=_now_iso()))
                asyncio.create_task(persist(state, interview_id))
                return answer2

            log.warning("STT still empty interview_id=%s idx=%d — using [inaudible] (F-01)", interview_id, state.currentQuestionIndex)
            return "[inaudible]"

        # ---------------------------------------------------------------- Intro (A-02/A-03) — not a question, currentQuestionIndex stays 0
        intro = intro_message(config.candidateName, config.jobTitle, state.totalQuestions)
        log.info("intro interview_id=%s", interview_id)
        await say_with_fallback(intro)
        await asyncio.sleep(0.8)

        # ---------------------------------------------------------------- Turn Loop (T-01..T-05, C-03 ordered)
        for idx in range(len(config.questions)):
            state.currentQuestionIndex = idx
            question_text = config.questions[idx]
            log.info("asking Q%d/%d interview_id=%s", idx + 1, len(config.questions), interview_id)

            # Drain any stale fragments that arrived during intro/previous ack TTS (when agent was speaking)
            # These were buffered while interruption was disabled and should be discarded (fixes overlap)
            _drain_queue()

            # T-04: ask question via generate_reply (agents.md §2.4)
            await say_with_fallback(question_text)
            await persist(state, interview_id)

            if state.status == "abandoned":
                log.info("abandoned before answer Q%d interview_id=%s", idx + 1, interview_id)
                break

            # Clear any audio captured while question TTS was playing (interruption disabled → must be discarded)
            # This prevents the agent hearing its own echo or candidate's premature "hello" during TTS as answer.
            _drain_queue()
            await asyncio.sleep(0.3)  # brief echo-tail grace before listening

            # T-01: STT — transcript arrives via user_input_transcribed event (F-02 ordering handled there)
            transcript = await wait_for_answer(timeout=75.0)

            # wait_for_answer already appends real transcripts; only handle [inaudible] fallback
            if transcript == "[inaudible]":
                state.conversationHistory.append(Turn(speaker="Candidate", text=transcript, timestamp=_now_iso()))
                await persist(state, interview_id)

            if state.status == "abandoned":
                log.info("abandoned after answer Q%d interview_id=%s", idx + 1, interview_id)
                break

            # T-02/T-03: Acknowledgement/transition via LLM (F-02: 1 retry, then fallback)
            # The InterviewerAgent suppresses auto LLM, so we drive ack manually here.
            # We capture the LLM-generated text via SpeechHandle or fallback to deterministic ack.
            user_prompt = build_user_message(idx=idx, question_text=question_text, transcript=transcript)
            ack_text: str | None = None
            llm_ack_captured: str | None = None
            for attempt in range(2):  # 1 retry = 2 attempts (PRD §7, agents.md §2.7)
                try:
                    # generate_reply returns SpeechHandle; we await its completion to get actual TTS text
                    handle = session.generate_reply(instructions=user_prompt)  # type: ignore
                    # handle is SpeechHandle — wait for playout without raising (per docs)
                    try:
                        await handle  # type: ignore
                    except Exception:
                        pass
                    # Try to extract generated text from chat context (last assistant message)
                    try:
                        if hasattr(session, "_chat_ctx") and session._chat_ctx.items:  # type: ignore
                            last = session._chat_ctx.items[-1]  # type: ignore
                            if getattr(last, "role", None) == "assistant":
                                llm_ack_captured = str(last.text_content or last.raw_text_content or "").strip()  # type: ignore
                        if not llm_ack_captured and hasattr(session, "chat_ctx") and getattr(session, "chat_ctx", None):  # type: ignore
                            items = session.chat_ctx.items  # type: ignore
                            if items and getattr(items[-1], "role", None) == "assistant":
                                llm_ack_captured = str(items[-1].text_content or "").strip()  # type: ignore
                    except Exception:
                        pass
                    if llm_ack_captured:
                        state.conversationHistory.append(Turn(speaker="AI", text=llm_ack_captured, timestamp=_now_iso()))
                        await persist(state, interview_id)
                        log.info("llm ack captured interview_id=%s idx=%d text=%r", interview_id, idx, llm_ack_captured[:80])
                    else:
                        # Fallback: if we couldn't capture, use deterministic transition so transcript stays complete
                        # Don't duplicate — the LLM did speak, we just didn't capture text
                        log.info("llm ack generated but text not captured interview_id=%s idx=%d", interview_id, idx)
                    ack_text = None
                    break
                except Exception as e:
                    log.error(
                        "LLM/generate_reply failed interview_id=%s idx=%d attempt=%d error=%s",
                        interview_id,
                        idx,
                        attempt + 1,
                        e,
                        exc_info=True,
                    )
                    if attempt == 0:
                        log.info("LLM retrying interview_id=%s idx=%d (1 retry per F-02)", interview_id, idx)
                        continue
                    log.warning("LLM second failure interview_id=%s idx=%d — using fallback ack", interview_id, idx)
                    ack_text = fallback_ack(config.candidateName)
                    await say_with_fallback(ack_text)
                    break

            # T-04/T-05: advance
            state.currentQuestionIndex = idx + 1
            await persist(state, interview_id)
            await asyncio.sleep(0.6)

            if state.status == "abandoned":
                break

        # --- Closing (E-01/E-02) — deterministic, not LLM ---
        if state.status != "abandoned":
            closing = closing_message(config.candidateName)
            log.info("closing interview_id=%s", interview_id)
            await say_with_fallback(closing)
            state.status = "completed"
            state.durationSeconds = state.compute_duration()
            await persist(state, interview_id)
            log.info("interview completed interview_id=%s duration=%ds", interview_id, state.durationSeconds)
        else:
            log.info("interview abandoned interview_id=%s duration=%ds", interview_id, state.durationSeconds)

        # --- Shutdown (A-04/E-03) ---
        try:
            maybe_coro = session.shutdown()  # type: ignore
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
        except Exception as e:
            log.warning("session.shutdown error: %s", e)
        try:
            await ctx.room.disconnect()
        except Exception:
            pass

    # ---------------------------------------------------------------- CLI startup
    if __name__ == "__main__":
        cli.run_app(server)

else:
    if __name__ == "__main__":
        import sys

        print("livekit-agents not installed — scaffold mode. Install with: pip install -r requirements.txt")
        print("Would resolve config:", InterviewConfig.from_env().to_dict())
        sys.exit(0)
