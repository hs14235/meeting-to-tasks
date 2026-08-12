import TaskExtractor from "./components/TaskExtractor";
import UploadCard from "./components/UploadCard";

const STACK = [
  "FastAPI backend",
  "React + Vite frontend",
  "Sentence Transformers retrieval",
  "FAISS or memory fallback",
  "Local Ollama extraction",
  "GitHub issue preview + creation",
];

export default function App() {
  return (
    <div className="shell">
      <div className="ambient ambient-a" />
      <div className="ambient ambient-b" />

      <div className="wrap">
        <header className="hero">
          <p className="eyebrow">Portfolio-ready local workflow</p>
          <h1>Turn meeting transcripts into reviewable tasks and optional GitHub issues.</h1>
          <p className="lede">
            Index a plain-text transcript, retrieve the most relevant context, inspect extracted work,
            and only create issues after a preview step.
          </p>

          <div className="heroChips">
            {STACK.map((item) => (
              <span key={item} className="heroChip">
                {item}
              </span>
            ))}
          </div>
        </header>

        <div className="layout">
          <section className="panel panel-wide">
            <div className="panelHead">
              <div>
                <p className="sectionKicker">Step 1</p>
                <h2>Extract work worth tracking</h2>
              </div>
              <p className="sectionNote">
                Ollama handles the broader extraction prompts. The rules fallback stays intentionally
                narrow and only captures explicit action lines.
              </p>
            </div>
            <TaskExtractor />
          </section>

          <aside className="panel">
            <div className="panelHead">
              <div>
                <p className="sectionKicker">Step 0</p>
                <h2>Index a transcript</h2>
              </div>
              <p className="sectionNote">
                Supported today: UTF-8 <code>.txt</code> and <code>.md</code> meeting transcripts.
                PDF and Word support are intentionally out of scope until a real parser is added.
              </p>
            </div>
            <UploadCard />
          </aside>
        </div>
      </div>
    </div>
  );
}
