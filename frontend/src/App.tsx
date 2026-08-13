import { type ChangeEvent, useEffect, useRef, useState } from "react";

import { useToast } from "./components/Toast";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string) ||
  `${window.location.protocol}//${window.location.hostname}:8000`;

type MeetingSummary = {
  id: string;
  title: string;
  chunk_count: number;
  updated_at: string;
};

type Chunk = {
  i: number;
  text: string;
  speaker?: string | null;
  timestamp?: string | null;
  start_line: number;
};

type Task = {
  title: string;
  body: string;
  labels: string[];
  assignee_hint?: string | null;
  due_hint?: string | null;
  source_i: number;
  confidence: number;
  source_text?: string;
};

type MeetingDetail = MeetingSummary & {
  raw_text: string;
  chunks: Chunk[];
  tasks: Task[];
};

type PreviewIssue = { repo: string; title: string; body: string; labels: string[] };
type Timings = { retrieval_ms?: number; extraction_ms?: number; total_ms?: number };
type Stage = "ready" | "indexing" | "retrieving" | "review" | "preview" | "publishing";

const FOCUS_OPTIONS = ["action items", "decisions", "follow-ups and blockers", "risks"];
const SAMPLE_REPO = "hs14235/meeting-to-tasks";

function Icon({ name }: { name: "spark" | "upload" | "github" | "clock" | "trash" | "check" }) {
  const paths = {
    spark: "M12 2l1.4 5.1L18 9l-4.6 1.9L12 16l-1.4-5.1L6 9l4.6-1.9L12 2zm6 12 .8 2.2L21 17l-2.2.8L18 20l-.8-2.2L15 17l2.2-.8L18 14z",
    upload: "M12 16V4m0 0L7 9m5-5 5 5M5 14v5h14v-5",
    github: "M9 19c-4 1.2-4-2-5-2m10 4v-3.1c0-.9.1-1.3-.4-1.8 3.2-.4 6.4-1.6 6.4-7A5.4 5.4 0 0018.5 5 5 5 0 0018.3 1S17 1 14 2.5a13.4 13.4 0 00-5 0C6 1 4.7 1 4.7 1A5 5 0 004.5 5 5.4 5.4 0 003 9.1c0 5.4 3.2 6.6 6.4 7-.5.5-.5 1-.4 1.8V21",
    clock: "M12 21a9 9 0 100-18 9 9 0 000 18zm0-13v5l3 2",
    trash: "M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7m4 4v6m4-6v6",
    check: "M5 12l4 4L19 6",
  };
  return (
    <svg aria-hidden="true" viewBox="0 0 24 24" fill={name === "spark" ? "currentColor" : "none"}>
      <path d={paths[name]} stroke={name === "spark" ? "none" : "currentColor"} strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.detail?.error || payload?.detail || payload?.error || "Request failed";
    throw new Error(typeof message === "string" ? message : JSON.stringify(message));
  }
  return payload as T;
}

