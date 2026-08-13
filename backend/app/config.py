import os

API_TITLE = "Meeting to Tasks API"
ALLOWED_ORIGINS = [
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
ALLOWED_ORIGIN_REGEX = os.getenv(
    "ALLOWED_ORIGIN_REGEX",
    (
        r"^http://(?:localhost|127\.0\.0\.1|10(?:\.\d{1,3}){3}|"
        r"192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})"
        r":(?:5173|8081)$"
    ),
)

# Vector store choice: "faiss" (if installed) or "memory".
RAG_STORE = os.getenv("RAG_STORE", "memory")

# Sentence Transformers model used for retrieval.
EMBED_MODEL = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

# "hash" is a deterministic, lexical-only provider for tests and demos.
EMBED_PROVIDER = os.getenv("EMBED_PROVIDER", "sentence-transformers")

# FAISS file locations (used only if RAG_STORE=faiss and faiss is installed).
FAISS_INDEX = os.getenv("FAISS_INDEX", "../data/faiss.index")
FAISS_META = os.getenv("FAISS_META", "../data/faiss_meta.json")

PUBLIC_DEMO_MODE = os.getenv("PUBLIC_DEMO_MODE", "false").lower() in {"1", "true", "yes"}
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD", "0.08"))
