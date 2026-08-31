import { useEffect, useState } from "react";
import { InterviewRoom } from "./components/InterviewRoom.tsx";
import { TranscriptView } from "./components/TranscriptView.tsx";
import { AudioPlayer } from "./components/AudioPlayer.tsx";
import type { InterviewRecord } from "./types.ts";

const BACKEND = import.meta.env.VITE_BACKEND_URL || "http://localhost:3000";
const LIVEKIT_URL = import.meta.env.VITE_LIVEKIT_URL || "";

const DEFAULT_QUESTIONS = [
  "Tell me about yourself.",
  "What is your Node.js experience?",
  "Describe a challenging bug you fixed.",
];

type Phase = "setup" | "live" | "result";

// ─── SVG Icons ───
function MicIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
      <path d="M19 10v2a7 7 0 01-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </svg>
  );
}

function PlayIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  );
}

function RefreshIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  );
}

// ─── Main App ───
export default function App() {
  const [phase, setPhase] = useState<Phase>("setup");

  // Setup form
  const [candidateName, setCandidateName] = useState("Aarav");
  const [jobTitle, setJobTitle] = useState("Backend Engineer");
  const [questionsText, setQuestionsText] = useState(DEFAULT_QUESTIONS.join("\n"));
  const [busy, setBusy] = useState(false);
  const [setupError, setSetupError] = useState<string | null>(null);

  // Live session
  const [roomName, setRoomName] = useState("");
  const [token, setToken] = useState("");
  const [interviewId, setInterviewId] = useState<string | null>(null);

  // Result
  const [record, setRecord] = useState<InterviewRecord | null>(null);
  const [resultError, setResultError] = useState<string | null>(null);

  async function handleStart() {
    setSetupError(null);
    const questions = questionsText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);

    if (!candidateName.trim() || !jobTitle.trim() || questions.length === 0) {
      setSetupError("Please provide a candidate name, job title, and at least one question.");
      return;
    }
    if (!LIVEKIT_URL) {
      setSetupError("LiveKit URL is not configured. Set VITE_LIVEKIT_URL in your .env file.");
      return;
    }

    setBusy(true);
    try {
      const createRes = await fetch(`${BACKEND}/api/interviews`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidateName: candidateName.trim(), jobTitle: jobTitle.trim(), questions }),
      });
      const createData = await createRes.json();
      if (!createRes.ok) throw new Error(createData.error || createData.errors?.join(", ") || "Failed to create interview");
      const id: string = createData.id;
      const rName: string = createData.roomName;
      setInterviewId(id);
      setRoomName(rName);

      const metadata = JSON.stringify({ interviewId: id, candidateName: candidateName.trim(), jobTitle: jobTitle.trim(), questions, roomName: rName });
      const tokenRes = await fetch(`${BACKEND}/api/token`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ identity: `candidate-${candidateName.trim().replace(/\s+/g, "-")}-${id.slice(0, 6)}`, roomName: rName, metadata }),
      });
      const tokenData = await tokenRes.json();
      if (!tokenRes.ok) throw new Error(tokenData.error || "Failed to generate token");

      setToken(tokenData.token);
      setRoomName(tokenData.roomName);
      setPhase("live");
    } catch (e: any) {
      setSetupError(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  async function fetchResult(id: string) {
    setResultError(null);
    try {
      const r = await fetch(`${BACKEND}/api/interviews/${id}`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Failed to load interview");
      setRecord(data);
    } catch (e: any) {
      setResultError(e.message ?? String(e));
    }
  }

  useEffect(() => {
    if (phase === "result" && interviewId) fetchResult(interviewId);
  }, [phase, interviewId]);

  // Poll while live
  useEffect(() => {
    if (phase !== "live" || !interviewId) return;
    const t = setInterval(() => {
      fetch(`${BACKEND}/api/interviews/${interviewId}`)
        .then((r) => r.json())
        .then(setRecord)
        .catch(() => {});
    }, 4000);
    return () => clearInterval(t);
  }, [phase, interviewId]);

  return (
    <div className="app-shell">
      {/* ─── Navbar ─── */}
      <nav className="navbar">
        <div className="navbar-brand">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
            <path d="M19 10v2a7 7 0 01-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="22" />
          </svg>
          TapTalent
        </div>
        <div className="navbar-meta">
          <span>AI Voice Interviewer</span>
        </div>
      </nav>

      {/* ─── Main Content ─── */}
      <main className="main-content">

        {/* ═══ SETUP PHASE ═══ */}
        {phase === "setup" && (
          <div className="card">
            <div className="card-header">
              <div>
                <div className="card-title">New Interview</div>
                <div className="card-subtitle">
                  Configure the candidate details and interview questions. The AI agent will conduct the interview in order.
                </div>
              </div>
            </div>

            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="candidate-name">Candidate name</label>
                <input
                  id="candidate-name"
                  className="form-input"
                  value={candidateName}
                  onChange={(e) => setCandidateName(e.target.value)}
                  placeholder="e.g. Aarav"
                />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="job-title">Job title</label>
                <input
                  id="job-title"
                  className="form-input"
                  value={jobTitle}
                  onChange={(e) => setJobTitle(e.target.value)}
                  placeholder="e.g. Backend Engineer"
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label" htmlFor="questions">
                Interview questions
                <span className="form-hint">— one per line</span>
              </label>
              <textarea
                id="questions"
                className="form-textarea"
                value={questionsText}
                onChange={(e) => setQuestionsText(e.target.value)}
                rows={5}
                placeholder={"Tell me about yourself.\nWhat is your experience with…\nDescribe a challenge you overcame."}
              />
            </div>

            <div className="btn-group">
              <button id="start-interview" className="btn btn-primary" onClick={handleStart} disabled={busy}>
                {busy ? (
                  <>Starting…</>
                ) : (
                  <>
                    <PlayIcon />
                    Start Interview
                  </>
                )}
              </button>
              <button className="btn btn-secondary" onClick={() => setQuestionsText(DEFAULT_QUESTIONS.join("\n"))}>
                Reset defaults
              </button>
            </div>

            {setupError && (
              <div className="alert alert-error" style={{ marginTop: 16 }}>
                {setupError}
              </div>
            )}

            {/* Connection info */}
            <div style={{ marginTop: 20, fontSize: 12, color: "var(--color-text-muted)", display: "flex", gap: 16 }}>
              <span>Backend: <code>{BACKEND}</code></span>
              <span>LiveKit: <code>{LIVEKIT_URL || "(not configured)"}</code></span>
            </div>
          </div>
        )}

        {/* ═══ LIVE PHASE ═══ */}
        {phase === "live" && token && roomName && (
          <>
            <InterviewRoom
              url={LIVEKIT_URL}
              token={token}
              roomName={roomName}
              candidateName={candidateName}
              onLeave={() => setPhase("result")}
            />

            <div className="btn-group" style={{ marginTop: 12 }}>
              <button className="btn btn-secondary btn-sm" onClick={() => setPhase("result")}>
                View Results
              </button>
              {interviewId && (
                <button className="btn btn-secondary btn-sm" onClick={() => fetchResult(interviewId)}>
                  <RefreshIcon /> Refresh
                </button>
              )}
            </div>

            {/* Live progress card */}
            {record && (
              <div className="card" style={{ marginTop: 12 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <h3 style={{ margin: 0 }}>Interview progress</h3>
                  <span className={`badge badge-${record.status}`}>{record.status.replace("_", " ")}</span>
                </div>
                <div className="stat-grid" style={{ marginTop: 12 }}>
                  <div className="stat-item">
                    <div className="stat-value">{record.currentQuestionIndex}/{record.questions.length}</div>
                    <div className="stat-label">Questions</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-value">{formatDuration(record.durationSeconds)}</div>
                    <div className="stat-label">Duration</div>
                  </div>
                  <div className="stat-item">
                    <div className="stat-value">{record.conversationHistory.length}</div>
                    <div className="stat-label">Turns</div>
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* ═══ RESULT PHASE ═══ */}
        {phase === "result" && (
          <>
            {/* Header card */}
            <div className="card">
              <div className="card-header" style={{ marginBottom: 0 }}>
                <div>
                  <div className="card-title">
                    {record ? `${record.candidateName} · ${record.jobTitle}` : "Interview Results"}
                  </div>
                  {record && (
                    <div className="card-subtitle">
                      Room <code>{record.roomName}</code> · ID <code>{record.id.slice(0, 12)}</code>
                    </div>
                  )}
                </div>
                <div className="btn-group">
                  {interviewId && (
                    <button className="btn btn-secondary btn-sm" onClick={() => fetchResult(interviewId)}>
                      <RefreshIcon /> Refresh
                    </button>
                  )}
                  <button className="btn btn-primary btn-sm" onClick={() => { setRecord(null); setPhase("setup"); }}>
                    <PlusIcon /> New Interview
                  </button>
                </div>
              </div>
            </div>

            {resultError && (
              <div className="alert alert-error" style={{ marginTop: 12 }}>{resultError}</div>
            )}

            {record ? (
              <>
                {/* Stats */}
                <div className="card">
                  <div className="stat-grid">
                    <div className="stat-item">
                      <div className="stat-value">
                        <span className={`badge badge-${record.status}`}>{record.status.replace("_", " ")}</span>
                      </div>
                      <div className="stat-label">Status</div>
                    </div>
                    <div className="stat-item">
                      <div className="stat-value">{formatDuration(record.durationSeconds)}</div>
                      <div className="stat-label">Duration</div>
                    </div>
                    <div className="stat-item">
                      <div className="stat-value">{record.currentQuestionIndex}/{record.questions.length}</div>
                      <div className="stat-label">Questions</div>
                    </div>
                    <div className="stat-item">
                      <div className="stat-value">{record.conversationHistory.length}</div>
                      <div className="stat-label">Turns</div>
                    </div>
                  </div>
                </div>

                {/* Transcript */}
                <div className="card">
                  <h2>Transcript</h2>
                  <TranscriptView turns={record.conversationHistory} />
                </div>

                {/* Recording */}
                <div className="card">
                  <h2>Recording</h2>
                  <AudioPlayer recordingPath={record.audioRecordingPath} />
                </div>

                {/* Debug JSON */}
                <div className="card">
                  <details>
                    <summary>Raw interview data</summary>
                    <pre className="json-block" style={{ marginTop: 8 }}>
                      {JSON.stringify(record, null, 2)}
                    </pre>
                  </details>
                </div>
              </>
            ) : (
              <div className="card">
                <div className="empty-state">Loading interview data…</div>
              </div>
            )}

            {/* Lookup */}
            <div className="card">
              <h3>Browse interviews</h3>
              <InterviewLookup onSelect={(id) => { setInterviewId(id); fetchResult(id); }} />
            </div>
          </>
        )}
      </main>

      {/* ─── Footer ─── */}
      <footer className="app-footer">
        TapTalent · AI Voice Interview Platform · LiveKit Agents · Deepgram · Groq · ElevenLabs
      </footer>
    </div>
  );
}

// ─── Duration formatter ───
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

// ─── Interview Lookup ───
function InterviewLookup({ onSelect }: { onSelect: (id: string) => void }) {
  const [id, setId] = useState("");
  const [list, setList] = useState<InterviewRecord[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function loadList() {
    setErr(null);
    try {
      const r = await fetch(`${BACKEND}/api/interviews`);
      const data = await r.json();
      if (!r.ok) throw new Error(data.error || "Failed to load");
      setList(data);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    }
  }

  useEffect(() => {
    loadList();
  }, []);

  return (
    <div>
      <div style={{ display: "flex", gap: 8 }}>
        <input
          className="form-input"
          placeholder="Interview ID"
          value={id}
          onChange={(e) => setId(e.target.value)}
          style={{ flex: 1 }}
        />
        <button className="btn btn-secondary btn-sm" onClick={() => id.trim() && onSelect(id.trim())}>
          Load
        </button>
        <button className="btn btn-secondary btn-sm" onClick={loadList}>
          <RefreshIcon />
        </button>
      </div>

      {err && <div className="alert alert-error" style={{ marginTop: 8 }}>{err}</div>}

      {list && list.length > 0 && (
        <div className="interview-list">
          {list.map((r) => (
            <button key={r.id} onClick={() => onSelect(r.id)} className="interview-list-item">
              <div className="interview-list-item-info">
                <span style={{ fontWeight: 600 }}>{r.candidateName}</span>
                <span className="text-muted">·</span>
                <span>{r.jobTitle}</span>
                <span className={`badge badge-${r.status}`}>{r.status.replace("_", " ")}</span>
              </div>
              <div className="interview-list-item-meta">
                {r.id.slice(0, 8)} · {r.currentQuestionIndex}/{r.questions.length} Q
              </div>
            </button>
          ))}
        </div>
      )}

      {list && list.length === 0 && (
        <div className="empty-state" style={{ padding: 16 }}>
          No interviews yet — start one above.
        </div>
      )}
    </div>
  );
}
