export function AudioPlayer({
  recordingPath,
  egressUrl,
}: {
  recordingPath?: string;
  egressUrl?: string | null;
}) {
  const backend = import.meta.env.VITE_BACKEND_URL || "http://localhost:3000";

  const src = recordingPath
    ? recordingPath.startsWith("/")
      ? `${backend}${recordingPath}`
      : `${backend}/${recordingPath}`
    : egressUrl || null;

  if (!src) {
    return (
      <div className="empty-state">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" style={{ marginBottom: 8, opacity: 0.4 }}>
          <path d="M12 2a3 3 0 00-3 3v7a3 3 0 006 0V5a3 3 0 00-3-3z" />
          <path d="M19 10v2a7 7 0 01-14 0v-2" />
          <line x1="12" y1="19" x2="12" y2="22" />
        </svg>
        <div>Recording will be available after the interview completes.</div>
      </div>
    );
  }

  return (
    <div className="audio-container">
      <audio controls src={src} style={{ width: "100%" }} preload="metadata" />
      <div className="audio-source">
        Source: <code>{src}</code>
      </div>
    </div>
  );
}
