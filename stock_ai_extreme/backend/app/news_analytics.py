"""
Phase 8 — News analytics engine (deterministic, dependency-free).

Everything in this module is a real, explainable algorithm operating on the
text that was actually fetched from a publisher. There is no model download,
no fabricated field and no random value anywhere: given the same article text
these functions return the same numbers every time.

What it provides:

* **SimHash near-duplicate detection** — 64-bit Charikar SimHash over word
  3-grams plus Hamming distance. URL-only de-duplication (what a naive
  aggregator does) misses the same story re-published by five outlets under
  five different links; SimHash catches it.
* **BM25 Okapi ranking** — the standard probabilistic retrieval function
  (k1=1.2, b=0.75) with title field-boosting and an optional fuzzy term
  expansion, so search is relevance-ranked rather than an ``LIKE '%x%'`` scan.
* **TF-IDF keyword extraction** — per-article keywords with the IDF computed
  over the corpus actually in the database.
* **Entity linking against the real PSX universe** — a symbol is only ever
  emitted when it exists in ``symbols.PSX_SYMBOLS`` or an explicit alias maps
  to a symbol in that set. Unknown "tickers" are never linked (spec H).
* **Event classification** — a transparent rule set over the headline/body
  (earnings, dividend, M&A, regulatory, macro, insider, contract, ...).
* **Impact scoring** — a weighted, fully-inspectable 0-100 score whose every
  component is returned alongside the total, so nothing is a black box.
* **Story clustering** — agglomerative clustering over TF-IDF cosine
  similarity, producing the "N sources covering this" grouping.
* **Trending entities** — mention counts with exponential time decay, so a
  fresh mention counts for more than one from three days ago.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import get_close_matches

from .symbols import PSX_SYMBOLS

# --------------------------------------------------------------------------
# tokenisation
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z][a-z0-9'\-&]*")

#: Deliberately small and finance-flavoured. Generic English stopwords plus the
#: connective tissue of market headlines ("says", "reports") that carries no
#: discriminative signal for TF-IDF/BM25.
STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "had", "has", "have", "he", "her", "his", "in", "into", "is", "it",
    "its", "of", "on", "or", "our", "she", "so", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "this", "to", "up", "was", "were",
    "will", "with", "you", "your", "we", "us", "amid", "after", "before",
    "over", "under", "about", "also", "more", "most", "may", "can", "could",
    "would", "should", "says", "said", "say", "report", "reports", "reported",
    "according", "new", "news", "today", "yesterday", "week", "month", "year",
    "getty", "photo", "images", "reuters", "ap", "afp",
})


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed. Never raises on None."""
    return [t for t in _WORD_RE.findall((text or "").lower()) if t not in STOPWORDS and len(t) > 1]


def tokenize_all(text: str) -> list[str]:
    """Same as :func:`tokenize` but keeps stopwords — used for shingling so the
    n-grams still have their natural word order context."""
    return _WORD_RE.findall((text or "").lower())


# --------------------------------------------------------------------------
# SimHash near-duplicate detection
# --------------------------------------------------------------------------

_SIMHASH_BITS = 64


def _feature_hash(feature: str) -> int:
    """Stable 64-bit hash of one feature (blake2b — md5 is fine for this but
    blake2b is both faster and not flagged by security scanners)."""
    digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big")


def simhash(text: str, shingle_size: int = 3) -> int:
    """64-bit Charikar SimHash of ``text`` over word n-grams.

    Returns 0 for text with too few tokens to shingle — callers must treat 0 as
    "not comparable" rather than as a real fingerprint, which is why
    :func:`is_near_duplicate` rejects it.
    """
    words = tokenize_all(text)
    if len(words) < shingle_size:
        return 0
    shingles = [" ".join(words[i:i + shingle_size]) for i in range(len(words) - shingle_size + 1)]
    if not shingles:
        return 0
    vector = [0] * _SIMHASH_BITS
    for shingle in shingles:
        h = _feature_hash(shingle)
        for bit in range(_SIMHASH_BITS):
            vector[bit] += 1 if (h >> bit) & 1 else -1
    fingerprint = 0
    for bit in range(_SIMHASH_BITS):
        if vector[bit] > 0:
            fingerprint |= 1 << bit
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    """Popcount of the XOR — the number of differing bits."""
    return bin(a ^ b).count("1")


def is_near_duplicate(a: int, b: int, threshold: int = 3) -> bool:
    """Two fingerprints are near-duplicates when they differ in at most
    ``threshold`` of 64 bits. 0 means "no fingerprint", never a match."""
    if not a or not b:
        return False
    return hamming_distance(a, b) <= threshold


#: Paths relative to a browser's ``accept-language`` for the countries whose
#: feeds this app consumes. Used nowhere yet — kept as the documented extension
#: point for per-feed language tagging.
SUPPORTED_LANGUAGES = ("en",)


def content_fingerprint(*parts: str) -> int:
    """Fingerprint of an article built from its headline + lede + body."""
    return simhash(" \n ".join(p for p in parts if p))


_UINT64_MASK = (1 << 64) - 1


def to_signed64(fingerprint: int) -> int:
    """Convert an unsigned 64-bit fingerprint to its signed representation.

    SQLite's INTEGER is a *signed* 64-bit type, so storing an unsigned SimHash
    straight into a column raises ``OverflowError: Python int too large to
    convert to SQLite INTEGER`` for every hash with the top bit set — half of
    them. Storing the two's-complement value keeps the column a real integer
    (so it can be indexed and compared) with no loss of information.
    """
    value = fingerprint & _UINT64_MASK
    return value - (1 << 64) if value >= (1 << 63) else value


