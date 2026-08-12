import { useEffect, useRef, useState } from "react";

import type { Phase } from "../types/flow";
import { useToast } from "./Toast";

const PRESET_QUERIES = [
  "action items",
  "decisions",
  "follow-ups and blockers",
  "risks",
  "bugs and regressions",
] as const;

type Preset = (typeof PRESET_QUERIES)[number];
type Mode = "ollama" | "rules" | "";

type Task = {
  title?: string;
  body?: string;
  labels?: string[];
  assignee_hint?: string | null;
  due_hint?: string | null;
  source_i?: number;
  confidence?: number;
};

type PreviewItem = {
  repo: string;
  title: string;
  body: string;
  labels: string[];
};

type CreatedItem = {
  number?: number;
  url?: string;
  title: string;
  status: string;
};

type ApiEnvelope = {
  detail?: unknown;
  created?: CreatedItem[];
  would_create?: PreviewItem[];
};

type StreamEvt = {
  stage?: Phase;
  mode?: Exclude<Mode, "">;
  tasks?: Task[];
  message?: string;
  note?: string;
  progress?: number;
};

const API_BASE = (import.meta.env.VITE_API_BASE as string) || "http://127.0.0.1:8000";
const repoRegex = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

const STAGE_LABELS: Record<Phase, string> = {
  idle: "Idle",
  starting: "Starting",
  retrieving: "Retrieving context",
  ollama: "Calling Ollama",
  parsing: "Parsing output",
  rules_fallback: "Rules fallback",
  aborted: "Stopped",
  error: "Error",
  done: "Done",
};

function readList(key: string): string[] {
  try {
    return JSON.parse(localStorage.getItem(key) || "[]") as string[];
  } catch {
    return [];
  }
}

function writeList(key: string, values: string[]) {
  localStorage.setItem(key, JSON.stringify([...new Set(values)].slice(0, 10)));
}

async function readJsonSafely(response: Response): Promise<ApiEnvelope> {
  try {
    return (await response.json()) as ApiEnvelope;
  } catch {
    return {};
  }
}

function toneForStage(stage: Phase) {
  if (stage === "done") {
    return "is-ok";
  }
  if (stage === "error") {
    return "is-danger";
  }
  if (stage === "aborted") {
    return "is-warn";
  }
  return "is-neutral";
}

