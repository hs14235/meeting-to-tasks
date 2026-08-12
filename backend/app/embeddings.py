import hashlib
import re
from typing import Any

import numpy as np

_model: Any = None


def get_embedder(name: str):
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed. Run `pip install -r backend/requirements.txt`."
            ) from exc
        _model = SentenceTransformer(name)
    return _model


def embed_texts(texts, name: str):
    model = get_embedder(name)
    # normalize=True means inner product is comparable to cosine similarity.
    return model.encode(texts, normalize_embeddings=True).tolist()


def embed_texts_hash(texts, name: str):
    """Create deterministic lexical vectors for offline tests and demos."""
    del name
    vectors = []
    for text in texts:
        vector = np.zeros(384, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % vector.size
            direction = 1.0 if digest[4] & 1 else -1.0
            vector[index] += direction

        norm = np.linalg.norm(vector)
        if norm:
            vector /= norm
        vectors.append(vector.tolist())
    return vectors


def get_embedding_function(provider: str):
    if provider == "sentence-transformers":
        return embed_texts
    if provider == "hash":
        return embed_texts_hash
    raise RuntimeError(
        f'Unsupported EMBED_PROVIDER "{provider}". Use "sentence-transformers" or "hash".'
    )