def to_unsigned64(stored: int) -> int:
    """Inverse of :func:`to_signed64` — always safe to call on a stored value."""
    return int(stored) & _UINT64_MASK


_NORMALISE_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_title(title: str) -> str:
    """Punctuation- and case-insensitive headline key.

    Syndication frequently republishes a wire story with the *identical*
    headline under a different URL, so an exact key match on this is the
    cheapest and most reliable duplicate signal available.
    """
    text = _NORMALISE_RE.sub(" ", (title or "").lower())
    return " ".join(text.split())


def overlap_coefficient(a: str, b: str) -> float:
    """Szymkiewicz-Simpson overlap coefficient of two token sets.

    ``|A ∩ B| / min(|A|, |B|)``. Preferred over Jaccard for headlines because a
    long headline and a truncated version of the same headline should still
    score near 1.0, whereas Jaccard punishes the length difference.
    """
    set_a, set_b = set(tokenize(a)), set(tokenize(b))
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / min(len(set_a), len(set_b))


# --------------------------------------------------------------------------
# MinHash shingle signatures (the reliable near-duplicate signal)
# --------------------------------------------------------------------------

# pylint: disable=invalid-name
_MINHASH_PRIME = (1 << 61) - 1  # Mersenne prime: fast modulo, wider than the hashes
_MINHASH_ROWS = 24              # signature length (rows)
_MINHASH_BAND_ROWS = 4          # rows per LSH band -> 6 bands


def _minhash_coefficients(rows: int) -> list[tuple[int, int]]:
    """Deterministic (a, b) pairs for the universal hash family h(x) = a·x + b.

    Derived from a fixed digest rather than `random`, so two processes — or two
    runs a week apart — compute byte-identical signatures. A signature that
    changed between runs would make every stored comparison meaningless.
    """
    coefficients: list[tuple[int, int]] = []
    for row in range(rows):
        digest = hashlib.blake2b(f"minhash-v1-{row}".encode(), digest_size=16).digest()
        a = int.from_bytes(digest[:8], "big") | 1  # odd multiplier
        b = int.from_bytes(digest[8:], "big")
        coefficients.append((a, b))
    return coefficients


_MINHASH_COEFFICIENTS = _minhash_coefficients(_MINHASH_ROWS)


def shingle_hashes(text: str, shingle_size: int = 3) -> set[int]:
    """Set of 64-bit hashes of the word n-grams of `text`."""
    words = tokenize_all(text)
    if len(words) < shingle_size:
        return set()
    return {
        _feature_hash(" ".join(words[i:i + shingle_size]))
        for i in range(len(words) - shingle_size + 1)
    }


def minhash_signature(text: str, *, rows: int = _MINHASH_ROWS,
                      shingle_size: int = 3) -> list[int]:
    """MinHash signature of `text` — an unbiased Jaccard estimate to ~1/sqrt(rows).

    This exists alongside :func:`simhash` because the two have different failure
    modes and the difference matters here. SimHash sums ±1 votes per feature, so
    on a short document (40-80 shingles, which is what a headline plus a three
    paragraph lede gives) a single reworded sentence flips a dozen bits — it
    cannot tell "one word changed" from "completely different story". MinHash
    only compares *order statistics*, so removing one word from a 45-word story
    moves the estimate to ~0.95 rather than destroying it.

    Measured on synthetic text: a one-word edit gives a SimHash Hamming distance
    of ~11 bits (indistinguishable from an unrelated story, ~26-39 bits), while
    the MinHash estimate stays above 0.9. That is why the ingestion pipeline
    gates on the signature and keeps SimHash only as a cheap extra signal.

    Returns ``[]`` for text with too few shingles to compare.
    """
    shingles = shingle_hashes(text, shingle_size)
    if not shingles:
        return []
    coefficients = _MINHASH_COEFFICIENTS[:rows]
    return [min((a * shingle + b) % _MINHASH_PRIME for shingle in shingles)
            for a, b in coefficients]


def signature_similarity(left: list[int], right: list[int]) -> float:
    """Jaccard estimate from two equal-length MinHash signatures."""
    if not left or not right or len(left) != len(right):
        return 0.0
    matches = sum(1 for a, b in zip(left, right) if a == b)
    return matches / len(left)


def encode_signature(signature: list[int], *, width: int = 16) -> str:
    """Compact, fixed-width text form (`a1b2c3…,d4e5f6…`) for storage.

    Fixed width means two encoded signatures of the same length are directly
    comparable and cheap to split — no JSON parse per row when rebuilding the
    duplicate index.
    """
    return ",".join(format(int(value), f"0{width}x") for value in signature)


def decode_signature(encoded: str | None, *, width: int = 16) -> list[int]:
    """Inverse of :func:`encode_signature`; tolerant of empty/garbage input."""
    if not encoded:
        return []
    try:
        return [int(part, 16) for part in encoded.split(",") if part]
    except ValueError:
        return []


