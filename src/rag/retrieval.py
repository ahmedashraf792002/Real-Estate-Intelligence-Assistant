import math
from collections import Counter, defaultdict

import numpy as np

from . import config
from .text import tokens


# keyword search (BM25)
class BM25:
    def __init__(self, docs_tokens, k1=1.4, b=0.75):
        self.k1, self.b = k1, b
        self.tf = [Counter(t) for t in docs_tokens]
        self.len = np.array([len(t) for t in docs_tokens], dtype="float32")
        self.avg = float(self.len.mean()) if len(docs_tokens) else 1.0
        self.post = defaultdict(list)
        for i, c in enumerate(self.tf):
            for w in c:
                self.post[w].append(i)
        n = len(docs_tokens)
        self.idf = {w: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for w, p in self.post.items()}

    def scores(self, q_tokens):
        s = np.zeros(len(self.tf), dtype="float32")
        for w in set(q_tokens):
            idf = self.idf.get(w)
            if idf is None:
                continue
            for i in self.post[w]:
                f = self.tf[i][w]
                s[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
        return s


# keywords + vectors together
class Retriever:
    def __init__(self, chunks, index=None, embed=None):
        self.chunks = chunks
        self.index = index  # where the vectors are (database or local)
        self.embed = embed  # function: text -> vector
        self._dense = None
        self.ids = [c["id"] for c in chunks]
        self.by_id = {c["id"]: c for c in chunks}
        self.bm25 = BM25([tokens(c["title"] + " " + c["text"]) for c in chunks])

    @property
    def dense(self):
        # asked once (the answer is cached), and a database error means "no vectors", not a crash
        if self._dense is None:
            try:
                self._dense = bool(self.index and self.embed and self.index.has_vectors())
            except Exception as e:
                print("could not check vectors:", str(e)[:150])
                return False
        return self._dense

    def rankings(self, query, pool):
        ranks = []
        # keyword ranking
        scores = self.bm25.scores(tokens(query))
        if len(scores) and scores.max() > 0:
            ranks.append([self.ids[i] for i in np.argsort(-scores)[:pool]])
        # vector ranking (if it fails we still have the keyword one)
        if self.dense:
            try:
                hits = self.index.search(self.embed(query), pool)
                ranks.append([cid for cid, _ in hits if cid in self.by_id])
            except Exception as e:
                print("vector search failed, using keywords only:", str(e)[:150])
        return ranks

    def search(self, query, k=None, pool=40):
        k = k or config.TOP_K
        # reciprocal rank fusion: merge the two rankings
        fused = defaultdict(float)
        for ranking in self.rankings(query, pool):
            for pos, cid in enumerate(ranking):
                fused[cid] += 1.0 / (60 + pos)
        # at most 2 chunks per page so the sources stay different
        found, per_page = [], Counter()
        for cid in sorted(fused, key=fused.get, reverse=True):
            chunk = self.by_id[cid]
            if per_page[chunk["url"]] >= 2:
                continue
            per_page[chunk["url"]] += 1
            found.append(chunk)
            if len(found) >= k:
                break
        return found
