export type Phase =
  | "idle"
  | "starting"
  | "retrieving"
  | "ollama"
  | "parsing"
  | "rules_fallback"
  | "aborted"
  | "error"
  | "done";