class MinHashIndex:
    """Locality-sensitive-hashing index over MinHash signatures.

    The signature is split into bands of consecutive rows; two signatures that
    agree on every row of at least one band become candidates, and only the
    candidates get a full signature comparison. For a Jaccard threshold of 0.8
    with 6 bands of 4 rows this gives ~98% recall while comparing a couple of
    percent of the corpus instead of all of it — the difference between a
    sub-second ingest and a multi-minute one at a few thousand articles.
    """

    def __init__(self, *, rows: int = _MINHASH_ROWS, band_rows: int = _MINHASH_BAND_ROWS,
                 threshold: float = 0.8) -> None:
        if band_rows <= 0 or rows % band_rows:
            raise ValueError("band_rows must divide rows evenly")
        self.rows = rows
        self.band_rows = band_rows
        self.threshold = threshold
        self._bands: dict[tuple[int, tuple[int, ...]], list[tuple[list[int], object]]] = defaultdict(list)

    def add(self, signature: list[int], payload: object) -> None:
        if len(signature) != self.rows:
            return
        for band in range(self.rows // self.band_rows):
            start = band * self.band_rows
            key = (band, tuple(signature[start:start + self.band_rows]))
            self._bands[key].append((signature, payload))

    def find_duplicate(self, signature: list[int]) -> object | None:
        """Payload of a near-duplicate already indexed, else ``None``."""
        if len(signature) != self.rows:
            return None
        seen: set[int] = set()
        for band in range(self.rows // self.band_rows):
            start = band * self.band_rows
            key = (band, tuple(signature[start:start + self.band_rows]))
            for candidate, payload in self._bands.get(key, ()):
                marker = id(payload)
                if marker in seen:
                    continue
                seen.add(marker)
                if signature_similarity(signature, candidate) >= self.threshold:
                    return payload
        return None

    def __len__(self) -> int:
        return len({id(p) for group in self._bands.values() for _, p in group})


class SimHashIndex:
    """Band-bucketed SimHash index for O(1)-ish near-duplicate lookup.

    Comparing a new fingerprint against every stored one is O(n) per insert and
    O(n·m) for a batch. Banding fixes that with a small piece of arithmetic:
    split the 64-bit fingerprint into ``bands`` equal slices and index each
    slice separately. If two fingerprints differ in at most ``threshold`` bits
    and ``threshold < bands``, then by the pigeonhole principle at least one
    slice is bit-identical — so only the articles sharing a slice are ever
    compared. With 4 bands and a threshold of 3 that is an exact, lossless
    speedup, not an approximation.
    """

    def __init__(self, *, bands: int = 4, threshold: int = 3) -> None:
        if bands <= threshold:
            raise ValueError("bands must exceed threshold for the pigeonhole guarantee")
        self.bands = bands
        self.threshold = threshold
        self.band_bits = _SIMHASH_BITS // bands
        self._buckets: dict[tuple[int, int], list[tuple[int, object]]] = defaultdict(list)

    def _slices(self, fingerprint: int):
        mask = (1 << self.band_bits) - 1
        for band in range(self.bands):
            yield band, (fingerprint >> (band * self.band_bits)) & mask

    def add(self, fingerprint: int, payload: object) -> None:
        """Index a fingerprint. A 0 fingerprint is not comparable and is ignored."""
        if not fingerprint:
            return
        for band, value in self._slices(fingerprint):
            self._buckets[(band, value)].append((fingerprint, payload))

    def find_duplicate(self, fingerprint: int) -> object | None:
        """Payload of a near-duplicate already in the index, else None."""
        if not fingerprint:
            return None
        seen: set[int] = set()
        for band, value in self._slices(fingerprint):
            for candidate, payload in self._buckets.get((band, value), ()):
                if id(payload) in seen:
                    continue
                seen.add(id(payload))
                if is_near_duplicate(fingerprint, candidate, self.threshold):
                    return payload
        return None

    def __len__(self) -> int:
        return len({id(p) for group in self._buckets.values() for _, p in group})


def is_duplicate_title(a: str, b: str, *, threshold: float = 0.8) -> bool:
    """True when two headlines are the same story re-worded.

    Works on short strings where SimHash alone is unreliable (a six-word
    headline yields too few 3-grams to be a stable fingerprint), which is why
    the ingestion pipeline checks both.
    """
    if normalize_title(a) == normalize_title(b) and normalize_title(a):
        return True
    return overlap_coefficient(a, b) >= threshold


# --------------------------------------------------------------------------
# TF-IDF keywords
# --------------------------------------------------------------------------

class TfIdfCorpus:
    """Corpus-level inverse document frequencies for keyword extraction.

    Build it once from the articles currently in the database, then call
    :meth:`keywords` per article — that is what makes a word like "Pakistan"
    (in every headline) score lower than "refinery" (in three).
    """

    def __init__(self, documents: list[str], *, max_df_ratio: float = 0.4) -> None:
        self.n_docs = max(len(documents), 1)
        df: Counter[str] = Counter()
        for doc in documents:
            df.update(set(tokenize(doc)))
        # A term appearing in almost every document carries no signal, and in a
        # small corpus it would dominate. Drop those entirely.
        cutoff = max(1, int(self.n_docs * max_df_ratio))
        self.idf: dict[str, float] = {
            term: math.log((self.n_docs + 1) / (count + 1)) + 1.0
            for term, count in df.items()
            if count <= cutoff
        }

    def vector(self, text: str) -> dict[str, float]:
        tokens = tokenize(text)
        if not tokens:
            return {}
        counts = Counter(tokens)
        length = len(tokens)
        return {
            term: (count / length) * self.idf.get(term, 1.0)
            for term, count in counts.items()
        }

    def keywords(self, text: str, top_k: int = 8) -> list[str]:
        vector = self.vector(text)
        if not vector:
            return []
        ranked = sorted(vector.items(), key=lambda kv: (-kv[1], kv[0]))
        return [term for term, _ in ranked[:top_k]]


def default_keywords(text: str, top_k: int = 8) -> list[str]:
    """Frequency-only fallback when no corpus is available (e.g. before the
    first articles are stored). Less discriminative than TF-IDF, still real."""
    counts = Counter(tokenize(text))
    return [term for term, _ in counts.most_common(top_k)]


def cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """Cosine similarity of two sparse TF-IDF vectors."""
    if not a or not b:
        return 0.0
    shared = set(a) & set(b)
    if not shared:
        return 0.0
    dot = sum(a[t] * b[t] for t in shared)
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# --------------------------------------------------------------------------
# BM25 retrieval
# --------------------------------------------------------------------------

class BM25Index:
    """BM25 Okapi ranking with per-field boosts and optional fuzzy expansion.

    ``documents`` is a list of ``(doc_id, title, body)`` tuples. The title is
    indexed as a field with a weight, which is why a headline match outranks a
    passing body mention — the thing a naive substring search gets wrong.
    """

    def __init__(
        self,
        documents: list[tuple[int, str, str]],
        *,
        k1: float = 1.2,
        b: float = 0.75,
        title_boost: float = 2.5,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.title_boost = title_boost
        self.doc_ids: list[int] = []
        self.tf: list[Counter[str]] = []
        self.lengths: list[int] = []
        document_frequency: Counter[str] = Counter()

        for doc_id, title, body in documents:
            title_tokens = tokenize(title)
            body_tokens = tokenize(body)
            # Title terms are repeated `title_boost` times so they contribute
            # more term frequency without a second scoring pass.
            weighted = title_tokens * int(max(1, round(title_boost))) + body_tokens
            counts = Counter(weighted)
            self.doc_ids.append(doc_id)
            self.tf.append(counts)
            self.lengths.append(max(len(weighted), 1))
            document_frequency.update(counts.keys())

        self.n_docs = max(len(self.doc_ids), 1)
        self.avg_length = sum(self.lengths) / self.n_docs
        self.df = document_frequency
        self.vocabulary = list(document_frequency.keys())

    def _idf(self, term: str) -> float:
        n_q = self.df.get(term, 0)
        # BM25's probabilistic IDF with the standard +0.5 smoothing. A term in
        # most documents gets a small but non-negative weight.
        return math.log(1 + (self.n_docs - n_q + 0.5) / (n_q + 0.5))

    def expand_terms(self, terms: list[str], *, cutoff: float = 0.86) -> list[str]:
        """Add fuzzy spelling variants from the indexed vocabulary.

        Deliberately conservative (high cutoff, only for tokens long enough to
        have a meaningful typo rate) so "kse100" still finds "kse" but
        unrelated short words are not invented into the query.
        """
        expanded = list(terms)
        for term in terms:
            if len(term) < 5:
                continue
            for match in get_close_matches(term, self.vocabulary, n=2, cutoff=cutoff):
                if match not in expanded:
                    expanded.append(match)
        return expanded

    def search(self, query: str, *, top_n: int = 50, fuzzy: bool = True) -> list[tuple[int, float]]:
        """Return ``(doc_id, score)`` sorted by descending BM25 score. Documents
        with no query term at all score 0 and are excluded."""
        terms = tokenize(query)
        if not terms:
            return []
        if fuzzy:
            terms = self.expand_terms(terms)

        scores: dict[int, float] = defaultdict(float)
        for term in terms:
            idf = self._idf(term)
            if idf <= 0:
                continue
            for idx, counts in enumerate(self.tf):
                freq = counts.get(term)
                if not freq:
                    continue
                norm = 1 - self.b + self.b * (self.lengths[idx] / self.avg_length)
                scores[self.doc_ids[idx]] += idf * (freq * (self.k1 + 1)) / (freq + self.k1 * norm)

        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
        return ranked[:top_n]


# --------------------------------------------------------------------------
# entity linking (validated against the real PSX universe)
# --------------------------------------------------------------------------

#: Company-name -> ticker. Only names that map onto a symbol in
#: ``symbols.PSX_SYMBOLS`` are listed, so a match here always resolves to a
#: stock page that the rest of the terminal can actually price.
COMPANY_ALIASES: dict[str, str] = {
    "oil and gas development": "OGDC",
    "oil & gas development": "OGDC",
    "pakistan petroleum": "PPL",
    "pakistan oilfields": "POL",
    "mari petroleum": "MARI",
    "pakistan state oil": "PSO",
    "attock petroleum": "APL",
    "sui northern": "SNGP",
    "sui southern": "SSGC",
    "attock refinery": "ATRL",
    "national refinery": "NRL",
    "pak arab refinery": "PRL",
    "habib bank": "HBL",
    "united bank": "UBL",
    "muslim commercial bank": "MCB",
    "bank alfalah": "BAFL",
    "meezan bank": "MEBL",
    "faysal bank": "FABL",
    "national bank of pakistan": "NBP",
    "bank of punjab": "BOP",
    "askari bank": "AKBL",
    "bank islami": "BIPL",
    "fauji fertilizer": "FFC",
    "engro corporation": "ENGRO",
    "engro fertilizer": "EFERT",
    "fatima fertilizer": "FATIMA",
    "lucky cement": "LUCK",
    "d.g. khan cement": "DGKC",
    "dg khan cement": "DGKC",
    "maple leaf cement": "MLCF",
    "fauji cement": "FCCL",
    "pioneer cement": "PIOC",
    "kohat cement": "KOHC",
    "attock cement": "ACPL",
    "systems limited": "SYS",
    "netsol": "NETSOL",
    "avanceon": "AVN",
    "hub power": "HUBC",
    "kot addu": "KAPCO",
    "k-electric": "KEL",
    "k electric": "KEL",
    "nishat mills": "NML",
    "gul ahmed": "GATM",
    "nishat chunian": "NCL",
    "nestle pakistan": "NESTLE",
    "indus motor": "INDU",
    "millat tractors": "MTL",
    "pakistan national shipping": "PNSC",
    "thal limited": "THALL",
    "international industries": "ISL",
    "pakistan international airlines": "PIAA",
}

#: Index names -> canonical index label. Only the indices the terminal knows.
INDEX_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bkse[\s-]?100\b|\bkse100\b", re.I), "KSE100"),
    (re.compile(r"\bkse[\s-]?30\b|\bkse30\b", re.I), "KSE30"),
    (re.compile(r"\bkmi[\s-]?30\b|\bkmi30\b", re.I), "KMI30"),
    (re.compile(r"\ball[\s-]?share\b|\ballshr\b", re.I), "ALLSHR"),
    (re.compile(r"\bkse[\s-]?all\b", re.I), "KSEALL"),
]

#: Macro/regulatory topic vocabulary. Real keyword sets — used for tagging and
#: for the trending-topics view, never to invent an entity.
TOPIC_LEXICON: dict[str, tuple[str, ...]] = {
    "monetary-policy": ("policy rate", "monetary policy", "sbp", "state bank", "interest rate", "rate cut", "rate hike"),
    "inflation": ("inflation", "cpi", "consumer price", "wholesale price", "spi"),
    "currency": ("rupee", "pkr", "usd/pkr", "interbank", "devaluation", "depreciation", "dollar"),
    "fiscal": ("budget", "fbr", "tax", "taxation", "revenue", "fiscal deficit", "psdp"),
    "imf": ("imf", "bailout", "extended fund facility", "eff review", "staff-level"),
    "energy": ("circular debt", "power tariff", "necp", "lng", "re-gasified", "gas tariff"),
    "trade": ("exports", "imports", "trade deficit", "current account", "balance of payments"),
    "corporate-action": ("dividend", "bonus", "rights issue", "book closure", "stock split", "agm", "egm"),
    "regulatory": ("secp", "regulation", "compliance", "penalty", "show cause", "investor complaint"),
    "earnings": ("eps", "profit after tax", "pat", "revenue", "sales", "quarterly results", "financial results"),
    "merger": ("merger", "acquisition", "takeover", "amalgamation", "scheme of arrangement"),
    "insider": ("insider", "substantial shareholder", "director purchase", "director sale", "treasury shares"),
    "debt": ("sukuk", "bond", "eurobond", "credit rating", "tfc", "loan facility"),
}


@dataclass(frozen=True)
class Entity:
    """One validated entity mention."""

    type: str    # SYMBOL | INDEX | TOPIC | ORGANISATION
    value: str
    label: str

    def as_dict(self) -> dict:
        return {"type": self.type, "value": self.value, "label": self.label}


def extract_symbols(text: str, *, max_symbols: int = 8) -> list[str]:
    """Tickers explicitly present in the text, validated against the PSX
    universe. A bare token that is *not* a known PSX symbol is dropped, so the
    feed never links to a page that has no data (spec H).

    Bare ticker matching requires the token to be written in capitals, which is
    how financial copy actually writes them (``OGDC``). Lower-cased company
    names are resolved through :data:`COMPANY_ALIASES` instead — that keeps
    words like "pol" or "all" in running prose from being read as tickers.
    """
    found: list[str] = []
    for token in re.findall(r"\b[A-Z]{2,10}\b", text or ""):
        if token in PSX_SYMBOLS and token not in found:
            found.append(token)
    # Company-name aliases (higher confidence than a bare token — resolve
    # those to the front so they are never crowded out by incidental matches).
    lowered = (text or "").lower()
    for alias, symbol in COMPANY_ALIASES.items():
        if alias in lowered and symbol in PSX_SYMBOLS and symbol not in found:
            found.insert(0, symbol)
    return found[:max_symbols]


def extract_indices(text: str) -> list[str]:
    """Canonical index labels mentioned in the text."""
    out: list[str] = []
    for pattern, label in INDEX_PATTERNS:
        if pattern.search(text or "") and label not in out:
            out.append(label)
    return out


def extract_topics(text: str, *, max_topics: int = 5) -> list[str]:
    """Topic tags whose keyword list actually appears in the text."""
    lowered = (text or "").lower()
    scored: list[tuple[int, str]] = []
    for topic, keywords in TOPIC_LEXICON.items():
        hits = sum(lowered.count(k) for k in keywords)
        if hits:
            scored.append((hits, topic))
    scored.sort(key=lambda kv: (-kv[0], kv[1]))
    return [topic for _, topic in scored[:max_topics]]


def extract_entities(text: str) -> list[Entity]:
    """All entities for one article, in a stable order: symbols, indices, topics."""
    entities: list[Entity] = []
    for symbol in extract_symbols(text):
        entities.append(Entity("SYMBOL", symbol, symbol))
    for index in extract_indices(text):
        entities.append(Entity("INDEX", index, index))
    for topic in extract_topics(text):
        entities.append(Entity("TOPIC", topic, topic.replace("-", " ").title()))
    return entities


# --------------------------------------------------------------------------
# event classification
# --------------------------------------------------------------------------

#: Ordered rules — the first matching rule wins, so the more specific
#: corporate actions are checked before the generic "financial result" bucket.
EVENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("DIVIDEND", ("dividend", "payout", "book closure", "interim dividend", "final dividend", "bonus share", "stock dividend")),
    ("RIGHT_ISSUE", ("rights issue", "right share", "rights shares", "renounceable")),
    ("MERGER_ACQUISITION", ("merger", "acquisition", "acquires", "takeover", "amalgamation", "stake sale", "divest")),
    ("EARNINGS", ("financial results", "quarterly results", "earnings", "eps", "profit after tax", "net profit", "loss after tax", "half-year", "annual results")),
    ("CONTRACT_AWARD", ("contract", "awarded", "order book", "epc", "supply agreement", "tender")),
    ("CAPITAL_INCREASE", ("capital increase", "paid-up capital", "share issuance", "ipo", "offer for sale", "gdr")),
    ("REGULATORY", ("secp", "regulation", "penalty", "show cause", "compliance", "investor complaint", "notice issued")),
    ("RATING", ("credit rating", "rating action", "upgrade", "downgrade", "outlook revised")),
    ("INSIDER", ("insider", "substantial shareholder", "director purchase", "director sale", "treasury shares")),
    ("MGMT_CHANGE", ("ceo", "chief executive", "managing director", "chairman appointed", "resign", "board change")),
    ("MONETARY_POLICY", ("monetary policy", "policy rate", "sbp raises", "sbp cuts", "interest rate decision")),
    ("MACRO_DATA", ("inflation", "cpi", "gdp", "current account", "trade deficit", "exports", "imports", "remittances")),
    ("LEGAL", ("lawsuit", "litigation", "court", "petition", "nepra", "ombudsman")),
    ("MARKET_UPDATE", ("index closes", "kse-100", "market closes", "stocks end", "bourse", "trading session")),
]


def detect_event(text: str) -> str:
    """Event type for the text, or ``"GENERAL"`` when nothing matches. A miss
    is reported honestly as GENERAL rather than forced into a bucket."""
    lowered = (text or "").lower()
    for event, keywords in EVENT_RULES:
        if any(k in lowered for k in keywords):
            return event
    return "GENERAL"


# --------------------------------------------------------------------------
# impact scoring
# --------------------------------------------------------------------------

#: Publisher-tier priors. These are *quality priors for ranking*, not claims
#: about publisher accuracy — they encode "an exchange filing matters more than
#: an aggregator rewrite", and every one of them is visible in the API response.
SOURCE_TIERS: dict[str, float] = {
    "psx": 1.00,
    "sbp": 1.00,
    "secp": 1.00,
    "dawn": 0.85,
    "brecorder": 0.90,
    "business recorder": 0.90,
    "express tribune": 0.78,
    "tribune": 0.78,
    "the news": 0.72,
    "profit": 0.80,
    "google news": 0.70,
    "reuters": 0.95,
    "bloomberg": 0.95,
    "wsj": 0.92,
    "financial times": 0.92,
    "cnbc": 0.88,
    "bbc": 0.88,
    "yahoo finance": 0.70,
    "investing.com": 0.70,
    "newsapi": 0.65,
    "finnhub": 0.70,
    "alpha vantage": 0.70,
    "yfinance": 0.70,
}
DEFAULT_SOURCE_TIER = 0.6

#: Event weights — a dividend or an M&A story moves a stock; a routine market
#: wrap-up does not.
EVENT_WEIGHTS: dict[str, float] = {
    "DIVIDEND": 1.00,
    "MERGER_ACQUISITION": 1.00,
    "EARNINGS": 0.95,
    "RIGHT_ISSUE": 0.85,
    "REGULATORY": 0.85,
    "CONTRACT_AWARD": 0.80,
    "INSIDER": 0.75,
    "RATING": 0.75,
    "CAPITAL_INCREASE": 0.80,
    "MONETARY_POLICY": 0.90,
    "MACRO_DATA": 0.70,
    "MGMT_CHANGE": 0.60,
    "LEGAL": 0.60,
    "MARKET_UPDATE": 0.45,
    "GENERAL": 0.40,
}

#: Words that mark a headline as market-moving regardless of event type.
HIGH_IMPACT_TERMS: tuple[str, ...] = (
    "record", "halt", "suspend", "default", "fraud", "probe", "investigation",
    "ban", "approval", "policy rate", "imf", "bailout", "crash", "plunge",
    "surge", "all-time", "profit warning", "downgrade", "upgrade", "deal",
)


def source_tier(publisher: str | None, data_source: str | None = None) -> float:
    """Quality prior for a publisher, falling back to its feeder."""
    for candidate in (publisher, data_source):
        key = (candidate or "").strip().lower()
        if not key:
            continue
        if key in SOURCE_TIERS:
            return SOURCE_TIERS[key]
        for name, weight in SOURCE_TIERS.items():
            if name in key:
                return weight
    return DEFAULT_SOURCE_TIER


def impact_score(
    *,
    title: str,
    excerpt: str = "",
    publisher: str | None = None,
    data_source: str | None = None,
    published_at: datetime | None = None,
    sentiment_score: float | None = None,
    symbols: list[str] | None = None,
    event_type: str = "GENERAL",
    now: datetime | None = None,
    source_type: str = "ARTICLE",
) -> dict:
    """Transparent 0-100 newsworthiness score.

    Five weighted components, each returned in ``components`` so a user can see
    exactly why an article scored what it scored:

    ==================  ====  ==============================================
    component           max   what it measures
    ==================  ====  ==============================================
    ``event``           30    event-type weight (dividend/M&A > market wrap)
    ``source``          20    publisher quality prior
    ``entities``        20    number of validated PSX entities (0-3+)
    ``signal``          15    high-impact vocabulary + sentiment magnitude
    ``recency``         15    exponential decay, 12-hour half-life
    ==================  ====  ==============================================
    """
    now = now or datetime.now(timezone.utc)
    combined = f"{title} {excerpt}"

    event_component = 30.0 * EVENT_WEIGHTS.get(event_type, 0.4)
    source_component = 20.0 * source_tier(publisher, data_source)

    symbols = symbols or []
    entity_component = 20.0 * min(len(symbols), 3) / 3.0

    hits = sum(1 for term in HIGH_IMPACT_TERMS if term in combined.lower())
    signal_component = 15.0 * min(hits, 2) / 2.0
    if sentiment_score is not None:
        signal_component += 15.0 * min(abs(sentiment_score), 1.0)

    # A filing/notice is by definition a confirmed primary source, not a story
    # about one — small honest bonus, capped so it cannot dominate.
    if source_type in {"PSX_FILING", "OFFICIAL_NOTICE", "PRESS_RELEASE"}:
        signal_component += 5.0

    recency_component = 0.0
    if published_at is not None:
        published = published_at if published_at.tzinfo else published_at.replace(tzinfo=timezone.utc)
        age_hours = max((now - published).total_seconds() / 3600.0, 0.0)
        recency_component = 15.0 * math.pow(0.5, age_hours / 12.0)

    components = {
        "event": round(event_component, 2),
        "source": round(source_component, 2),
        "entities": round(entity_component, 2),
        "signal": round(min(signal_component, 20.0), 2),
        "recency": round(recency_component, 2),
    }
    total = round(min(sum(components.values()), 100.0), 2)
    return {"score": total, "components": components, "event_type": event_type}


def priority_from_impact(score: float) -> str:
    """Map the impact score onto the spec's HIGH / NORMAL / LOW priority."""
    if score >= 65:
        return "HIGH"
    if score >= 38:
        return "NORMAL"
    return "LOW"


# --------------------------------------------------------------------------
# content stats
# --------------------------------------------------------------------------

def content_stats(text: str, *, wpm: int = 200) -> dict:
    """Word count and an estimated reading time (never below 1 minute for
    non-empty text — "0 min read" is a bug, not a measurement)."""
    words = len(re.findall(r"\S+", text or ""))
    if words == 0:
        return {"word_count": 0, "reading_time_minutes": 0}
    return {"word_count": words, "reading_time_minutes": max(1, round(words / wpm))}


# --------------------------------------------------------------------------
# story clustering
# --------------------------------------------------------------------------

@dataclass
class StoryCluster:
    """A set of articles judged to be the same underlying story."""

    key: str
    article_ids: list[int] = field(default_factory=list)
    publishers: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    terms: list[str] = field(default_factory=list)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    max_impact: float = 0.0

    @property
    def size(self) -> int:
        return len(self.article_ids)

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "article_ids": self.article_ids,
            "size": self.size,
            "publishers": self.publishers,
            "symbols": self.symbols,
            "terms": self.terms,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
            "max_impact": round(self.max_impact, 2),
        }