export default function TaskExtractor() {
  const { error, success } = useToast();

  const [meetingId, setMeetingId] = useState("mtg-001");
  const [repo, setRepo] = useState("owner/repo");
  const [q, setQ] = useState<string>("action items");
  const [k, setK] = useState(5);

  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState<Phase>("idle");
  const [mode, setMode] = useState<Mode>("");
  const [statusNote, setStatusNote] = useState("Index a transcript, then extract the work you want to review.");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [preview, setPreview] = useState<PreviewItem[] | null>(null);
  const [created, setCreated] = useState<CreatedItem[] | null>(null);

  const abortRef = useRef<AbortController | null>(null);

  const [recentMeetings, setRecentMeetings] = useState<string[]>(() => readList("recentMeetings"));
  const [recentRepos, setRecentRepos] = useState<string[]>(() => readList("recentRepos"));

  const repoOk = repoRegex.test(repo.trim()) && repo.trim().toLowerCase() !== "owner/repo";
  const activePreset = PRESET_QUERIES.find((preset) => preset === q) ?? null;
  const isBusy = ["starting", "retrieving", "ollama", "parsing", "rules_fallback"].includes(stage);

  useEffect(() => {
    writeList("recentRepos", recentRepos);
  }, [recentRepos]);

  useEffect(() => {
    const onAdded = (event: Event) => {
      const custom = event as CustomEvent<{ id?: string } | string>;
      const detail = custom.detail;
      const id = typeof detail === "string" ? detail : detail?.id;
      if (!id) {
        return;
      }

      setRecentMeetings((prev) => {
        const next = [id, ...prev];
        writeList("recentMeetings", next);
        return [...new Set(next)].slice(0, 10);
      });
      setMeetingId(id);
    };

    window.addEventListener("mtg-added", onAdded);
    return () => window.removeEventListener("mtg-added", onAdded);
  }, []);

  async function start() {
    if (!meetingId.trim()) {
      error("Meeting ID required", "Choose or upload a meeting ID before extracting.");
      return;
    }

    const controller = new AbortController();
    abortRef.current = controller;

    setProgress(8);
    setStage("starting");
    setMode("");
    setTasks([]);
    setPreview(null);
    setCreated(null);
    setStatusNote("Retrieving the most relevant transcript chunks for this query.");

    try {
      const res = await fetch(`${API_BASE}/tasks/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ meeting_id: meetingId.trim(), q: q.trim(), k }),
        signal: controller.signal,
      });

      if (!res.ok || !res.body) {
        const payload = await readJsonSafely(res);
        const detail = payload.detail ?? payload;
        error("Failed to start extraction", detail);
        setStage("error");
        setStatusNote("The backend rejected the extraction request.");
        return;
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() || "";

        for (const frame of frames) {
          if (!frame.startsWith("data:")) {
            continue;
          }

          let evt: StreamEvt;
          try {
            evt = JSON.parse(frame.replace(/^data:\s*/, "")) as StreamEvt;
          } catch {
            continue;
          }
          if (evt.stage) {
            setStage(evt.stage);
          }
          if (typeof evt.note === "string" && evt.note) {
            setStatusNote(evt.note);
          }
          if (typeof evt.progress === "number") {
            setProgress(evt.progress);
          }

          if (evt.stage === "retrieving") {
            setProgress(18);
          } else if (evt.stage === "parsing") {
            setProgress((prev) => Math.max(prev, 96));
          } else if (evt.stage === "rules_fallback") {
            setProgress(97);
          } else if (evt.stage === "done") {
            setProgress(100);
            setMode(evt.mode || "");
            setTasks(Array.isArray(evt.tasks) ? evt.tasks : []);
            setStatusNote(
              evt.mode === "ollama"
                ? "Reviewed tasks are ready for preview or issue creation."
                : "Rule-based extraction finished. This mode only captures explicit action lines."
            );
          } else if (evt.stage === "error") {
            setStage("error");
            setStatusNote(evt.message || "Extraction failed.");
            error("Extraction failed", evt.message || "Unknown backend error");
          }
        }
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        setStage("aborted");
        setStatusNote("Extraction stopped.");
        return;
      }

      error("Backend request failed", err instanceof Error ? err.message : "Unknown network error");
      setStage("error");
      setStatusNote("Could not reach the backend.");
    } finally {
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  async function doPreview() {
    if (!repoOk) {
      error("Valid repo required", "Enter a real GitHub repo in owner/repo format.");
      return;
    }

    try {
      setPreview(null);
      const res = await fetch(`${API_BASE}/issues/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: repo.trim(), meeting_id: meetingId.trim(), tasks }),
      });

      const data = await readJsonSafely(res);
      if (!res.ok) {
        error("Preview failed", data.detail ?? data);
        return;
      }

      setPreview(Array.isArray(data.would_create) ? data.would_create : []);
    } catch (err) {
      error("Preview failed", err instanceof Error ? err.message : "Unknown network error");
    }
  }

  async function doCreate() {
    if (!repoOk) {
      error("Valid repo required", "Enter a real GitHub repo in owner/repo format.");
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/issues`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: repo.trim(), meeting_id: meetingId.trim(), tasks }),
      });

      const data = await readJsonSafely(res);
      if (!res.ok) {
        error("Failed to create issues", data.detail ?? data);
        return;
      }

      const createdItems = Array.isArray(data.created) ? data.created : [];
      setCreated(createdItems);

      const createdCount = createdItems.filter((item) => item.status === "created").length;
      const duplicateCount = createdItems.filter((item) => item.status === "skipped-duplicate").length;
      const skippedCount = createdItems.length - createdCount;
      success(
        `Created ${createdCount}, skipped ${skippedCount}${duplicateCount ? ` (${duplicateCount} duplicates)` : ""}`
      );
    } catch (err) {
      error("Failed to create issues", err instanceof Error ? err.message : "Unknown network error");
    }
  }

  return (
    <div className="stack">
      <datalist id="recent-meetings">
        {recentMeetings.map((item) => (
          <option key={item} value={item} />
        ))}
      </datalist>
      <datalist id="recent-repos">
        {recentRepos.map((item) => (
          <option key={item} value={item} />
        ))}
      </datalist>

      <div className="toolGrid">
        <label className="field" htmlFor="meeting-id">
          <span className="fieldLabel">Meeting ID</span>
          <input
            id="meeting-id"
            list="recent-meetings"
            className="txt"
            value={meetingId}
            onChange={(event) => setMeetingId(event.target.value)}
            placeholder="meeting id"
          />
        </label>

        <label className="field" htmlFor="repo-name">
          <span className="fieldLabel">GitHub repo</span>
          <div className="inputWithBadge">
            <input
              id="repo-name"
              list="recent-repos"
              className="txt"
              value={repo}
              onChange={(event) => {
                const value = event.target.value;
                setRepo(value);
                if (repoRegex.test(value)) {
                  setRecentRepos((prev) => [value, ...prev].slice(0, 10));
                }
              }}
              placeholder="owner/repo"
              title="owner/repo"
            />
            <span className={`statusPill ${repoOk ? "is-ok" : "is-warn"}`}>
              {repoOk ? "Ready" : "owner/repo"}
            </span>
          </div>
        </label>

        <div className="field">
          <span className="fieldLabel">Context size</span>
          <div className="rangeRow">
            <input type="range" min={1} max={10} value={k} onChange={(event) => setK(Number(event.target.value))} />
            <span className="rangeValue">K {k}</span>
          </div>
          <p className="helperText">
            Higher K broadens recall but adds more local inference cost and more transcript noise.
          </p>
        </div>
      </div>

      <div className="field">
        <span className="fieldLabel">Extraction focus</span>
        <div className="chipRow">
          {PRESET_QUERIES.map((preset) => (
            <button
              key={preset}
              type="button"
              className={`chip ${activePreset === preset ? "active" : ""}`}
              onClick={() => setQ(preset)}
            >
              {preset}
            </button>
          ))}
        </div>

        <input
          className="txt txtQuery"
          value={q}
          onChange={(event) => setQ(event.target.value)}
          placeholder="custom extraction query"
        />
        <p className="helperText">
          Use a preset for the common paths, or type a custom query for a one-off extraction pass.
        </p>
      </div>

      <div className="actionRow">
        <div className="buttonRow">
          <button className="btn btn-primary" onClick={start} disabled={isBusy}>
            {isBusy ? "Extracting..." : "Extract tasks"}
          </button>
          {isBusy && (
            <button className="btn btn-secondary" onClick={stop}>
              Stop
            </button>
          )}
        </div>

        <div className="statusGroup">
          <span className={`statusBadge ${toneForStage(stage)}`}>{STAGE_LABELS[stage]}</span>
          {mode && <span className="statusBadge is-muted">{mode === "ollama" ? "Ollama" : "Rules"}</span>}
        </div>
      </div>

      <div className="bar">
        <div className="barFill" style={{ width: `${progress}%` }} />
      </div>
      <div className="statusNote">{statusNote}</div>

      <div className="sectionHeaderRow">
        <div>
          <h3>Extracted tasks</h3>
          <p className="helperText">Review the generated work before previewing or creating issues.</p>
        </div>
        {tasks.length > 0 && <span className="countBadge">{tasks.length} items</span>}
      </div>

      <div className="tasks">
        {tasks.length === 0 && <div className="emptyState">No tasks yet.</div>}

        {tasks.map((task, index) => (
          <article key={`${task.title || "task"}-${index}`} className="task">
            <div className="taskHead">
              <div>
                <div className="tTitle">{task.title || "(no title)"}</div>
                <div className="metaRow">
                  {(task.labels || []).map((label) => (
                    <span key={label} className="metaChip">
                      {label}
                    </span>
                  ))}
                </div>
              </div>
              <div className="confidence">{Math.round((task.confidence ?? 0) * 100)}%</div>
            </div>

            {task.body && <pre className="tBody">{task.body}</pre>}

            <div className="metaRow">
              <span className="metaChip">source #{task.source_i ?? "-"}</span>
              {task.assignee_hint && <span className="metaChip">owner {task.assignee_hint}</span>}
              {task.due_hint && <span className="metaChip">due {task.due_hint}</span>}
            </div>
          </article>
        ))}
      </div>

      <div className="actionRow">
        <div className="buttonRow">
          <button className="btn btn-secondary" onClick={doPreview} disabled={!tasks.length}>
            Preview issues
          </button>
          <button className="btn btn-primary" onClick={doCreate} disabled={!tasks.length}>
            Create issues
          </button>
        </div>
      </div>

      {preview && (
        <section className="previewSection">
          <div className="sectionHeaderRow">
            <h3>Issue preview</h3>
            <span className="countBadge">{preview.length} issues</span>
          </div>

          {preview.map((item, index) => (
            <article key={`${item.title}-${index}`} className="task">
              <div className="tTitle">{item.title}</div>
              <pre className="tBody">{item.body}</pre>
              <div className="metaRow">
                {item.labels.map((label) => (
                  <span key={label} className="metaChip">
                    {label}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </section>
      )}

      {created && (
        <section className="previewSection">
          <div className="sectionHeaderRow">
            <h3>Issue results</h3>
            <span className="countBadge">{created.length} responses</span>
          </div>

          {created.map((item, index) => (
            <article key={`${item.title}-${index}`} className="task">
              <div className="taskHead">
                <div className="tTitle">{item.title}</div>
                <span className="metaChip">{item.status}</span>
              </div>
              {item.url && (
                <a href={item.url} target="_blank" rel="noreferrer">
                  {item.url}
                </a>
              )}
            </article>
          ))}
        </section>
      )}
    </div>
  );
}
