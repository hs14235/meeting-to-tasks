import { type DragEvent, useRef, useState } from "react";

import { useToast } from "./Toast";

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8000";

export default function UploadCard() {
  const fileRef = useRef<HTMLInputElement | null>(null);
  const { error, success } = useToast();

  const [meetingId, setMeetingId] = useState("mtg-001");
  const [title, setTitle] = useState("Weekly sync");
  const [msg, setMsg] = useState("Supported uploads: UTF-8 .txt and .md transcripts.");
  const [drag, setDrag] = useState(false);

  async function doUpload(file?: File) {
    if (!meetingId.trim()) {
      error("Meeting ID required", "Choose the meeting ID that should own this transcript.");
      return;
    }

    const selectedFile = file ?? fileRef.current?.files?.[0];
    if (!selectedFile) {
      error("Choose a file first");
      return;
    }

    const form = new FormData();
    form.append("file", selectedFile);
    form.append("meeting_id", meetingId.trim());
    form.append("title", title.trim());

    setMsg("Uploading and indexing transcript...");

    try {
      const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: form });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        setMsg("Upload failed.");
        error("Upload failed", data);
        return;
      }

      setMsg(`Indexed ${selectedFile.name} under ${meetingId.trim()}.`);
      success("Upload and indexing complete", { meetingId: meetingId.trim(), title: title.trim() });
      window.dispatchEvent(new CustomEvent("mtg-added", { detail: { id: meetingId.trim() } }));
      if (fileRef.current) {
        fileRef.current.value = "";
      }
    } catch (err) {
      setMsg("Could not reach the backend.");
      error("Upload failed", err instanceof Error ? err.message : "Unknown network error");
    }
  }

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDrag(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      await doUpload(file);
    }
  }

  return (
    <div className="cardStack">
      <div className="field">
        <span className="fieldLabel">Meeting ID</span>
        <input
          className="txt"
          value={meetingId}
          onChange={(event) => setMeetingId(event.target.value)}
          placeholder="meeting id"
        />
      </div>

      <div className="field">
        <span className="fieldLabel">Optional title</span>
        <input
          className="txt"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          placeholder="meeting title"
        />
      </div>

      <div
        className={`dropzone ${drag ? "is-dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <p className="dropTitle">Drop a transcript here</p>
        <p className="dropHelp">Accepted: UTF-8 .txt and .md files only.</p>
        <label className="browseLink">
          Browse files
          <input
            ref={fileRef}
            type="file"
            accept=".txt,.md,text/plain,text/markdown"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) {
                void doUpload(file);
              }
            }}
          />
        </label>
      </div>

      <div className="uploadFooter">
        <button className="btn btn-primary" onClick={() => void doUpload()}>
          Upload and index
        </button>
        <p className="helperText">{msg}</p>
      </div>
    </div>
  );
}