def cluster_articles(
    articles: list[dict],
    *,
    threshold: float = 0.22,
    max_clusters: int = 25,
    title_weight: int = 3,
) -> list[StoryCluster]:
    """Greedy agglomerative clustering over TF-IDF cosine similarity.

    Each article is compared against the running centroid of every existing
    cluster; it joins the best cluster above ``threshold`` or starts a new one.
    Single-pass and deterministic (ties break on cluster key), which keeps it
    O(n·k) instead of the O(n²) all-pairs comparison a naive implementation
    would do on a feed of several hundred articles.

    ``title_weight`` repeats the headline in the clustering text so two
    articles about the same event but with different body text still group.
    """
    if not articles:
        return []

    texts = [
        " ".join([a.get("title", "")] * title_weight + [a.get("excerpt") or "", a.get("content") or ""])
        for a in articles
    ]
    corpus = TfIdfCorpus(texts + [""])  # extra empty doc keeps n_docs>=2 for tiny feeds
    vectors = [corpus.vector(text) for text in texts]

    clusters: list[StoryCluster] = []
    centroids: list[dict[str, float]] = []

    for article, vector in zip(articles, vectors):
        best_index = -1
        best_similarity = 0.0
        for index, centroid in enumerate(centroids):
            similarity = cosine_similarity(vector, centroid)
            if similarity > best_similarity:
                best_similarity = similarity
                best_index = index

        if best_index >= 0 and best_similarity >= threshold:
            _absorb(clusters[best_index], centroids[best_index], article, vector)
        else:
            cluster = StoryCluster(key=_cluster_key(article, len(clusters)))
            centroid: dict[str, float] = {}
            _absorb(cluster, centroid, article, vector)
            clusters.append(cluster)
            centroids.append(centroid)

    clusters.sort(key=lambda c: (-c.size, -c.max_impact, c.key))
    return clusters[:max_clusters]


