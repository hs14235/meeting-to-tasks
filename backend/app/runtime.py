from .config import EMBED_MODEL, EMBED_PROVIDER, FAISS_INDEX, FAISS_META, RAG_STORE
from .embeddings import get_embedding_function
from .services import ExtractionService, IssueService, MeetingService
from .vectorstore.factory import get_store

DIM = 384  # MiniLM-L6-v2 output size

store = get_store(DIM, RAG_STORE, FAISS_INDEX, FAISS_META)
meeting_service = MeetingService(
    store=store,
    embed_model=EMBED_MODEL,
    embedder=get_embedding_function(EMBED_PROVIDER),
)
extraction_service = ExtractionService(meetings=meeting_service)
issue_service = IssueService()
