import type { Turn } from "../types.ts";

export function TranscriptView({ turns }: { turns: Turn[] }) {
  if (!turns || turns.length === 0) {
    return (
      <div className="empty-state">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 8, opacity: 0.4 }}>
          <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
        </svg>
        <div>Transcript will appear once the interview begins.</div>
      </div>
    );
  }

  return (
    <div className="transcript-list">
      {turns.map((t, i) => (
        <div key={i} className={`turn ${t.speaker === "AI" ? "turn-ai" : "turn-candidate"}`}>
          <div className="turn-header">
            <span className="turn-speaker">
              {t.speaker === "AI" ? "AI Interviewer" : "Candidate"}
            </span>
            <span className="turn-time">
              {new Date(t.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          </div>
          <div className="turn-text">{t.text}</div>
        </div>
      ))}
    </div>
  );
}