export default function App() {
  const { error, success } = useToast();
  const fileRef = useRef<HTMLInputElement>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [meeting, setMeeting] = useState<MeetingDetail | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [activeSource, setActiveSource] = useState<number | null>(null);
  const [preview, setPreview] = useState<PreviewIssue[] | null>(null);
  const [stage, setStage] = useState<Stage>("ready");
  const [focus, setFocus] = useState(FOCUS_OPTIONS[0]);
  const [repo, setRepo] = useState(SAMPLE_REPO);
  const [timings, setTimings] = useState<Timings>({});
  const [demoMode, setDemoMode] = useState(false);
  const [mobilePanel, setMobilePanel] = useState<"transcript" | "tasks">("tasks");
  const [upload, setUpload] = useState({ meetingId: "", title: "", file: null as File | null });

  async function refreshMeetings(selectId?: string) {
    const data = await api<{ meetings: MeetingSummary[] }>("/meetings");
    setMeetings(data.meetings);
    const nextId = selectId || meeting?.id || data.meetings[0]?.id;
    if (nextId) await openMeeting(nextId);
  }

  async function openMeeting(id: string) {
    try {
      const detail = await api<MeetingDetail>(`/meetings/${encodeURIComponent(id)}`);
      setMeeting(detail);
      setTasks(detail.tasks || []);
      setSelected(new Set((detail.tasks || []).map((_, index) => index)));
      setActiveSource(detail.chunks[0]?.i ?? null);
      setPreview(null);
      setStage("ready");
    } catch (reason) {
      error("Could not open meeting", reason instanceof Error ? reason.message : reason);
    }
  }

  useEffect(() => {
    void Promise.all([
      refreshMeetings(),
      api<{ demo_mode: boolean }>("/healthz").then((health) => setDemoMode(health.demo_mode)),
    ]).catch((reason) => error("Backend unavailable", reason instanceof Error ? reason.message : reason));
  }, []);

  async function loadDemo() {
    setStage("indexing");
    try {
      const result = await api<{ meeting_id: string }>("/meetings/demo", { method: "POST" });
      await refreshMeetings(result.meeting_id);
      success("Demo meeting is ready", "Launch readiness is indexed with source evidence.");
    } catch (reason) {
      error("Could not load demo", reason instanceof Error ? reason.message : reason);
    } finally {
      setStage("ready");
    }
  }

  async function indexFile() {
    if (!upload.file || !upload.meetingId.trim()) {
      error("Transcript and meeting ID required");
      return;
    }
    setStage("indexing");
    const body = new FormData();
    body.append("file", upload.file);
    body.append("meeting_id", upload.meetingId.trim());
    body.append("title", upload.title.trim());
    try {
      await api("/upload", { method: "POST", body });
      await refreshMeetings(upload.meetingId.trim());
      setUpload({ meetingId: "", title: "", file: null });
      if (fileRef.current) fileRef.current.value = "";
      success("Transcript indexed", "The meeting is ready for retrieval and extraction.");
    } catch (reason) {
      error("Indexing failed", reason instanceof Error ? reason.message : reason);
    } finally {
      setStage("ready");
    }
  }

  async function extract() {
    if (!meeting) return;
    setStage("retrieving");
    setPreview(null);
    try {
      const result = await api<{ tasks: Task[]; mode: string; timings: Timings }>("/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_id: meeting.id, q: focus, k: 6 }),
      });
      setTasks(result.tasks);
      setSelected(new Set(result.tasks.map((_, index) => index)));
      setTimings(result.timings || {});
      setActiveSource(result.tasks[0]?.source_i ?? null);
      setStage("review");
      success(`${result.tasks.length} tasks extracted`, `${result.mode} mode with source mapping preserved.`);
    } catch (reason) {
      setStage("ready");
      error("Extraction failed", reason instanceof Error ? reason.message : reason);
    }
  }

  function updateTask(index: number, patch: Partial<Task>) {
    setTasks((current) => current.map((task, taskIndex) => (taskIndex === index ? { ...task, ...patch } : task)));
    setPreview(null);
  }

  async function saveDrafts() {
    if (!meeting) return;
    try {
      await api(`/meetings/${encodeURIComponent(meeting.id)}/tasks`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tasks }),
      });
      success("Draft edits saved");
    } catch (reason) {
      error("Could not save drafts", reason instanceof Error ? reason.message : reason);
    }
  }

  const approvedTasks = tasks.filter((_, index) => selected.has(index));

  async function previewIssues() {
    if (!meeting || !approvedTasks.length) return;
    setStage("preview");
    try {
      const result = await api<{ would_create: PreviewIssue[] }>("/issues/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo, meeting_id: meeting.id, tasks: approvedTasks }),
      });
      setPreview(result.would_create);
    } catch (reason) {
      error("Preview failed", reason instanceof Error ? reason.message : reason);
    } finally {
      setStage("review");
    }
  }

  async function publishIssues() {
    if (!meeting || !preview || demoMode) return;
    if (!window.confirm(`Create ${approvedTasks.length} GitHub issues in ${repo}?`)) return;
    setStage("publishing");
    try {
      const result = await api<{ created: { status: string }[] }>("/issues", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo, meeting_id: meeting.id, tasks: approvedTasks }),
      });
      const created = result.created.filter((item) => item.status === "created").length;
      const duplicates = result.created.filter((item) => item.status === "skipped-duplicate").length;
      success(`${created} issues created`, `${duplicates} duplicates safely skipped.`);
    } catch (reason) {
      error("Publishing failed", reason instanceof Error ? reason.message : reason);
    } finally {
      setStage("review");
    }
  }

  async function removeMeeting(id: string) {
    if (!window.confirm("Delete this indexed meeting and its drafts?")) return;
    try {
      await api(`/meetings/${encodeURIComponent(id)}`, { method: "DELETE" });
      setMeeting(null);
      setTasks([]);
      await refreshMeetings();
    } catch (reason) {
      error("Delete failed", reason instanceof Error ? reason.message : reason);
    }
  }

  function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] || null;
    setUpload((current) => ({
      ...current,
      file,
      meetingId: current.meetingId || file?.name.replace(/\.[^.]+$/, "").replace(/[^A-Za-z0-9_.-]/g, "-") || "",
      title: current.title || file?.name.replace(/\.[^.]+$/, "") || "",
    }));
  }

  const activeChunk = meeting?.chunks.find((chunk) => chunk.i === activeSource);

  return (
    <div className="appShell">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Meeting to Tasks home">
          <span className="brandMark"><Icon name="spark" /></span>
          <span>Meeting <i>to</i> Tasks</span>
        </a>
        <div className="topbarMeta">
          <span className="liveDot"><b /> MCP + REST online</span>
          <a href="https://github.com/hs14235/meeting-to-tasks" target="_blank" rel="noreferrer" className="iconButton" aria-label="Open GitHub repository"><Icon name="github" /></a>
        </div>
      </header>

      <div className="productGrid" id="top">
        <aside className="meetingRail" aria-label="Meeting library">
          <div className="railIntro">
            <span className="overline">Workspace</span>
            <h1>Turn talk into traction.</h1>
            <p>Source-grounded action items, reviewed by a human before they become GitHub work.</p>
          </div>

          <button className="demoButton" onClick={() => void loadDemo()} disabled={stage === "indexing"}>
            <Icon name="spark" /> Load polished demo
          </button>

          <div className="libraryHead"><span>Recent meetings</span><b>{meetings.length}</b></div>
          <nav className="meetingList">
            {meetings.map((item) => (
              <button key={item.id} className={`meetingItem ${meeting?.id === item.id ? "active" : ""}`} onClick={() => void openMeeting(item.id)}>
                <span className="meetingMonogram">{item.title.slice(0, 2).toUpperCase()}</span>
                <span><strong>{item.title}</strong><small>{item.chunk_count} source chunks</small></span>
              </button>
            ))}
            {!meetings.length && <p className="quietEmpty">No indexed meetings yet.</p>}
          </nav>

          <section className="importCard">
            <div className="importTitle"><Icon name="upload" /><span><strong>Import transcript</strong><small>UTF-8 .txt or .md</small></span></div>
            <input className="fieldInput" aria-label="Meeting ID" placeholder="meeting-id" value={upload.meetingId} onChange={(event) => setUpload({ ...upload, meetingId: event.target.value })} />
            <input className="fieldInput" aria-label="Meeting title" placeholder="Meeting title" value={upload.title} onChange={(event) => setUpload({ ...upload, title: event.target.value })} />
            <label className="filePicker">
              <input ref={fileRef} type="file" accept=".txt,.md,text/plain,text/markdown" onChange={chooseFile} />
              <span>{upload.file?.name || "Choose transcript"}</span>
            </label>
            <button className="primaryButton compact" onClick={() => void indexFile()} disabled={!upload.file || stage === "indexing"}>{stage === "indexing" ? "Indexing..." : "Index meeting"}</button>
          </section>
        </aside>

        <main className="workspace">
          {meeting ? (
            <>
              <header className="workspaceHead">
                <div>
                  <span className="overline">Meeting action workspace</span>
                  <h2>{meeting.title}</h2>
                  <p>{meeting.id} / {meeting.chunk_count} evidence chunks / updated {new Date(meeting.updated_at).toLocaleDateString()}</p>
                </div>
                <div className="workspaceActions">
                  <button className="secondaryButton dangerText" onClick={() => void removeMeeting(meeting.id)}><Icon name="trash" /> Delete</button>
                  <button className="primaryButton" onClick={() => void extract()} disabled={stage === "retrieving"}><Icon name="spark" /> {stage === "retrieving" ? "Finding work..." : "Extract actions"}</button>
                </div>
              </header>

              <section className="controlStrip" aria-label="Extraction controls">
                <div><span className="controlLabel">Focus</span><div className="focusTabs">{FOCUS_OPTIONS.map((option) => <button key={option} className={focus === option ? "active" : ""} onClick={() => setFocus(option)}>{option}</button>)}</div></div>
                <div className="pipelineStatus"><span className={`stageOrb ${stage}`} /><span><b>{stage === "retrieving" ? "Retrieving and extracting" : tasks.length ? `${tasks.length} drafts ready` : "Ready to extract"}</b><small>{timings.total_ms ? `${timings.total_ms.toFixed(0)} ms total pipeline` : "Hybrid retrieval / source mapped"}</small></span></div>
              </section>

              <div className="mobileTabs"><button className={mobilePanel === "transcript" ? "active" : ""} onClick={() => setMobilePanel("transcript")}>Transcript</button><button className={mobilePanel === "tasks" ? "active" : ""} onClick={() => setMobilePanel("tasks")}>Tasks {tasks.length ? `(${tasks.length})` : ""}</button></div>

              <div className="reviewGrid">
                <section className={`transcriptPane ${mobilePanel !== "transcript" ? "mobileHidden" : ""}`}>
                  <div className="paneHead"><div><span className="overline">Evidence</span><h3>Transcript</h3></div><span className="sourceCount">{meeting.chunks.length} chunks</span></div>
                  <div className="transcriptFlow">
                    {meeting.chunks.map((chunk) => (
                      <button key={chunk.i} className={`sourceBlock ${activeSource === chunk.i ? "active" : ""}`} onClick={() => setActiveSource(chunk.i)}>
                        <span className="sourceIndex">{String(chunk.i + 1).padStart(2, "0")}</span>
                        <span><small>{chunk.timestamp || `Line ${chunk.start_line}`}{chunk.speaker ? ` / ${chunk.speaker}` : ""}</small><span>{chunk.text}</span></span>
                      </button>
                    ))}
                  </div>
                </section>

                <section className={`taskPane ${mobilePanel !== "tasks" ? "mobileHidden" : ""}`}>
                  <div className="paneHead"><div><span className="overline">Review queue</span><h3>Action drafts</h3></div>{tasks.length > 0 && <button className="textButton" onClick={() => void saveDrafts()}>Save edits</button>}</div>
                  {!tasks.length ? (
                    <div className="taskEmpty"><span className="emptyGlyph"><Icon name="spark" /></span><h4>Your action queue starts here.</h4><p>Run extraction to turn explicit commitments into editable, source-grounded drafts.</p><button className="primaryButton" onClick={() => void extract()}>Extract from this meeting</button></div>
                  ) : (
                    <div className="taskList">
                      {tasks.map((task, index) => (
                        <article className={`taskDraft ${selected.has(index) ? "selected" : ""}`} key={`${task.source_i}-${index}`}>
                          <div className="taskSelectRow">
                            <label className="taskCheck"><input type="checkbox" checked={selected.has(index)} onChange={() => setSelected((current) => { const next = new Set(current); next.has(index) ? next.delete(index) : next.add(index); return next; })} /><span><Icon name="check" /></span></label>
                            <button className="evidenceLink" onClick={() => { setActiveSource(task.source_i); setMobilePanel("transcript"); }}>Source {task.source_i + 1}</button>
                            <span className="confidenceMark" title="Extraction confidence"><i style={{ width: `${task.confidence * 100}%` }} />{Math.round(task.confidence * 100)}%</span>
                          </div>
                          <textarea rows={2} className="taskTitleInput" aria-label={`Task ${index + 1} title`} value={task.title} onChange={(event) => updateTask(index, { title: event.target.value })} />
                          <textarea className="taskBodyInput" aria-label={`Task ${index + 1} description`} value={task.body} onChange={(event) => updateTask(index, { body: event.target.value })} />
                          <div className="taskFields">
                            <label><span>Owner</span><input placeholder="Unassigned" value={task.assignee_hint || ""} onChange={(event) => updateTask(index, { assignee_hint: event.target.value || null })} /></label>
                            <label><span>Due</span><input placeholder="No date" value={task.due_hint || ""} onChange={(event) => updateTask(index, { due_hint: event.target.value || null })} /></label>
                            <label><span>Labels</span><input value={task.labels.join(", ")} onChange={(event) => updateTask(index, { labels: event.target.value.split(",").map((label) => label.trim()).filter(Boolean) })} /></label>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </section>
              </div>

              {activeChunk && <aside className="evidenceRibbon"><span>Active evidence</span><p>{activeChunk.text}</p><small>Chunk {activeChunk.i + 1} / line {activeChunk.start_line}</small></aside>}
            </>
          ) : (
            <section className="welcomeState"><span className="welcomeMark"><Icon name="spark" /></span><span className="overline">A quieter way to ship follow-through</span><h2>Meetings end.<br />Momentum shouldn't.</h2><p>Import a transcript or load the demo to create an evidence-backed review queue in seconds.</p><button className="primaryButton" onClick={() => void loadDemo()}>Explore the demo workspace</button></section>
          )}
        </main>

        <aside className="approvalTray" aria-label="GitHub approval tray">
          <div className="trayHead"><span className="trayIcon"><Icon name="github" /></span><div><span className="overline">Approval tray</span><h3>GitHub publish</h3></div></div>
          <label className="repoField"><span>Destination repository</span><input value={repo} onChange={(event) => { setRepo(event.target.value); setPreview(null); }} /></label>
          <div className="approvalSummary"><strong>{approvedTasks.length}</strong><span>selected drafts<br />ready for review</span></div>
          <div className="safetyNote"><Icon name="check" /><p><b>Human approval required</b><span>Nothing leaves this workspace until the preview matches your intent.</span></p></div>
          <button className="secondaryButton full" disabled={!approvedTasks.length} onClick={() => void previewIssues()}>Preview exact payloads</button>
          {preview && <div className="previewStack"><div className="previewHead"><span>Payload preview</span><b>{preview.length}</b></div>{preview.map((item, index) => <details key={`${item.title}-${index}`}><summary>{item.title}</summary><pre>{item.body}</pre></details>)}</div>}
          <button className="publishButton" disabled={!preview || demoMode || stage === "publishing"} onClick={() => void publishIssues()}><Icon name="github" /> {demoMode ? "Preview-only demo" : stage === "publishing" ? "Publishing..." : "Approve & create issues"}</button>
          <p className="trayFoot"><Icon name="clock" /> Duplicate fingerprints are skipped automatically.</p>
          <div className="metricGrid"><span><b>{timings.retrieval_ms?.toFixed(0) || "--"}</b><small>retrieval ms</small></span><span><b>{timings.extraction_ms?.toFixed(0) || "--"}</b><small>extract ms</small></span></div>
        </aside>
      </div>
    </div>
  );
}
