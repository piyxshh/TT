import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, RemoteParticipant } from "livekit-client";
import type { Turn } from "../types.ts";

type Props = {
  url: string;
  token: string;
  roomName: string;
  candidateName: string;
  onLeave: () => void;
  onTranscriptUpdate?: (turns: Turn[]) => void;
};

export function InterviewRoom({ url, token, roomName, candidateName, onLeave }: Props) {
  const roomRef = useRef<Room | null>(null);
  const [status, setStatus] = useState<"connecting" | "live" | "ended" | "error">("connecting");
  const [error, setError] = useState<string | null>(null);
  const [liveTranscript, setLiveTranscript] = useState<Turn[]>([]);
  const [participants, setParticipants] = useState<string[]>([]);
  const audioContainerRef = useRef<HTMLDivElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [liveTranscript]);

  useEffect(() => {
    const room = new Room({
      adaptiveStream: true,
      dynacast: true,
    });
    roomRef.current = room;
    let mounted = true;

    async function connect() {
      try {
        room.on(RoomEvent.TrackSubscribed, (track, _pub, participant) => {
          if (track.kind === Track.Kind.Audio) {
            const el = track.attach();
            (el as HTMLAudioElement).autoplay = true;
            audioContainerRef.current?.appendChild(el);
            setParticipants((prev) => (prev.includes(participant.identity) ? prev : [...prev, participant.identity]));
          }
        });

        room.on(RoomEvent.TrackUnsubscribed, (track) => {
          track.detach().forEach((el) => el.remove());
        });

        room.on(RoomEvent.ParticipantConnected, (p: RemoteParticipant) => {
          setParticipants((prev) => prev.includes(p.identity) ? prev : [...prev, p.identity]);
        });

        room.on(RoomEvent.ParticipantDisconnected, (p: RemoteParticipant) => {
          setParticipants((prev) => prev.filter((id) => id !== p.identity));
        });

        room.on(RoomEvent.DataReceived, (payload: Uint8Array) => {
          try {
            const msg = JSON.parse(new TextDecoder().decode(payload));
            if (msg.type === "transcript" && msg.text) {
              const turn: Turn = {
                speaker: msg.speaker === "Candidate" ? "Candidate" : "AI",
                text: msg.text,
                timestamp: new Date().toISOString(),
              };
              setLiveTranscript((prev) => [...prev, turn]);
            }
          } catch {
            // ignore non-JSON data
          }
        });

        room.on(RoomEvent.Disconnected, () => {
          if (mounted) setStatus("ended");
        });

        await room.connect(url, token);
        await room.localParticipant.setMicrophoneEnabled(true);

        if (mounted) {
          setStatus("live");
          setParticipants([...room.remoteParticipants.values()].map((p) => p.identity));
        }
      } catch (e: any) {
        console.error("[InterviewRoom] connect failed", e);
        if (mounted) {
          setError(e.message ?? String(e));
          setStatus("error");
        }
      }
    }

    connect();

    return () => {
      mounted = false;
      room.disconnect().catch(() => {});
      roomRef.current = null;
    };
  }, [url, token]);

  const handleLeave = async () => {
    try {
      await roomRef.current?.disconnect();
    } catch {}
    onLeave();
  };

  const dotClass =
    status === "live" ? "status-dot-live"
    : status === "connecting" ? "status-dot-connecting"
    : status === "error" ? "status-dot-error"
    : "status-dot-ended";

  const statusLabel =
    status === "connecting" ? "Connecting…"
    : status === "live" ? `Live · ${roomName}`
    : status === "ended" ? "Interview ended"
    : "Connection error";

  return (
    <div className="card">
      {/* Header bar */}
      <div className="session-bar">
        <div>
          <div className="session-status">
            <span className={`status-dot ${dotClass}`} />
            <span className="session-label">{statusLabel}</span>
          </div>
          <div className="session-meta">
            {candidateName} · {participants.length + 1} participant{participants.length !== 0 ? "s" : ""}
          </div>
        </div>
        <button className="btn btn-danger btn-sm" onClick={handleLeave}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4" />
            <polyline points="16 17 21 12 16 7" />
            <line x1="21" y1="12" x2="9" y2="12" />
          </svg>
          Leave
        </button>
      </div>

      {error && <div className="alert alert-error" style={{ marginTop: 16 }}>{error}</div>}

      {/* Hidden audio container */}
      <div ref={audioContainerRef} style={{ display: "none" }} aria-hidden />

      {/* Mic visualization */}
      <div className="mic-visualizer">
        <div className={`mic-ring ${status === "live" ? "active" : ""}`}>
          <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
            <path d="M19 10v2a7 7 0 01-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
        </div>
      </div>

      {/* Helpful tip */}
      <div className="session-info-box">
        <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
          {status === "connecting" && "Setting up your microphone and connecting to the room…"}
          {status === "live" && "Your microphone is active. Speak naturally — the AI interviewer will listen to your full answer before responding."}
          {status === "ended" && "The interview session has ended. You can view the full transcript and recording."}
          {status === "error" && "Unable to connect. Check your LiveKit credentials and try again."}
        </div>
      </div>

      {/* Live transcript */}
      {liveTranscript.length > 0 && (
        <div className="section-gap">
          <h3>Live transcript</h3>
          <div className="transcript-list" style={{ maxHeight: 300, overflowY: "auto" }}>
            {liveTranscript.map((t, i) => (
              <div key={i} className={`turn ${t.speaker === "AI" ? "turn-ai" : "turn-candidate"}`}>
                <div className="turn-header">
                  <span className="turn-speaker">{t.speaker === "AI" ? "AI Interviewer" : "Candidate"}</span>
                </div>
                <div className="turn-text">{t.text}</div>
              </div>
            ))}
            <div ref={transcriptEndRef} />
          </div>
        </div>
      )}
    </div>
  );
}