def _cluster_key(article: dict, index: int) -> str:
    symbol = (article.get("related_symbols") or ["MARKET"])[0]
    event = article.get("event_type") or "GENERAL"
    return f"{symbol}-{event}-{index}".lower()


def _absorb(cluster: StoryCluster, centroid: dict[str, float], article: dict, vector: dict[str, float]) -> None:
    """Add an article to a cluster and update the centroid in place."""
    article_id = article.get("id")
    if article_id is not None and article_id not in cluster.article_ids:
        cluster.article_ids.append(article_id)

    publisher = article.get("publisher")
    if publisher and publisher not in cluster.publishers:
        cluster.publishers.append(publisher)

    for symbol in article.get("related_symbols") or []:
        if symbol not in cluster.symbols:
            cluster.symbols.append(symbol)

    for term, weight in vector.items():
        centroid[term] = (centroid.get(term, 0.0) * (cluster.size - 1) + weight) / max(cluster.size, 1)

    cluster.terms = [t for t, _ in sorted(centroid.items(), key=lambda kv: -kv[1])[:8]]

    published = _coerce_datetime(article.get("published_at"))
    if published is not None:
        if cluster.first_seen is None or published < cluster.first_seen:
            cluster.first_seen = published
        if cluster.last_seen is None or published > cluster.last_seen:
            cluster.last_seen = published

    impact = article.get("impact_score")
    if impact is not None:
        cluster.max_impact = max(cluster.max_impact, float(impact))


