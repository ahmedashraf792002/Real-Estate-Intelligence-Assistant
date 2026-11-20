import numpy as np

from . import config

_model = None
_failed = False


def available():
    # load the model once. if it fails we keep going with keyword search only
    global _model, _failed
    if _model is None and not _failed:
        try:
            from fastembed import TextEmbedding
            _model = TextEmbedding(model_name=config.EMBED_MODEL)
        except Exception as e:
            print("embeddings disabled:", repr(e)[:150])
            _failed = True
    return _model is not None


def normalize(v):
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-9)


def embed_chunks(chunks):
    texts = [f"{c['title']}\n{c['text']}"[:1000] for c in chunks]
    vectors = np.array(list(_model.embed(texts, batch_size=32)), dtype="float32")
    return normalize(vectors)


def embed_query(text):
    return normalize(np.array(next(iter(_model.embed([text]))), dtype="float32"))