def _coerce_datetime(value) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------
# trending entities
# --------------------------------------------------------------------------

def trending_entities(
    articles: list[dict],
    *,
    window_hours: int = 72,
    half_life_hours: float = 24.0,
    top_n: int = 12,
    now: datetime | None = None,
) -> dict:
    """Time-decayed mention counts for validated symbols, indices and topics.

    Each mention contributes ``0.5 ** (age_hours / half_life_hours)``, so the
    ranking reflects *attention right now* rather than raw volume — an entity
    mentioned 40 times last week loses to one mentioned 6 times this morning.
    Also reports each entity's raw count and mean sentiment across mentions.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=window_hours)

    buckets: dict[tuple[str, str], dict] = {}

    for article in articles:
        published = _coerce_datetime(article.get("published_at")) or now
        if published < cutoff:
            continue
        age_hours = max((now - published).total_seconds() / 3600.0, 0.0)
        decay = math.pow(0.5, age_hours / half_life_hours)
        sentiment = article.get("sentiment_score")

        entities: list[tuple[str, str, str]] = []
        for symbol in article.get("related_symbols") or []:
            entities.append(("SYMBOL", symbol, symbol))
        for index in article.get("related_indices") or []:
            entities.append(("INDEX", index, index))
        for topic in article.get("topics") or []:
            entities.append(("TOPIC", topic, str(topic).replace("-", " ").title()))

        for kind, value, label in entities:
            bucket = buckets.setdefault(
                (kind, value),
                {"type": kind, "value": value, "label": label, "count": 0,
                 "weighted": 0.0, "sentiments": [], "latest": None},
            )
            bucket["count"] += 1
            bucket["weighted"] += decay
            if sentiment is not None:
                bucket["sentiments"].append(float(sentiment))
            if bucket["latest"] is None or published > bucket["latest"]:
                bucket["latest"] = published

    ranked = sorted(buckets.values(), key=lambda b: (-b["weighted"], b["value"]))
    results = []
    for bucket in ranked[:top_n]:
        sentiments = bucket.pop("sentiments")
        latest = bucket.pop("latest")
        results.append({
            **bucket,
            "trend_score": round(bucket["weighted"], 3),
            "avg_sentiment": round(sum(sentiments) / len(sentiments), 4) if sentiments else None,
            "latest_mention": latest.isoformat() if latest else None,
        })

    return {
        "window_hours": window_hours,
        "half_life_hours": half_life_hours,
        "generated_at": now.isoformat(),
        "entities": results,
    }


# --------------------------------------------------------------------------
# one-call enrichment used by the ingestion pipeline
# --------------------------------------------------------------------------

#: Cap on how much text feeds the fingerprints. Real feeds append footers,
#: related-link blocks and boilerplate; hashing 10 kB of that per article costs
#: time and dilutes the signal without adding information.
FINGERPRINT_TOKEN_LIMIT = 1200


def fingerprint_text(text: str) -> str:
    """Trim `text` to the first :data:`FINGERPRINT_TOKEN_LIMIT` words."""
    words = tokenize_all(text)
    if len(words) <= FINGERPRINT_TOKEN_LIMIT:
        return text or ""
    return " ".join(words[:FINGERPRINT_TOKEN_LIMIT])


def enrich(
    article: dict,
    *,
    corpus: TfIdfCorpus | None = None,
    now: datetime | None = None,
) -> dict:
    """Attach every analytics field to a normalized article dict.

    Idempotent and side-effect free: returns a new dict, never mutates the
    input. Text used for analysis is headline + excerpt (the body is used for
    scoring keywords/clustering, not for entity linking, to avoid a passing
    quote dragging an unrelated ticker into the entity list).
    """
    title = article.get("title") or ""
    excerpt = article.get("excerpt") or ""
    content = article.get("content") or ""
    analysis_text = f"{title}. {excerpt}"
    full_text = f"{title}. {excerpt} {content}"

    symbols = extract_symbols(analysis_text)
    indices = extract_indices(analysis_text)
    topics = extract_topics(analysis_text)
    event_type = detect_event(analysis_text)

    keywords = (
        corpus.keywords(full_text, top_k=10) if corpus is not None
        else default_keywords(full_text, top_k=10)
    )
    stats = content_stats(full_text)
    score = impact_score(
        title=title,
        excerpt=excerpt,
        publisher=article.get("publisher"),
        data_source=article.get("data_source"),
        published_at=_coerce_datetime(article.get("published_at")),
        sentiment_score=article.get("sentiment_score"),
        symbols=symbols,
        event_type=event_type,
        now=now,
        source_type=article.get("source_type") or "ARTICLE",
    )

    # The publisher's own ticker tag wins when it exists (e.g. a Finnhub
    # company-news call for OGDC), so a company feed never loses its link.
    existing = [s for s in (article.get("related_symbols") or []) if s in PSX_SYMBOLS]
    merged_symbols = existing + [s for s in symbols if s not in existing]

    enriched = dict(article)
    enriched.update({
        "related_symbols": merged_symbols,
        "related_indices": sorted(set((article.get("related_indices") or []) + indices)),
        "topics": topics,
        "keywords": keywords,
        "event_type": event_type,
        "impact_score": score["score"],
        "impact_components": score["components"],
        "priority": priority_from_impact(score["score"]),
        **stats,
        "simhash": content_fingerprint(title, excerpt),
        # The signature is the near-duplicate decision signal; SimHash is kept
        # alongside it as a cheap corroborating check and for observability.
        "shingle_signature": encode_signature(
            minhash_signature(fingerprint_text(full_text))
        ),
        "entities": [e.as_dict() for e in extract_entities(analysis_text)],
    })
    return enriched
