import os
import re
import json
import math
import hashlib
import difflib
import requests
import unicodedata
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any, Union, Callable
from deep_translator import GoogleTranslator, MyMemoryTranslator
from app.core.config import SUPPORTED_LANGUAGES, STORY_PERSONAS

MAX_CHRONOLOGY_RETRIES: int = 1


@dataclass
class SceneBlock:
    """
    Phase 4A Authoritative SceneBlock Representation.
    Preserves strict separation between source movie coordinates and output narration coordinates.

    Coordinate Hierarchy:
    - movie_start / movie_end: SOURCE MOVIE timeline coordinates (factual source anchors).
    - narration_start / narration_end: OUTPUT EXPLAINER timeline coordinates (derived from actual TTS).
    - estimated_duration: Pre-TTS planning estimate based on word budget / WPM (never final authority).
    - actual_duration / speech_dur: Authoritative measured duration of synthesized TTS audio.
    """
    movie_start: float          # seconds into SOURCE movie (e.g. 185.0)
    movie_end: float            # seconds into SOURCE movie (e.g. 290.0)
    narration_text: str         # clean spoken narration for this scene
    word_count: int             # word count in narration
    speech_dur: float = 0.0     # actual allocated speech duration (seconds)
    narration_start: float = 0.0 # start timestamp in explainer voiceover
    narration_end: float = 0.0   # end timestamp in explainer voiceover
    dialogue_ref: Optional[str] = None # exact dialogue quote or reference from source movie (verified source-bound or None)
    estimated_duration: float = 0.0  # pre-TTS estimated narration duration (seconds)
    actual_duration: float = 0.0     # authoritative measured TTS duration (seconds)
    audio_file: Optional[str] = None # path or identifier of synthesized audio file
    block_id: Optional[str] = None   # optional scene/block identifier (e.g. "SCENE_1")
    is_authoritative: bool = False   # True once locked to actual synthesized TTS audio
    evidence_ref: Optional[str] = None # Phase 3B evidence packet reference (e.g. "EP-001")
    story_step: Optional[int] = None   # Phase 3B story plan step number
    transcript_source: str = "none"    # Phase 6A: Source of dialogue cues ("existing_subtitles", "user_transcript", "asr", "none")
    source_timestamp: Optional[float] = None # Phase 6G.3: Authoritative source movie timestamp (from DialogueRefProvenance / EvidencePacket)
    chronology_valid: bool = True       # Phase 6G.3: True if scene sequence preserves source-grounded order
    chronology_error: Optional[str] = None # Phase 6G.3: Diagnostic error if chronology violated

    def to_dict(self) -> Dict[str, Any]:
        return {
            "movie_start": self.movie_start,
            "movie_end": self.movie_end,
            "narration_text": self.narration_text,
            "word_count": self.word_count,
            "speech_dur": self.speech_dur,
            "narration_start": self.narration_start,
            "narration_end": self.narration_end,
            "dialogue_ref": self.dialogue_ref,
            "estimated_duration": self.estimated_duration,
            "actual_duration": self.actual_duration,
            "audio_file": self.audio_file,
            "block_id": self.block_id,
            "is_authoritative": self.is_authoritative,
            "evidence_ref": self.evidence_ref,
            "story_step": self.story_step,
            "transcript_source": self.transcript_source,
            "source_timestamp": self.source_timestamp,
            "chronology_valid": self.chronology_valid,
            "chronology_error": self.chronology_error,
        }


@dataclass
class EvidencePacket:
    """
    Phase 3B Deterministic Evidence Packet.
    Pairs each selected roadmap point directly to authoritative source dialogue,
    bounded local context, act placement, and source traceability.
    """
    packet_id: str                      # unique sequence identifier (e.g. "EP-001")
    movie_start: float                  # start timestamp in source video (seconds)
    movie_end: float                    # end timestamp in source video (seconds)
    source_text: str                    # verbatim dialogue / event text from source
    act: str                            # narrative act ("Act 1", "Act 2A", "Act 2B", "Act 3", "Epilogue")
    sequence_index: int                 # 0-indexed chronological sequence position
    cue_index: Optional[int] = None     # index into original source cues array
    context_before: str = ""            # bounded local source cues immediately prior
    context_after: str = ""             # bounded local source cues immediately following
    confidence: float = 1.0             # source match confidence (1.0 = direct verified source cue)
    is_resolved: bool = True            # whether evidence successfully maps to source
    metadata: Optional[Dict[str, Any]] = None  # optional match/traceability metadata

    def to_dict(self) -> Dict[str, Any]:
        return {
            "packet_id": self.packet_id,
            "movie_start": self.movie_start,
            "movie_end": self.movie_end,
            "source_text": self.source_text,
            "act": self.act,
            "sequence_index": self.sequence_index,
            "cue_index": self.cue_index,
            "context_before": self.context_before,
            "context_after": self.context_after,
            "confidence": self.confidence,
            "is_resolved": self.is_resolved,
            "metadata": self.metadata or {}
        }


@dataclass
class StoryPlanItem:
    """
    Phase 3B Structured Story Plan Item.
    Intermediate planning representation linking sequence steps directly to EvidencePackets,
    enforcing chronological progression, core actions, mentioned entities, and word budgets.
    """
    step: int                           # 1-indexed plan sequence step
    source_timestamp: float             # seconds in source timeline
    act: str                            # narrative act
    evidence_ref: str                   # packet_id of underlying EvidencePacket (e.g. "EP-001")
    core_event: str                     # concise event description strictly grounded in evidence
    entities: List[str]                 # characters, locations, objects directly mentioned in source
    narration_purpose: str              # structural role (e.g. "hook", "setup", "escalation", "climax", "resolution")
    budget_words: int                   # allocated target spoken word count for this beat
    is_inferred: bool = False           # flag indicating if any minimal connective inference was used

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "source_timestamp": self.source_timestamp,
            "act": self.act,
            "evidence_ref": self.evidence_ref,
            "core_event": self.core_event,
            "entities": self.entities,
            "narration_purpose": self.narration_purpose,
            "budget_words": self.budget_words,
            "is_inferred": self.is_inferred
        }


@dataclass
class DialogueRefProvenance:
    """
    Phase 6F: Source-Bound Dialogue Reference Provenance Representation.
    Enforces strict provenance verification: a dialogue_ref MUST trace directly to
    an authoritative EvidencePacket or source transcript cue. Unverified or hallucinated
    dialogue references are safely converted to None (null).
    """
    status: str                         # "SOURCE_BOUND" or "NOT_SOURCE_BOUND"
    is_source_bound: bool
    dialogue_ref: Optional[str]         # verified clean reference, or None if NOT_SOURCE_BOUND
    source_text: Optional[str] = None   # actual source text where match was found
    evidence_ref: Optional[str] = None  # packet_id (e.g. "EP-001") if matched to an EvidencePacket
    cue_index: Optional[int] = None     # index into source cues if matched
    source_timestamp: Optional[float] = None # start timestamp of source cue/packet
    match_type: Optional[str] = None    # "exact", "normalized_exact", "source_contained_excerpt", "source_contains_excerpt", "none"
    normalized_ref: str = ""
    normalized_source: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "is_source_bound": self.is_source_bound,
            "dialogue_ref": self.dialogue_ref,
            "evidence_ref": self.evidence_ref,
            "source_text": self.source_text,
            "source_timestamp": self.source_timestamp,
            "cue_index": self.cue_index,
            "match_type": self.match_type,
            "normalized_ref": self.normalized_ref,
            "normalized_source": self.normalized_source,
            "reason": self.reason
        }


# =============================================================================
# PHASE 5: CONTROLLED SEMANTIC RETRIEVAL ABSTRACTION & HELPERS
# =============================================================================

class EmbeddingProvider:
    """
    Abstract Base Class for semantic embedding providers (Phase 5 / Phase 5B).
    Decouples core business logic from specific vendors and ensures safe error handling.
    """
    provider_id: str = "generic"
    model_id: str = "default"

    @property
    def namespace(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    def embed_text(self, text: str) -> Optional[List[float]]:
        """Embeds a single string into a vector. Returns list of floats or None on failure."""
        raise NotImplementedError

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Embeds a batch of strings. Returns list of vectors (or None per item on failure)."""
        return [self.embed_text(t) for t in texts]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """
    Production embedding provider utilizing standard OpenAI-compatible REST endpoints (Phase 5B).
    Compatible with OpenAI (api.openai.com), 9Router (local proxy), Ollama, LocalAI, vLLM, or custom proxies.
    Defensively validates input, HTTP responses, dimensions, and finite numbers without leaking credentials.
    """
    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        api_key: str = "",
        model_name: str = "text-embedding-3-small",
        timeout: float = 10.0,
        expected_dim: Optional[int] = None,
        max_batch_size: int = 64,
        provider_name: str = "openai_compatible"
    ):
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = (api_key or "").strip()
        self.model_name = (model_name or "text-embedding-3-small").strip()
        self.timeout = max(1.0, float(timeout))
        self.expected_dim = expected_dim
        self.max_batch_size = max(1, min(2048, int(max_batch_size)))
        self.provider_id = (provider_name or "openai_compatible").strip()
        self.model_id = self.model_name

        # Resolve endpoint
        base = self.base_url
        if base.endswith("/embeddings"):
            self.endpoint = base
        elif base.endswith("/v1"):
            self.endpoint = f"{base}/embeddings"
        else:
            self.endpoint = f"{base}/v1/embeddings"

    def _validate_vector(self, vec: Any) -> Optional[List[float]]:
        if not isinstance(vec, (list, tuple)) or len(vec) == 0:
            return None
        if self.expected_dim is not None and len(vec) != self.expected_dim:
            return None
        clean: List[float] = []
        for x in vec:
            if not isinstance(x, (int, float)) or not math.isfinite(x):
                return None
            clean.append(float(x))
        if self.expected_dim is None and clean:
            self.expected_dim = len(clean)
        return clean

    def embed_text(self, text: str) -> Optional[List[float]]:
        if not text or not str(text).strip():
            return None
        clean_text = str(text).strip()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "input": clean_text,
            "model": self.model_name
        }

        try:
            res = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
            if res.status_code != 200:
                print(f"[EmbeddingProvider Notice] Provider HTTP {res.status_code} ({self.provider_id})")
                return None
            data = res.json()
            if not isinstance(data, dict):
                return None
            data_items = data.get("data", [])
            if not isinstance(data_items, list) or not data_items:
                return None
            first_item = data_items[0]
            if not isinstance(first_item, dict):
                return None
            raw_vec = first_item.get("embedding")
            return self._validate_vector(raw_vec)
        except Exception as e:
            # Defensive logging without logging secrets or full text (Security Rule 1/2)
            print(f"[EmbeddingProvider Notice] Request failed: {type(e).__name__} ({self.provider_id})")
            return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        valid_indices: List[int] = []
        valid_texts: List[str] = []

        for idx, t in enumerate(texts):
            if t and str(t).strip():
                valid_indices.append(idx)
                valid_texts.append(str(t).strip())

        if not valid_texts:
            return results

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        for chunk_start in range(0, len(valid_texts), self.max_batch_size):
            chunk_end = chunk_start + self.max_batch_size
            chunk_slice_texts = valid_texts[chunk_start:chunk_end]
            chunk_orig_indices = valid_indices[chunk_start:chunk_end]

            payload = {
                "input": chunk_slice_texts,
                "model": self.model_name
            }

            try:
                res = requests.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
                if res.status_code != 200:
                    print(f"[EmbeddingProvider Notice] Batch HTTP {res.status_code} on chunk [{chunk_start}:{chunk_end}]")
                    continue
                data = res.json()
                if not isinstance(data, dict):
                    continue
                items = data.get("data", [])
                if not isinstance(items, list):
                    continue

                indexed_vectors: Dict[int, List[float]] = {}
                for itm_idx, itm in enumerate(items):
                    if isinstance(itm, dict) and "embedding" in itm:
                        pos = itm.get("index", itm_idx)
                        if isinstance(pos, int):
                            vec = self._validate_vector(itm.get("embedding"))
                            if vec is not None:
                                indexed_vectors[pos] = vec

                for local_idx, orig_idx in enumerate(chunk_orig_indices):
                    if local_idx in indexed_vectors:
                        results[orig_idx] = indexed_vectors[local_idx]

            except Exception as e:
                print(f"[EmbeddingProvider Notice] Batch request failed on chunk [{chunk_start}:{chunk_end}]: {type(e).__name__}")

        return results


class DictEmbeddingProvider(EmbeddingProvider):
    """
    Deterministic embedding provider for unit tests, adversarial benchmarks,
    and controlled mock embedding maps (Phase 5).
    """
    def __init__(
        self,
        vector_map: Optional[Dict[str, List[float]]] = None,
        default_dim: int = 4,
        provider_name: str = "dict",
        model_name: str = "mock"
    ):
        self.vector_map = vector_map or {}
        self.default_dim = default_dim
        self.provider_id = provider_name
        self.model_id = model_name
        self.failure_mode = False
        self.dimension_mismatch_mode = False
        self.malformed_mode = False

    def embed_text(self, text: str) -> Optional[List[float]]:
        if self.failure_mode:
            raise RuntimeError("Simulated embedding provider failure")
        if not text:
            return None
        if self.malformed_mode:
            return [float("nan"), float("inf")]
        if self.dimension_mismatch_mode:
            return [1.0] * (self.default_dim + 2)
        clean = text.strip()
        if clean in self.vector_map:
            return self.vector_map[clean]
        clean_lower = clean.lower()
        for k, v in self.vector_map.items():
            if k.lower() == clean_lower:
                return v
        for k, v in self.vector_map.items():
            if k.lower() in clean_lower or clean_lower in k.lower():
                return v
        return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        if self.failure_mode:
            raise RuntimeError("Simulated embedding provider failure")
        return [self.embed_text(t) for t in texts]


def cosine_similarity(v1: Any, v2: Any) -> float:
    """
    Safe pure-Python cosine similarity computation (Phase 5).
    Guarantees finite output in [-1.0, 1.0], zero-drift, and complete safety against:
    - None, empty, or mismatched-dimension vectors
    - Non-numeric or non-finite values (NaN, +Inf, -Inf)
    - Zero-norm vectors
    """
    if not v1 or not v2:
        return 0.0
    try:
        if len(v1) != len(v2):
            return 0.0
        dot = 0.0
        norm1 = 0.0
        norm2 = 0.0
        for a, b in zip(v1, v2):
            if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
                return 0.0
            if not math.isfinite(a) or not math.isfinite(b):
                return 0.0
            dot += float(a) * float(b)
            norm1 += float(a) * float(a)
            norm2 += float(b) * float(b)
        if norm1 <= 0.0 or norm2 <= 0.0:
            return 0.0
        sim = dot / (math.sqrt(norm1) * math.sqrt(norm2))
        return round(max(-1.0, min(1.0, sim)), 4)
    except Exception:
        return 0.0


class SemanticEmbeddingCache:
    """
    Bounded in-memory cache for dialogue cue embeddings (Phase 5 / Phase 5B).
    Keys on SHA-256 hash of namespace (provider:model) and normalized text to avoid
    cross-provider vector corruption while preserving bounded memory limits.
    """
    def __init__(self, max_size: int = 5000):
        self.max_size = max(1, max_size)
        self._cache: Dict[str, List[float]] = {}
        self._order: List[str] = []

    def _key(self, text: str, namespace: str = "") -> str:
        norm_txt = (text or "").strip()
        norm_ns = (namespace or "").strip()
        raw = f"{norm_ns}::{norm_txt}" if norm_ns else norm_txt
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, text: str, namespace: str = "") -> Optional[List[float]]:
        k = self._key(text, namespace=namespace)
        return self._cache.get(k)

    def put(self, text: str, vec: List[float], namespace: str = "") -> None:
        if not vec:
            return
        k = self._key(text, namespace=namespace)
        if k in self._cache:
            self._cache[k] = vec
            return
        if len(self._cache) >= self.max_size and self._order:
            oldest = self._order.pop(0)
            self._cache.pop(oldest, None)
        self._cache[k] = vec
        self._order.append(k)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()

    def __len__(self) -> int:
        return len(self._cache)


_GLOBAL_EMBEDDING_CACHE = SemanticEmbeddingCache(max_size=5000)


class ScriptEngine:
    """
    Multilingual Storyboard & Narrative Generator for Movie Explainers.
    Supports 15+ languages, 4 storytelling personas, spoiler toggles, and virality scoring.
    """

    @staticmethod
    def auto_detect_creative_context(
        title: str,
        description: str = "",
        transcript_sample: str = ""
    ) -> Dict[str, str]:
        """
        Analyzes movie title, description, and transcript text to auto-detect
        the ideal genre, storytelling tone, background music mood, and spoiler mode.
        Guarantees 1-click mistake-proof alignment for users.
        """
        combined = f"{title} {description} {transcript_sample}".lower()

        horror_kw = ["ghost", "demon", "haunted", "witch", "curse", "creepy", "monsters", "chucky", "jigsaw", "killer", "conjuring", "mansion", "attic", "blood", "خوفناک", "بھوت", "चुड़ैल", "भूत"]
        action_kw = ["mafia", "gangster", "heist", "police", "gun", "assassin", "agent", "spy", "thriller", "chase", "combat", "fight", "revenge", "explosion", "cartel", "hitman", "rounds", "گینگسٹر", "مافیا", "गैंगस्टर", "गोलियां"]
        romance_kw = ["love", "romance", "heartbreak", "crying", "dying", "illness", "tears", "husband", "wife", "marriage", "divorce", "lover", "tragic", "hospital", "corridor", "letter", "محبت", "عشق", "آنسو", "प्यार", "दर्द", "आंसू"]
        scifi_kw = ["space", "alien", "robot", "galaxy", "future", "simulation", "matrix", "planet", "time travel", "cyborg"]
        doc_kw = ["documentary", "historical documentary", "history", "ancient", "empire", "wwii", "world war", "civilization", "archaeological"]
        bio_kw = ["biography", "biopic", "life story", "autobiography"]
        crime_kw = ["true crime", "forensic", "serial killer", "unsolved mystery", "cold case"]
        tech_kw = ["case study", "silicon valley", "startup", "tech giant", "billion dollar"]

        det_lang = ScriptEngine.detect_transcript_language(combined)
        # Action/Spy/Thriller in title or description takes priority for movies
        if any(kw in combined for kw in action_kw):
            res = {
                "genre": "movie_recap",
                "persona": "hollywood_trailer",
                "mood": "tense",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in horror_kw):
            res = {
                "genre": "movie_recap",
                "persona": "documentary",
                "mood": "suspense",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in doc_kw):
            res = {
                "genre": "documentary",
                "persona": "documentary",
                "mood": "suspense",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in bio_kw):
            res = {
                "genre": "biography",
                "persona": "documentary",
                "mood": "emotional",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in crime_kw):
            res = {
                "genre": "true_crime",
                "persona": "documentary",
                "mood": "tense",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in tech_kw):
            res = {
                "genre": "tech_science",
                "persona": "viral_fast",
                "mood": "upbeat",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in romance_kw):
            res = {
                "genre": "movie_recap",
                "persona": "hollywood_trailer",
                "mood": "emotional",
                "spoiler_mode": "full_recap"
            }
        elif any(kw in combined for kw in scifi_kw):
            res = {
                "genre": "movie_recap",
                "persona": "hollywood_trailer",
                "mood": "suspense",
                "spoiler_mode": "full_recap"
            }
        else:
            res = {
                "genre": "movie_recap",
                "persona": "hollywood_trailer",
                "mood": "suspense",
                "spoiler_mode": "full_recap"
            }
        res["detected_source_lang"] = det_lang
        return res

    @staticmethod
    def detect_transcript_language(text: str) -> str:
        """
        Auto-detects language of source transcript, subtitles, or text.
        Supports Urdu, Arabic, Hindi, Turkish, Korean, Japanese, Russian, and English.
        """
        if not text:
            return "en"
        
        sample = text[:3000]
        # Urdu distinctive characters (ٹ, ڈ, ڑ, ے, ں, ہ, ۂ, ۃ, ؤ)
        if re.search(r'[\u0679\u0688\u0691\u06d2\u06ba\u06c1\u06c2\u06c3\u0624]', sample):
            return "ur"
        # Arabic script (without distinctive Urdu letters)
        if re.search(r'[\u0600-\u06FF]', sample):
            return "ar"
        # Hindi Devanagari script
        if re.search(r'[\u0900-\u097F]', sample):
            return "hi"
        # Korean Hangul
        if re.search(r'[\uAC00-\uD7AF\u1100-\u11FF]', sample):
            return "ko"
        # Japanese Kana
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF]', sample):
            return "ja"
        # Russian Cyrillic
        if re.search(r'[\u0400-\u04FF]', sample):
            return "ru"
        # Turkish distinctive letters (ç, ğ, ı, İ, ö, ş, ü, Ğ, Ş)
        if re.search(r'[ğşışİĞŞ]', sample):
            return "tr"
        
        return "en"

    @staticmethod
    def detect_episode_info(title: str, description: str = "") -> Dict[str, Any]:
        """
        Detects if content is an episodic series / drama (e.g. Episode 01, Ep 14, قسط 5).
        Returns dict with is_episodic bool, current episode number, and next episode number.
        """
        combined = f"{title} {description}".lower()
        patterns = [
            r'(?:episode|ep|ep\.)\s*0*(\d+)',
            r'(?:قسط|قسمت|حلقہ)\s*(?:نمبر)?\s*0*(\d+)',
            r'\be0*(\d+)\b'
        ]
        for pat in patterns:
            m = re.search(pat, combined, re.IGNORECASE)
            if m:
                try:
                    num = int(m.group(1))
                    return {
                        "is_episodic": True,
                        "episode_num": num,
                        "next_episode_num": num + 1
                    }
                except Exception:
                    pass
        return {
            "is_episodic": False,
            "episode_num": None,
            "next_episode_num": None
        }

    @staticmethod
    def strip_code_and_developer_artifacts(raw_text: str) -> str:
        """
        Strips markdown code blocks, python test functions (e.g. def test_word_count),
        assertions, reasoning tags (<think>...</think>), and developer comments
        inadvertently generated by reasoning/coding LLMs.
        Preserves spoken narration, [SCENE: MM:SS - MM:SS] brackets, and [SFX: ...] cues.
        """
        if not raw_text:
            return ""

        text = raw_text

        # 1. Strip <think>...</think> blocks
        text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)

        # 2. Strip markdown code fences (e.g. ```python ... ``` or ``` ... ```)
        text = re.sub(r'```[a-zA-Z0-9_-]*[\s\S]*?```', '', text)

        # 3. Strip raw python functions (def test_... or def check_... up to unindented text or EOF)
        text = re.sub(r'(?m)^def\s+[a-zA-Z0-9_]+\s*\(.*?\).*?:\s*\n(?:[ \t]+.*\n)*', '', text)

        # 4. Strip assertion lines, dev notes, and ponytail test harness tags
        text = re.sub(r'(?m)^[ \t]*assert\s+.*$', '', text)
        text = re.sub(r'(?m)^[ \t]*#\s*(?:ponytail|test|todo|ci|unit\s*test).*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'(?m)^[ \t]*->\s*(?:skipped|note|test|full\s*testing).*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'(?m)^[ \t]*return\s+(?:True|False|count).*$', '', text)

        # 5. Clean up redundant empty lines
        text = re.sub(r'\n{3,}', '\n\n', text).strip()
        return text

    @staticmethod
    def _evaluate_block_importance(block_text: str) -> float:
        """
        Phase 1 Interim Heuristic for Content-Aware Block Evaluation:
        1. Introduced in Phase 1 to replace the content-blind positional middle deletion (drop_idx = len//2).
        2. Fully deterministic function evaluating narrative triggers, dialogue tags, and substantive text length.
        3. Operates as an interim heuristic to preserve critical plot points during budget clamping.
        4. Its keyword vocabulary (EN, UR, HI) is not a complete multilingual semantic model.
        5. Comprehensive multilingual semantic narrative scoring belongs to a later phase.
        """
        if not block_text:
            return 0.0
        words = re.findall(r'\w+', block_text.lower(), flags=re.UNICODE)
        if not words:
            return 0.0
        triggers = {
            "secret", "killed", "mystery", "shock", "trap", "never", "nobody", "twisted", "died", "lie",
            "revelation", "discover", "twist", "truth", "clue", "murder", "confront", "escape", "fight",
            "victim", "alive", "faked", "frame", "courtroom", "betray", "mastermind",
            "راز", "قتل", "دھوکہ", "خوفناک", "ہوش", "حیران", "خطرناک", "سازش", "انجام", "انکشاف",
            "सच", "मौत", "धोखा", "रहस्य", "चौंकाने", "खतरनाक", "साजिश", "खुलासा"
        }
        kw_count = sum(1 for w in words if w in triggers)
        has_dialogue = 1 if any(tag in block_text.lower() for tag in ["[dialogue_ref:", '"', '“']) else 0
        return (kw_count * 10.0) + (has_dialogue * 15.0) + (len(words) * 0.5)

    @staticmethod
    def clamp_script_word_budget(
        script_text: str,
        target_duration_mins: int = 3,
        target_lang: str = "en",
        voice_speed: str = "fast"
    ) -> str:
        """
        Non-Destructive Narrative Auto-Budgeting.
        Clamps storyboard script length to strict duration-budget word ceilings
        WITHOUT severing the climax or final scenes.
        Pillars (Scene 1 Hook & Final Climax/Ending) are permanently protected.
        """
        if not script_text or not script_text.strip():
            return script_text

        target_words = ScriptEngine.calculate_target_words(target_duration_mins, voice_speed, target_lang)
        # Allow buffer up to +8%
        max_words = max(180, int(round(target_words * 1.08)))

        words = script_text.split()
        if len(words) <= max_words:
            return script_text

        # Split into scene blocks
        blocks = [b.strip() for b in re.split(r'\n\s*\n', script_text.strip()) if b.strip()]
        if len(blocks) > 2:
            # Pillar 1: First scene (Hook)
            pillar_first = blocks[0]
            # Pillar 2: Last scene (Climax / Ending)
            pillar_last = blocks[-1]

            p1_words = len(pillar_first.split())
            p2_words = len(pillar_last.split())

            middle_blocks = blocks[1:-1]
            remaining_budget = max(50, max_words - (p1_words + p2_words))

            # Total middle words
            mid_words = sum(len(b.split()) for b in middle_blocks)

            if mid_words <= remaining_budget:
                retained_middle = middle_blocks
            else:
                # Proportional compression of middle blocks
                compression_ratio = remaining_budget / max(1, mid_words)
                retained_middle = []
                for b in middle_blocks:
                    b_sentences = re.split(r'(?<=[.!?۔؟\n])\s+', b.strip())
                    if len(b_sentences) > 1:
                        target_s_count = max(1, int(round(len(b_sentences) * compression_ratio)))
                        compressed_b = " ".join(b_sentences[:target_s_count]).strip()
                        if not any(compressed_b.endswith(p) for p in [".", "۔", "!", "?", "؟"]):
                            compressed_b += "۔" if any(ord(c) > 1500 for c in compressed_b) else "."
                        retained_middle.append(compressed_b)
                    else:
                        retained_middle.append(b)

                # If still over budget, drop least critical intermediate blocks via content-aware scoring
                cur_total = p1_words + p2_words + sum(len(b.split()) for b in retained_middle)
                while cur_total > max_words and len(retained_middle) > 1:
                    drop_idx = min(
                        range(len(retained_middle)),
                        key=lambda i: (
                            ScriptEngine._evaluate_block_importance(retained_middle[i]),
                            len(retained_middle[i].split()),
                            -i
                        )
                    )
                    retained_middle.pop(drop_idx)
                    cur_total = p1_words + p2_words + sum(len(b.split()) for b in retained_middle)

            final_blocks = [pillar_first] + retained_middle + [pillar_last]
            result = "\n\n".join(final_blocks).strip()
            if not any(result.endswith(p) for p in [".", "۔", "!", "?", "؟"]):
                result += "۔" if any(ord(c) > 1500 for c in result) else "."
            return result

        # Single block or only 2 blocks: clamp at sentence boundary while preserving first and last sentence
        sentences = re.split(r'(?<=[.!?۔؟\n])\s+', script_text.strip())
        if len(sentences) > 2:
            first_s = sentences[0]
            last_s = sentences[-1]
            rem_words = max_words - (len(first_s.split()) + len(last_s.split()))
            retained_mid = []
            cur_w = 0
            for s in sentences[1:-1]:
                s_w = len(s.split())
                if cur_w + s_w <= rem_words:
                    retained_mid.append(s)
                    cur_w += s_w
                else:
                    break
            res = " ".join([first_s] + retained_mid + [last_s]).strip()
            if not any(res.endswith(p) for p in [".", "۔", "!", "?", "؟"]):
                res += "۔" if any(ord(c) > 1500 for c in res) else "."
            return res

        return script_text

    @staticmethod
    def calculate_hook_score(script_text: str, lang: str = "en") -> Dict[str, Any]:
        """
        Evaluates the opening 5 seconds (first 25-40 words) for emotional hook,
        curiosity gap, high-stakes words, and viewer retention potential.
        """
        if not script_text:
            return {"score": 0, "rating": "Empty", "analysis": "No script provided."}

        first_passage = " ".join(script_text.strip().split()[:45]).lower()
        score = 65  # Base score

        # Universal curiosity and high-stakes markers
        trigger_keywords = [
            # English
            "secret", "killed", "mystery", "shock", "trap", "never", "nobody", "twisted", "died", "lie",
            # Urdu / Hindi
            "راز", "قتل", "دھوکہ", "خوفناک", "ہوش", "حیران", "خطرناک", "سازش", "انجام",
            "सच", "मौत", "धोखा", "रहस्य", "चौंकाने", "खतरनाक", "साजिश",
            # Spanish
            "secreto", "muerte", "peligro", "giro", "nadie", "aterrador", "trampa",
            # Indonesian
            "rahasia", "terjebak", "mati", "mengerikan", "misteri", "tak terduga",
            # Arabic
            "سر", "موت", "كارثة", "صدمة", "غامض", "مرعب", "خيانة"
        ]

        matches = [kw for kw in trigger_keywords if kw in first_passage]
        score += min(25, len(matches) * 7)

        # Sentence brevity bonus (punchy sentences retain attention)
        sentences = [s.strip() for s in re.split(r'[.!?۔\n]+', first_passage) if len(s.strip()) > 3]
        if len(sentences) >= 2:
            score += 8

        final_score = min(98, max(50, score))
        rating = "Viral Platinum 🔥" if final_score >= 88 else ("High Retention ⚡" if final_score >= 75 else "Moderate Pacing 📈")

        return {
            "score": final_score,
            "rating": rating,
            "analysis": f"Detected {len(matches)} curiosity triggers in the opening hook. High retention expected."
        }

    @staticmethod
    def strip_production_tags(t: str) -> str:
        """
        Aggressively strips director tags, metadata, timestamps, and SFX markers:
        - [SCENE: MM:SS - MM:SS] or SCENE: MM:SS - MM:SS]
        - [VOICEOVER] or VOICEOVER]
        - [SFX: ...]
        - [DIALOGUE_REF: ...]
        - PART or ===PART N===
        - isolated brackets, asterisks, hashes
        Returns clean, purely vocal narrative dialogue.
        """
        if not t:
            return ""
        # 1. Bracketed tags (LTR and RTL reversed brackets)
        c = re.sub(r'[\[\]]\s*(?:SCENE|TIME|VOICEOVER|SFX|DIALOGUE_REF|PART|BANNER)\b[^\[\]\n]*[\[\]]', ' ', t, flags=re.IGNORECASE)
        # 2. Standalone tags at line start or followed by colon/bracket
        c = re.sub(r'^\s*(?:SCENE|TIME|VOICEOVER|SFX|DIALOGUE_REF|BANNER)\b[^:\n]*[:\n]?', ' ', c, flags=re.MULTILINE | re.IGNORECASE)
        # 3. Explicit tag patterns with colons or closing brackets (e.g. [SFX: HEARTBEAT, VOICEOVER], SCENE: 01:00])
        c = re.sub(r'(?:\[|\b)(?:SCENE|TIME|VOICEOVER|SFX|DIALOGUE_REF|BANNER)\s*:[^\]\n]*\]?', ' ', c, flags=re.IGNORECASE)
        c = re.sub(r'\b(?:SCENE|VOICEOVER|SFX|DIALOGUE_REF|BANNER)\b\s*\]', ' ', c, flags=re.IGNORECASE)
        # 4. Multi-part headings (e.g. === PART 1 ===, [PART 1], PART 1:)
        c = re.sub(r'(?:===|\[|\b)PART\s*\d+\b[^=\]\n]*(?:===|\]|:)?', ' ', c, flags=re.IGNORECASE)
        # 5. Any remaining bracketed content
        c = re.sub(r'\[.*?\]', ' ', c)
        # 6. Standalone lines of keywords or horizontal rules
        c = re.sub(r'^\s*(?:SCENE|TIME|VOICEOVER|SFX|BANNER|DIALOGUE_REF|DIALOGUE)\b.*$', '', c, flags=re.MULTILINE | re.IGNORECASE)
        c = re.sub(r'^\s*[=\-~_]{2,}.*$', '', c, flags=re.MULTILINE)
        # 7. Strip isolated brackets, asterisks, hashes
        c = re.sub(r'[\[\]\*#_~`]', ' ', c)
        c = re.sub(r'^\d+[\.\)]\s*', '', c, flags=re.MULTILINE)
        c = re.sub(r'^(?:dialogue_ref|dialogue)\s*:\s*.*', '', c, flags=re.IGNORECASE | re.MULTILINE)
        c = re.sub(r'^(?:voiceover|narration)\s*:\s*', '', c, flags=re.IGNORECASE | re.MULTILINE)
        c = re.sub(r'[ \t]+', ' ', c)
        return c.strip()

    @staticmethod
    def parse_storyboard(raw_script: str) -> Tuple[str, List[Tuple[float, float]], List[str]]:
        """
        Extracts clean voiceover narration text, scene timestamp cuts (e.g. 01:23 - 02:45),
        and per-scene subtitle lines from the generated or edited storyboard.
        """
        if not raw_script:
            return "", [], []

        def time_to_sec(t: str) -> float:
            parts = t.strip().split(':')
            try:
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                pass
            return 0.0

        # 1. Parse timestamps
        ranges = []
        range_matches = re.findall(r'(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—to]+\s*(\d{1,2}:\d{2}(?::\d{2})?)', raw_script)
        for rm in range_matches:
            s_sec = time_to_sec(rm[0])
            e_sec = time_to_sec(rm[1])
            if e_sec > s_sec:
                ranges.append((s_sec, e_sec))

        # 2. Extract clean voiceover blocks
        vo_blocks = re.findall(r'(?:\[VOICEOVER\]|\bVOICEOVER\b\]?)\s*(.*?)(?=(?:\[(?:SCENE|TIME)|SCENE\s*\d*:|===PART|📝|\Z))', raw_script, flags=re.DOTALL | re.IGNORECASE)
        clean_blocks = []
        scene_subs = []

        if vo_blocks:
            for b in vo_blocks:
                cleaned_b = ScriptEngine.strip_production_tags(b)
                if len(cleaned_b) > 3:
                    clean_blocks.append(cleaned_b)
                    scene_subs.append(cleaned_b[:80])
            final_text = ' '.join(clean_blocks)
        else:
            # Strip tags and markdown
            clean_lines = []
            for line in raw_script.splitlines():
                l = line.strip()
                if not l or l.startswith(('#', '📌', '🏷️', '📝', '---', '===', 'Option:')):
                    continue
                cl = ScriptEngine.strip_production_tags(l)
                if len(cl) > 3:
                    clean_lines.append(cl)
            final_text = ' '.join(clean_lines)

        final_text = re.sub(r'\s+', ' ', final_text).strip()
        if not scene_subs and final_text:
            sentences = [s.strip() for s in re.split(r'[.!?۔।\n]+', final_text) if len(s.strip()) > 5]
            scene_subs = [s[:80] for s in sentences]

        return final_text, ranges, scene_subs

    @staticmethod
    def calculate_roadmap_capacity(
        target_output_dur_mins: Optional[float] = None,
        source_duration_sec: float = 3600.0,
        total_cues: int = 100
    ) -> int:
        """
        Dynamically calculates target roadmap event capacity (Phase 3A).
        Balances output duration, source duration, and available cue density
        without hardcoded static constants.
        """
        if total_cues <= 0:
            return 0

        # Determine effective output duration in minutes
        if target_output_dur_mins is not None and target_output_dur_mins > 0:
            out_mins = float(target_output_dur_mins)
        else:
            # Derive reasonable compression ratio (approx 6:1 source-to-output, clamped)
            out_mins = max(3.0, min(float(source_duration_sec) / 360.0, 30.0))

        # Dynamic continuous scaling formula:
        # Monotonically increasing with output duration (Invariant 5)
        # Bounded between 1 and total_cues (Invariant 6)
        base_capacity = 14.0 + (out_mins ** 0.82) * 4.2
        target_cap = int(round(base_capacity))

        return max(1, min(total_cues, target_cap))

    @staticmethod
    def evaluate_cue_informativeness(cue_text: str) -> float:
        """
        Evaluates narrative informativeness and semantic action density of a cue (Phase 3A Step 7).
        Prevents raw character length from favoring rambling filler over concise plot revelations.
        """
        if not cue_text:
            return 0.0

        clean = re.sub(r'<[^>]+>', '', str(cue_text)).strip()
        if not clean:
            return 0.0

        # Audio / noise tag penalty
        if clean.startswith(('[', '(')) and any(tag in clean.upper() for tag in ['SFX', 'MUSIC', 'APPLAUSE', 'LAUGHTER', 'INARTICULATE']):
            return -10.0

        STOP_WORDS = {
            'a', 'an', 'the', 'is', 'in', 'it', 'of', 'to', 'and', 'or',
            'on', 'at', 'by', 'as', 'be', 'we', 'he', 'she', 'his', 'her',
            'was', 'are', 'this', 'that', 'with', 'for', 'from', 'not',
            'but', 'so', 'if', 'its', 'into', 'up', 'out', 'now', 'then',
            'were', 'have', 'has', 'had', 'would', 'could', 'will', 'do',
            'i', 'you', 'my', 'your', 'me', 'him', 'them', 'they', 'what',
            'who', 'how', 'why', 'when', 'where', 'there', 'here', 'just',
            'about', 'like', 'well', 'um', 'uh', 'yeah', 'okay', 'oh', 'no', 'yes'
        }

        NARRATIVE_KEYWORDS = {
            'kill', 'killer', 'murder', 'murderer', 'dead', 'death', 'die', 'died', 'poison', 'poisoned',
            'victim', 'suspect', 'police', 'detective', 'gun', 'shoot', 'shot', 'weapon', 'blood',
            'secret', 'truth', 'discover', 'discovered', 'reveal', 'revealed', 'hide', 'evidence', 'proof',
            'lie', 'lied', 'escape', 'escaped', 'trap', 'trapped', 'danger', 'bomb', 'destroy', 'destroyed',
            'save', 'saved', 'help', 'betray', 'betrayed', 'confess', 'confession', 'arrest', 'arrested',
            'stole', 'steal', 'brother', 'sister', 'father', 'mother', 'daughter', 'son', 'husband', 'wife',
            'money', 'end', 'final', 'goodbye', 'love', 'hate', 'promise', 'trust', 'run', 'found'
        }

        words = re.findall(r'\w{2,}', clean.lower(), flags=re.UNICODE)
        if not words:
            return 0.0

        info_words = [w for w in words if w not in STOP_WORDS and not w.isdigit()]
        unique_info = set(info_words)
        kw_count = sum(1 for w in unique_info if w in NARRATIVE_KEYWORDS)
        repetition = max(0, len(words) - len(set(words)))
        kw_density = (kw_count / len(unique_info)) if unique_info else 0.0

        sc = (len(unique_info) * 1.5) + (kw_count * 4.5) + (kw_density * 6.0) - (repetition * 1.5)
        if len(clean) < 6:
            sc -= 2.0

        return round(sc, 2)

    @staticmethod
    def extract_balanced_transcript_sample(subs_text: str, max_chars: int = 4000) -> str:
        """
        Extracts a balanced beginning-middle-ending sample of raw unparsed transcript text
        to prevent Act 2/3 and ending erasure when structured cues cannot be parsed (Phase 3A Step 8).
        """
        if not subs_text or len(subs_text) <= max_chars:
            return subs_text or ""
        part_budget = max(100, (max_chars - 100) // 3)
        p1 = subs_text[:part_budget].rstrip()
        mid_idx = len(subs_text) // 2
        p2 = subs_text[mid_idx - part_budget // 2 : mid_idx + part_budget // 2].strip()
        p3 = subs_text[-part_budget:].lstrip()
        return f"{p1}\n\n[... Narrative Progression ...]\n\n{p2}\n\n[... Climax & Resolution ...]\n\n{p3}"

    @staticmethod
    def _parse_source_cues(
        subs_text: str,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Parses raw transcript or dialogue timeline into chronological cue objects.
        Guarantees non-destructive Unicode preservation across Urdu, Hindi, Arabic, and all languages.
        """
        from app.services.video_engine import VideoEngine

        cues: List[Dict[str, Any]] = []
        if dialogue_timeline and len(dialogue_timeline) > 0:
            cues = [dict(c) for c in dialogue_timeline if c.get("text", "").strip()]
        else:
            try:
                res = VideoEngine.parse_raw_transcript_text(subs_text or "")
                cues = res.get("dialogue_timeline", [])
            except Exception:
                cues = []

            if not cues and subs_text:
                ts_regex = re.compile(r'\[?((?:\d{1,2}:)?\d{1,3}:\d{2})\]?\s*(.*)')
                for line in subs_text.splitlines():
                    l = line.strip()
                    if not l:
                        continue
                    m = ts_regex.match(l)
                    if m:
                        ts_str = m.group(1)
                        txt = m.group(2).strip()
                        parts = ts_str.split(':')
                        sec = 0.0
                        if len(parts) == 2:
                            sec = int(parts[0]) * 60.0 + float(parts[1])
                        elif len(parts) == 3:
                            sec = int(parts[0]) * 3600.0 + int(parts[1]) * 60.0 + float(parts[2])
                        if txt:
                            cues.append({"start": sec, "end": sec + 5.0, "text": txt})

        cues.sort(key=lambda x: float(x.get("start", 0.0)))
        return cues

    @staticmethod
    def select_roadmap_cues(
        subs_text: str,
        total_movie_dur: float = 3600.0,
        max_points: Optional[int] = None,
        target_output_dur_mins: Optional[int] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Extracts selected representative roadmap cues and all source cues across 5 narrative acts (Phase 3A/3B).
        Returns (selected_cues, all_source_cues).
        """
        if not subs_text and not dialogue_timeline:
            return [], []

        cues = ScriptEngine._parse_source_cues(subs_text, dialogue_timeline)
        if not cues:
            return [], []

        # Determine target capacity (Phase 3A Step 4)
        if max_points is not None and max_points > 0:
            target_capacity = min(len(cues), int(max_points))
        else:
            target_capacity = ScriptEngine.calculate_roadmap_capacity(
                target_output_dur_mins=target_output_dur_mins,
                source_duration_sec=total_movie_dur,
                total_cues=len(cues)
            )

        # Timeline bounds (Phase 3A Step 5: Preserve full movie including climax and resolution)
        first_cue_s = float(cues[0]["start"])
        last_cue_s = float(cues[-1]["start"])
        effective_dur = max(float(total_movie_dur), last_cue_s + 10.0)
        start_bound = max(0.0, min(first_cue_s, effective_dur * 0.02))
        end_bound = min(effective_dur, max(last_cue_s + 5.0, effective_dur * 0.98))
        if end_bound <= start_bound:
            start_bound = first_cue_s
            end_bound = last_cue_s + 5.0
        story_span = max(1.0, end_bound - start_bound)

        # 5 Acts definitions matching partition_timeline
        acts_def = [
            ("Act 1", start_bound, start_bound + 0.20 * story_span, 0.20),
            ("Act 2A", start_bound + 0.20 * story_span, start_bound + 0.45 * story_span, 0.25),
            ("Act 2B", start_bound + 0.45 * story_span, start_bound + 0.70 * story_span, 0.25),
            ("Act 3", start_bound + 0.70 * story_span, start_bound + 0.90 * story_span, 0.20),
            ("Epilogue", start_bound + 0.90 * story_span, end_bound + 1.0, 0.10),
        ]

        act_cues: List[List[Dict[str, Any]]] = [[] for _ in range(5)]
        for c in cues:
            s = float(c["start"])
            placed = False
            for i, (_, a_start, a_end, _) in enumerate(acts_def):
                if a_start <= s < a_end or (i == 4 and s >= a_start):
                    act_cues[i].append(c)
                    placed = True
                    break
            if not placed:
                act_cues[-1].append(c)

        # Calculate act quotas
        quotas = [
            max(1 if len(act_cues[0]) > 0 else 0, int(round(target_capacity * 0.20))),
            max(1 if len(act_cues[1]) > 0 else 0, int(round(target_capacity * 0.25))),
            max(1 if len(act_cues[2]) > 0 else 0, int(round(target_capacity * 0.25))),
            max(1 if len(act_cues[3]) > 0 else 0, int(round(target_capacity * 0.20))),
            max(1 if len(act_cues[4]) > 0 else 0, target_capacity - sum([
                int(round(target_capacity * 0.20)),
                int(round(target_capacity * 0.25)),
                int(round(target_capacity * 0.25)),
                int(round(target_capacity * 0.20))
            ])),
        ]

        diff = sum(quotas) - target_capacity
        while diff != 0:
            if diff > 0:
                idx = max(range(5), key=lambda i: quotas[i] if quotas[i] > 1 else -1)
                quotas[idx] -= 1
                diff -= 1
            else:
                idx = max(range(5), key=lambda i: (len(act_cues[i]) - quotas[i], quotas[i]))
                quotas[idx] += 1
                diff += 1

        # Deficit reallocation for sparse acts
        deficit = 0
        for i in range(5):
            if len(act_cues[i]) < quotas[i]:
                deficit += quotas[i] - len(act_cues[i])
                quotas[i] = len(act_cues[i])

        while deficit > 0:
            surplus_acts = [i for i in range(5) if len(act_cues[i]) > quotas[i]]
            if not surplus_acts:
                break
            best_i = max(surplus_acts, key=lambda i: len(act_cues[i]) - quotas[i])
            quotas[best_i] += 1
            deficit -= 1

        # Select representative cues per act
        selected_cues: List[Dict[str, Any]] = []
        seen_starts = set()

        for i in range(5):
            q = quotas[i]
            cands = act_cues[i]
            act_name = acts_def[i][0]
            if q <= 0 or not cands:
                continue
            if len(cands) <= q:
                for c in cands:
                    k = round(float(c["start"]), 1)
                    if k not in seen_starts:
                        seen_starts.add(k)
                        c_copy = dict(c)
                        c_copy["act"] = act_name
                        selected_cues.append(c_copy)
                continue

            a_start = acts_def[i][1]
            a_end = acts_def[i][2]
            a_span = max(1.0, a_end - a_start)
            sub_step = a_span / float(q)

            chosen_indices = set()
            for j in range(q):
                sub_s = a_start + j * sub_step
                sub_e = sub_s + sub_step
                bucket = [(idx, c) for idx, c in enumerate(cands) if sub_s <= float(c["start"]) < sub_e and idx not in chosen_indices]
                if bucket:
                    best_idx, best_cue = max(bucket, key=lambda pair: ScriptEngine.evaluate_cue_informativeness(pair[1].get("text", "")))
                    chosen_indices.add(best_idx)
                    k = round(float(best_cue["start"]), 1)
                    if k not in seen_starts:
                        seen_starts.add(k)
                        c_copy = dict(best_cue)
                        c_copy["act"] = act_name
                        selected_cues.append(c_copy)
                else:
                    sub_mid = sub_s + sub_step / 2.0
                    unselected = [(idx, c) for idx, c in enumerate(cands) if idx not in chosen_indices]
                    if unselected:
                        best_idx, best_cue = min(unselected, key=lambda pair: abs(float(pair[1]["start"]) - sub_mid))
                        chosen_indices.add(best_idx)
                        k = round(float(best_cue["start"]), 1)
                        if k not in seen_starts:
                            seen_starts.add(k)
                            c_copy = dict(best_cue)
                            c_copy["act"] = act_name
                            selected_cues.append(c_copy)

        selected_cues.sort(key=lambda x: float(x["start"]))
        return selected_cues, cues

    @staticmethod
    def compress_transcript_to_roadmap(
        subs_text: str,
        total_movie_dur: float = 3600.0,
        max_points: Optional[int] = None,
        target_output_dur_mins: Optional[int] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """
        Compresses source transcripts into a chronological, act-aware narrative roadmap (Phase 3A).
        Guarantees full story arc coverage across all 5 narrative acts (beginning, midpoint, climax, ending)
        with duration-aware density and deterministic, informativeness-driven cue selection.
        """
        if not subs_text and not dialogue_timeline:
            return ""

        selected_cues, all_cues = ScriptEngine.select_roadmap_cues(
            subs_text=subs_text,
            total_movie_dur=total_movie_dur,
            max_points=max_points,
            target_output_dur_mins=target_output_dur_mins,
            dialogue_timeline=dialogue_timeline
        )

        if not all_cues:
            return ScriptEngine.extract_balanced_transcript_sample(subs_text, max_chars=3500)

        lines = []
        for c in selected_cues:
            sec = float(c["start"])
            m = int(sec // 60)
            s = int(sec % 60)
            text_snippet = c.get("text", "").replace("\n", " ").strip()
            text_snippet = re.sub(r'<[^>]+>', '', text_snippet)
            if len(text_snippet) > 85:
                text_snippet = text_snippet[:82] + "..."
            lines.append(f"[{m:02d}:{s:02d}] {text_snippet}")

        return "\n".join(lines)

    @staticmethod
    def explain_roadmap_coverage(
        subs_text: str,
        total_movie_dur: float = 3600.0,
        target_output_dur_mins: Optional[int] = None,
        max_points: Optional[int] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Quality and auditing introspection helper for Phase 3A narrative roadmap coverage.
        Returns exact metrics for source event count, retained counts, act distributions, and boundaries.
        """
        cues = ScriptEngine._parse_source_cues(subs_text, dialogue_timeline)
        total_source_events = len(cues)
        roadmap_str = ScriptEngine.compress_transcript_to_roadmap(
            subs_text=subs_text,
            total_movie_dur=total_movie_dur,
            max_points=max_points,
            target_output_dur_mins=target_output_dur_mins,
            dialogue_timeline=dialogue_timeline
        )
        lines = [l for l in roadmap_str.strip().splitlines() if l.strip().startswith("[")]

        def parse_ts_line(line_str: str) -> Optional[float]:
            m = re.search(r'\[((?:\d{1,2}:)?\d{1,3}):(\d{2})\]', line_str)
            if not m:
                return None
            prefix = m.group(1)
            sec_s = float(m.group(2))
            if ":" in prefix:
                h, mins = prefix.split(":")
                return int(h) * 3600.0 + int(mins) * 60.0 + sec_s
            else:
                return int(prefix) * 60.0 + sec_s

        earliest_ts = None
        latest_ts = None
        if lines:
            earliest_ts = parse_ts_line(lines[0])
            latest_ts = parse_ts_line(lines[-1])

        effective_dur = float(total_movie_dur)
        act_counts = {"act1": 0, "act2a": 0, "act2b": 0, "act3": 0, "epilogue": 0}
        for l in lines:
            s = parse_ts_line(l)
            if s is not None:
                ratio = s / max(1.0, effective_dur)
                if ratio < 0.20:
                    act_counts["act1"] += 1
                elif ratio < 0.45:
                    act_counts["act2a"] += 1
                elif ratio < 0.70:
                    act_counts["act2b"] += 1
                elif ratio < 0.90:
                    act_counts["act3"] += 1
                else:
                    act_counts["epilogue"] += 1

        return {
            "source_event_count": total_source_events,
            "retained_event_count": len(lines),
            "retention_ratio": round(len(lines) / max(1, total_source_events), 4),
            "earliest_timestamp": earliest_ts,
            "latest_timestamp": latest_ts,
            "act_breakdown": act_counts,
            "beginning_coverage": act_counts["act1"] > 0,
            "middle_coverage": (act_counts["act2a"] + act_counts["act2b"]) > 0,
            "climax_coverage": act_counts["act3"] > 0,
            "ending_coverage": act_counts["epilogue"] > 0,
            "roadmap_lines_count": len(lines),
        }

    # =========================================================================
    # PHASE 3B — EVIDENCE PACKETS & GROUNDED STORY PLANNING
    # =========================================================================

    @staticmethod
    def build_evidence_packets(
        subs_text: str = "",
        total_movie_dur: float = 3600.0,
        target_output_dur_mins: Optional[int] = None,
        max_points: Optional[int] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        selected_cues: Optional[List[Dict[str, Any]]] = None,
        all_source_cues: Optional[List[Dict[str, Any]]] = None,
        context_window_sec: float = 45.0,
        max_context_cues: int = 2
    ) -> List[Dict[str, Any]]:
        """
        Builds deterministic evidence packets from selected roadmap cues and original source dialogue (Phase 3B Step 3).
        Each packet binds a roadmap beat directly to verbatim source text, bounded local context, and narrative act.
        """
        if selected_cues is None or all_source_cues is None:
            selected_cues, all_source_cues = ScriptEngine.select_roadmap_cues(
                subs_text=subs_text,
                total_movie_dur=total_movie_dur,
                max_points=max_points,
                target_output_dur_mins=target_output_dur_mins,
                dialogue_timeline=dialogue_timeline
            )

        if not selected_cues:
            return []

        packets: List[Dict[str, Any]] = []
        for idx, cue in enumerate(selected_cues):
            c_start = float(cue.get("start", 0.0))
            c_end = float(cue.get("end", c_start + 5.0))
            c_text = cue.get("text", "").strip()

            # Locate matching authoritative cue in all_source_cues
            matched_idx = None
            if all_source_cues:
                for s_i, sc in enumerate(all_source_cues):
                    if sc is cue or (abs(float(sc.get("start", 0.0)) - c_start) < 0.05 and sc.get("text", "").strip() == c_text):
                        matched_idx = s_i
                        break

            # Local bounded context extraction (Phase 3B Step 4)
            context_before_list = []
            context_after_list = []
            is_resolved = (matched_idx is not None)
            confidence = 1.0 if is_resolved else 0.0

            if matched_idx is not None and all_source_cues:
                start_lookback = max(0, matched_idx - max_context_cues)
                for k in range(start_lookback, matched_idx):
                    prior_cue = all_source_cues[k]
                    if c_start - float(prior_cue.get("start", 0.0)) <= context_window_sec:
                        context_before_list.append(prior_cue.get("text", "").replace("\n", " ").strip())

                end_lookahead = min(len(all_source_cues), matched_idx + 1 + max_context_cues)
                for k in range(matched_idx + 1, end_lookahead):
                    next_cue = all_source_cues[k]
                    if float(next_cue.get("start", 0.0)) - c_start <= context_window_sec:
                        context_after_list.append(next_cue.get("text", "").replace("\n", " ").strip())

            # Determine act assignment
            act = cue.get("act", "")
            if not act:
                ratio = c_start / max(1.0, float(total_movie_dur))
                if ratio < 0.20:
                    act = "Act 1"
                elif ratio < 0.45:
                    act = "Act 2A"
                elif ratio < 0.70:
                    act = "Act 2B"
                elif ratio < 0.90:
                    act = "Act 3"
                else:
                    act = "Epilogue"

            packet_obj = EvidencePacket(
                packet_id=f"EP-{idx+1:03d}",
                movie_start=c_start,
                movie_end=c_end,
                source_text=c_text,
                act=act,
                sequence_index=idx,
                cue_index=matched_idx,
                context_before=" | ".join(context_before_list) if context_before_list else "",
                context_after=" | ".join(context_after_list) if context_after_list else "",
                confidence=confidence,
                is_resolved=is_resolved,
                metadata={"source_duration": round(c_end - c_start, 2)}
            )
            packets.append(packet_obj.to_dict())

        return packets

    @staticmethod
    def _extract_grounded_entities(text: str) -> List[str]:
        """Extracts candidate character names, numbers, or key proper entities strictly from text."""
        if not text:
            return []
        quoted = re.findall(r'["\']([^"\']{2,30})["\']', text)
        codes = re.findall(r'\b(?:\d{2,6}|[A-Z]{2,}\d*)\b', text)
        COMMON_STARTERS = {
            'The', 'A', 'An', 'In', 'On', 'At', 'By', 'For', 'With', 'About',
            'He', 'She', 'They', 'It', 'We', 'You', 'I', 'This', 'That', 'These',
            'Those', 'When', 'Where', 'Why', 'How', 'What', 'Who', 'Then', 'Now',
            'After', 'Before', 'Meanwhile', 'Suddenly', 'However', 'Although', 'If',
            'Because', 'Since', 'While', 'As', 'So', 'Just', 'Well', 'Anyway'
        }
        words = re.findall(r'\b[A-Z][a-z]{2,}\b', text)
        named = [w for w in words if w not in COMMON_STARTERS]
        combined = list(dict.fromkeys(named + quoted + codes))
        return combined[:5]

    @staticmethod
    def create_grounded_story_plan(
        evidence_packets: List[Dict[str, Any]],
        target_duration_mins: int = 5,
        genre: str = "movie_recap",
        target_lang: str = "en",
        voice_speed: str = "fast"
    ) -> List[Dict[str, Any]]:
        """
        Creates a structured, chronological story plan from evidence packets (Phase 3B Stage 1).
        Enforces proportional word-budget distribution across the 5 narrative acts without inventing facts.
        """
        if not evidence_packets:
            return []

        target_words = ScriptEngine.calculate_target_words(target_duration_mins, voice_speed, target_lang)

        act_weight_map = {
            "Act 1": 0.20,
            "Act 2A": 0.25,
            "Act 2B": 0.25,
            "Act 3": 0.20,
            "Epilogue": 0.10
        }

        act_packets: Dict[str, List[Dict[str, Any]]] = {
            "Act 1": [],
            "Act 2A": [],
            "Act 2B": [],
            "Act 3": [],
            "Epilogue": []
        }
        for p in evidence_packets:
            a = p.get("act", "Act 1")
            if a not in act_packets:
                act_packets[a] = []
            act_packets[a].append(p)

        plan_items: List[Dict[str, Any]] = []
        step_counter = 1

        for act_name, p_list in act_packets.items():
            if not p_list:
                continue
            act_budget = int(round(target_words * act_weight_map.get(act_name, 0.20)))
            per_item_budget = max(20, act_budget // len(p_list))

            for idx_in_act, packet in enumerate(p_list):
                if act_name == "Act 1":
                    purpose = "opening_hook" if idx_in_act == 0 else "inciting_setup"
                elif act_name == "Act 2A":
                    purpose = "progressive_complication"
                elif act_name == "Act 2B":
                    purpose = "midpoint_escalation"
                elif act_name == "Act 3":
                    purpose = "climax_confrontation"
                else:
                    purpose = "final_resolution"

                entities = ScriptEngine._extract_grounded_entities(packet.get("source_text", ""))
                core_event = packet.get("source_text", "").replace("\n", " ").strip()
                if len(core_event) > 100:
                    core_event = core_event[:97] + "..."

                item = StoryPlanItem(
                    step=step_counter,
                    source_timestamp=float(packet.get("movie_start", 0.0)),
                    act=act_name,
                    evidence_ref=packet.get("packet_id", f"EP-{step_counter:03d}"),
                    core_event=core_event,
                    entities=entities,
                    narration_purpose=purpose,
                    budget_words=per_item_budget,
                    is_inferred=False
                )
                plan_items.append(item.to_dict())
                step_counter += 1

        return plan_items

    @staticmethod
    def validate_story_plan(
        plan: List[Dict[str, Any]],
        evidence_packets: List[Dict[str, Any]]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Validates story plan integrity against evidence packets (Phase 3B Step 10).
        Enforces step sequencing, chronological non-decreasing timestamps, reference existence,
        and ensures no unresolved evidence is passed as verified fact.
        """
        if not plan:
            return False, "Plan is empty.", {"total_plan_items": 0, "error": "empty_plan"}

        packet_map = {p["packet_id"]: p for p in evidence_packets} if evidence_packets else {}
        seen_refs = set()
        prev_ts = -1.0
        prev_step = 0

        for idx, item in enumerate(plan):
            step = item.get("step")
            if step is None or step <= prev_step:
                return False, f"Plan sequencing error at index {idx}: step {step} <= previous {prev_step}", {"error": "sequence_error"}
            prev_step = step

            ts = item.get("source_timestamp")
            if ts is None or float(ts) < prev_ts:
                return False, f"Plan chronology violation at step {step}: timestamp {ts} < previous {prev_ts}", {"error": "chronology_error"}
            prev_ts = float(ts)

            ref = item.get("evidence_ref")
            if not ref or ref not in packet_map:
                return False, f"Plan evidence reference error at step {step}: packet '{ref}' not found in evidence packets", {"error": "invalid_evidence_ref"}

            if ref in seen_refs:
                return False, f"Plan duplicate reference error at step {step}: packet '{ref}' reused", {"error": "duplicate_evidence_ref"}
            seen_refs.add(ref)

            pkt = packet_map[ref]
            if not pkt.get("is_resolved", True):
                return False, f"Plan references unresolved evidence at step {step}: packet '{ref}' has no source match", {"error": "unresolved_evidence"}

        metrics = {
            "total_plan_items": len(plan),
            "total_evidence_packets": len(evidence_packets),
            "covered_packets_count": len(seen_refs),
            "coverage_ratio": round(len(seen_refs) / max(1, len(evidence_packets)), 4),
            "is_chronological": True,
            "is_sequenced": True,
            "valid_references": True
        }
        return True, "Plan passed all grounding integrity checks.", metrics

    @staticmethod
    def format_evidence_packets_for_prompt(
        packets: List[Dict[str, Any]],
        max_packets: int = 50
    ) -> str:
        """Formats evidence packets for inclusion in LLM prompt blueprints (Phase 3B Stage 2)."""
        lines = []
        for p in packets[:max_packets]:
            sec = float(p.get("movie_start", 0.0))
            m = int(sec // 60)
            s = int(sec % 60)
            txt = p.get("source_text", "").replace("\n", " ").strip()
            if len(txt) > 85:
                txt = txt[:82] + "..."
            line = f"[{p.get('packet_id', 'EP-???')}] [{m:02d}:{s:02d}] ({p.get('act', 'Act')}) Source: \"{txt}\""
            cb = p.get("context_before", "").strip()
            ca = p.get("context_after", "").strip()
            if cb:
                if len(cb) > 50:
                    cb = cb[:47] + "..."
                line += f" | Preceding: \"{cb}\""
            if ca:
                if len(ca) > 50:
                    ca = ca[:47] + "..."
                line += f" | Following: \"{ca}\""
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def format_story_plan_for_prompt(
        plan: List[Dict[str, Any]],
        max_items: int = 50
    ) -> str:
        """Formats story plan items for inclusion in LLM prompt blueprints (Phase 3B Stage 2)."""
        lines = []
        for item in plan[:max_items]:
            sec = float(item.get("source_timestamp", 0.0))
            m = int(sec // 60)
            s = int(sec % 60)
            ents = ", ".join(item.get("entities", [])) if item.get("entities") else "None"
            ev = item.get("core_event", "").replace("\n", " ").strip()
            if len(ev) > 85:
                ev = ev[:82] + "..."
            line = f"- Step {item.get('step')} [{m:02d}:{s:02d}] ({item.get('act')}, Ref: {item.get('evidence_ref')}, Budget: ~{item.get('budget_words')} words, Purpose: {item.get('narration_purpose')}): {ev} (Entities: {ents})"
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def build_plan_generation_prompt(
        evidence_packets: List[Dict[str, Any]],
        title: str = "",
        genre: str = "movie_recap",
        target_lang: str = "en",
        duration_mins: int = 5
    ) -> str:
        """Builds Stage A prompt for generating a structured story plan from evidence packets."""
        packets_str = ScriptEngine.format_evidence_packets_for_prompt(evidence_packets)
        return f"""You are an elite narrative architect. Construct a grounded story plan for '{title}' ({genre}, {duration_mins}m).
EVIDENCE PACKETS:
{packets_str}

STRICT GROUNDING RULES:
1. ONLY use characters, events, and actions supported by the evidence packets above.
2. DO NOT invent characters, relationships, causes, or outcomes not found in the evidence.
3. Preserve the exact chronological order and timestamps of the evidence packets.
4. Output one plan step per evidence packet referencing its packet ID (e.g. EP-001)."""

    @staticmethod
    def parse_story_plan(
        plan_text: str,
        evidence_packets: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """Parses structured story plan output (JSON or formatted markdown) into plan item dicts."""
        if not plan_text:
            return []

        try:
            cleaned = plan_text.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned)
                cleaned = re.sub(r'\s*```$', '', cleaned)
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass

        items = []
        packet_map = {p["packet_id"]: p for p in evidence_packets} if evidence_packets else {}
        line_regex = re.compile(
            r'-\s*(?:Step\s*)?(\d+)\s*\[?((?:\d{1,2}:)?\d{1,3}:\d{2})?\]?\s*(?:\(([^,\)]+)(?:,\s*Ref:\s*([^,\)]+))?(?:,\s*Budget:\s*~?(\d+))?(?:,\s*Purpose:\s*([^,\)]+))?\))?:\s*(.*)',
            re.IGNORECASE
        )

        for line in plan_text.splitlines():
            l = line.strip()
            if not l.startswith("-"):
                continue
            m = line_regex.match(l)
            if m:
                step_num = int(m.group(1))
                ts_str = m.group(2) or "00:00"
                act_str = (m.group(3) or "").strip()
                ref_str = (m.group(4) or "").strip()
                budget_str = m.group(5) or "50"
                purpose_str = (m.group(6) or "progression").strip()
                event_str = (m.group(7) or "").strip()

                parts = ts_str.split(':')
                sec = 0.0
                if len(parts) == 2:
                    sec = int(parts[0]) * 60.0 + float(parts[1])
                elif len(parts) == 3:
                    sec = int(parts[0]) * 3600.0 + int(parts[1]) * 60.0 + float(parts[2])

                if not ref_str and evidence_packets and step_num <= len(evidence_packets):
                    ref_str = evidence_packets[step_num - 1].get("packet_id", f"EP-{step_num:03d}")

                if ref_str in packet_map:
                    pkt = packet_map[ref_str]
                    sec = float(pkt.get("movie_start", sec))
                    if not act_str:
                        act_str = pkt.get("act", "Act 1")

                items.append({
                    "step": step_num,
                    "source_timestamp": sec,
                    "act": act_str or "Act 1",
                    "evidence_ref": ref_str or f"EP-{step_num:03d}",
                    "core_event": event_str,
                    "entities": ScriptEngine._extract_grounded_entities(event_str),
                    "narration_purpose": purpose_str or "progression",
                    "budget_words": int(budget_str),
                    "is_inferred": False
                })

        return items

    @staticmethod
    def explain_script_traceability(
        script_text: str,
        story_plan: List[Dict[str, Any]],
        evidence_packets: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Introspection helper tracing each generated scene block back through the Story Plan to Evidence Packets (Phase 3B Step 9).
        Verifies internal grounding chain: SceneBlock -> StoryPlanItem -> EvidencePacket -> SourceCue.
        """
        if not script_text or not story_plan or not evidence_packets:
            return {
                "total_scenes": 0,
                "total_plan_items": len(story_plan) if story_plan else 0,
                "total_evidence_packets": len(evidence_packets) if evidence_packets else 0,
                "grounding_ratio": 0.0,
                "traceability_chain": []
            }

        blocks = ScriptEngine.parse_storyboard_blocks(script_text)
        packet_map = {p["packet_id"]: p for p in evidence_packets}

        chain = []
        grounded_count = 0

        for s_idx, block in enumerate(blocks):
            b_start = float(block.movie_start)
            b_text = block.narration_text.lower()

            matched_plan = min(story_plan, key=lambda it: abs(float(it.get("source_timestamp", 0.0)) - b_start))
            ref = matched_plan.get("evidence_ref")
            matched_packet = packet_map.get(ref, {})

            p_start = float(matched_packet.get("movie_start", matched_plan.get("source_timestamp", 0.0)))
            time_dist = abs(b_start - p_start)

            p_words = set(re.findall(r'\w{3,}', matched_packet.get("source_text", "").lower(), flags=re.UNICODE))
            b_words = set(re.findall(r'\w{3,}', b_text, flags=re.UNICODE))
            overlap = len(p_words & b_words)

            is_grounded = (time_dist <= 120.0 or overlap > 0)
            if is_grounded:
                grounded_count += 1

            chain.append({
                "scene_index": s_idx + 1,
                "scene_start": b_start,
                "narration_snippet": block.narration_text[:60],
                "matched_plan_step": matched_plan.get("step"),
                "matched_evidence_ref": ref,
                "source_timestamp": p_start,
                "source_text_snippet": matched_packet.get("source_text", "")[:60],
                "time_distance_sec": round(time_dist, 1),
                "token_overlap_count": overlap,
                "is_grounded": is_grounded
            })

        ratio = grounded_count / max(1, len(blocks))
        return {
            "total_scenes": len(blocks),
            "total_plan_items": len(story_plan),
            "total_evidence_packets": len(evidence_packets),
            "grounded_scenes_count": grounded_count,
            "grounding_ratio": round(ratio, 4),
            "traceability_chain": chain
        }

    # =========================================================================
    # PHASE 6F: SOURCE-BOUND DIALOGUE REFERENCE INTEGRITY & PROVENANCE
    # =========================================================================

    @staticmethod
    def normalize_dialogue_text(s: str) -> str:
        """
        Phase 6F: Normalizes dialogue text to tolerate harmless casing, whitespace,
        punctuation, contraction, and Unicode differences without changing semantic content.
        """
        if not s:
            return ""
        norm = unicodedata.normalize("NFKC", str(s))
        # Replace stylized quotation marks
        norm = re.sub(r'[""«»„“”‘’`]', '"', norm)
        # Common speech/dialogue speaker prefixes like 'Peter: "..."' or 'Hero: '
        norm = re.sub(r'^\s*[A-Za-z0-9_\s]{1,25}:\s*', '', norm)
        # Common contraction handling
        norm = re.sub(r"\b(\w+)n['\"]t\b", r"\1 not", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]re\b", r"\1 are", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]ve\b", r"\1 have", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]ll\b", r"\1 will", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]d\b", r"\1 would", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]m\b", r"\1 am", norm, flags=re.IGNORECASE)
        norm = re.sub(r"\b(\w+)['\"]s\b", r"\1s", norm, flags=re.IGNORECASE)
        # Strip punctuation characters including Urdu/Hindi punctuation
        norm = re.sub(r'[^\w\s]', ' ', norm, flags=re.UNICODE)
        return re.sub(r'\s+', ' ', norm.lower(), flags=re.UNICODE).strip()

    @staticmethod
    def score_ref_against_source(
        clean_ref: str,
        clean_src: str,
        precomputed_norm_ref: Optional[str] = None,
        precomputed_ref_toks: Optional[set] = None,
        precomputed_ref_sentences: Optional[List[str]] = None
    ) -> Optional[Tuple[float, str, str, str]]:
        """
        Phase 6F: Evaluates provenance match strength between candidate dialogue_ref and source text.
        Returns (score, match_type, norm_ref, norm_src) if valid, else None.
        Enforces that generic partial matches or single common words are never treated as valid source quotes.
        """
        if not clean_ref or not clean_src:
            return None

        clean_r = clean_ref.strip().strip('"\'“”‘’')
        clean_s = clean_src.strip().strip('"\'“”‘’')
        if not clean_r or not clean_s:
            return None

        if clean_r == clean_s:
            return (1000.0, "exact", clean_r, clean_s)

        norm_ref = precomputed_norm_ref if precomputed_norm_ref is not None else ScriptEngine.normalize_dialogue_text(clean_r)
        norm_src = ScriptEngine.normalize_dialogue_text(clean_s)

        if not norm_ref or not norm_src:
            return None

        if norm_ref == norm_src:
            return (900.0, "normalized_exact", norm_ref, norm_src)

        stop_words = {
            "a", "an", "the", "is", "in", "it", "of", "to", "and", "or",
            "on", "at", "by", "as", "be", "we", "he", "she", "his", "her",
            "was", "are", "this", "that", "with", "for", "from", "not",
            "but", "so", "if", "its", "into", "up", "out", "now", "then",
            "were", "have", "has", "had", "would", "could", "will", "do",
            "don", "didn", "doesn", "wasn", "weren", "haven", "hasn", "hadn",
            "won", "wouldn", "couldn", "shouldn", "isn", "aren", "ain",
            "ve", "re", "ll", "d", "m", "kind", "sort",
        }

        ref_toks = precomputed_ref_toks if precomputed_ref_toks is not None else {t for t in re.findall(r"\w{2,}", norm_ref.lower(), flags=re.UNICODE) if t not in stop_words and not t.isdigit()}
        src_toks = {t for t in re.findall(r"\w{2,}", norm_src.lower(), flags=re.UNICODE) if t not in stop_words and not t.isdigit()}

        # 1. Reference is a substantive contiguous excerpt of source cue (Case B & Section 9)
        if norm_ref in norm_src:
            is_substantive = any(len(t) >= 4 for t in ref_toks) or len(ref_toks) >= 2 or len(norm_ref) >= 8
            if is_substantive:
                return (500.0 + len(norm_ref), "source_contained_excerpt", norm_ref, norm_src)

        # 2. Multi-sentence reference where at least one substantive sentence is in source
        ref_sentences = precomputed_ref_sentences if precomputed_ref_sentences is not None else [s.strip() for s in re.split(r'[\.\!\?\;\n]+', clean_r) if s.strip()]
        if len(ref_sentences) > 1:
            best_sent_sc = 0.0
            for r_s in ref_sentences:
                n_rs = ScriptEngine.normalize_dialogue_text(r_s)
                t_rs = {t for t in re.findall(r"\w{2,}", n_rs.lower(), flags=re.UNICODE) if t not in stop_words and not t.isdigit()}
                if n_rs and n_rs in norm_src:
                    if len(n_rs) >= 8 or any(len(t) >= 4 for t in t_rs) or len(t_rs) >= 2:
                        best_sent_sc = max(best_sent_sc, 450.0 + len(n_rs))
            if best_sent_sc > 0.0:
                return (best_sent_sc, "source_contained_excerpt", norm_ref, norm_src)

        # 3. Source cue is a substantive excerpt of reference (e.g. multi-cue dialogue)
        # Must NOT match single generic words like "You." or "What?"
        if norm_src in norm_ref:
            distinctive_src = any(len(t) >= 5 for t in src_toks)
            if len(norm_src) >= 10 and (len(src_toks) >= 2 or distinctive_src):
                return (300.0 + len(norm_src), "source_contains_excerpt", norm_ref, norm_src)

        # 4. Multi-sentence source cue where at least one substantive sentence is in ref
        src_sentences = [s.strip() for s in re.split(r'[\.\!\?\;\n]+', clean_s) if s.strip()]
        if len(src_sentences) > 1:
            best_sent_sc = 0.0
            for c_s in src_sentences:
                n_cs = ScriptEngine.normalize_dialogue_text(c_s)
                t_cs = {t for t in re.findall(r"\w{2,}", n_cs.lower(), flags=re.UNICODE) if t not in stop_words and not t.isdigit()}
                if n_cs and n_cs in norm_ref:
                    if len(n_cs) >= 10 and (len(t_cs) >= 2 or any(len(t) >= 5 for t in t_cs)):
                        best_sent_sc = max(best_sent_sc, 250.0 + len(n_cs))
            if best_sent_sc > 0.0:
                return (best_sent_sc, "source_contains_excerpt", norm_ref, norm_src)

        return None

    @staticmethod
    def validate_dialogue_ref_provenance(
        dialogue_ref: Optional[str],
        evidence_packets: Optional[List[Any]] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        source_text: Optional[str] = None
    ) -> DialogueRefProvenance:
        """
        Phase 6F: Deterministic validation answering: Is this dialogue_ref actually source-bound?
        Distinguishes SOURCE_BOUND vs NOT_SOURCE_BOUND.
        Traceable to EvidencePacket -> source cue -> timestamp.
        """
        if not dialogue_ref or not str(dialogue_ref).strip():
            return DialogueRefProvenance(
                status="NOT_SOURCE_BOUND",
                is_source_bound=False,
                dialogue_ref=None,
                reason="empty_dialogue_ref"
            )

        clean_ref = str(dialogue_ref).strip().strip('"\'“”‘’')
        norm_ref = ScriptEngine.normalize_dialogue_text(clean_ref)

        has_packets = evidence_packets is not None and len(evidence_packets) > 0
        has_timeline = dialogue_timeline is not None and len(dialogue_timeline) > 0
        has_source_text = bool(source_text and str(source_text).strip())

        if not has_packets and not has_timeline and not has_source_text:
            return DialogueRefProvenance(
                status="NOT_SOURCE_BOUND",
                is_source_bound=False,
                dialogue_ref=None,
                normalized_ref=norm_ref,
                reason="no_source_evidence_available"
            )

        stop_words = {
            "a", "an", "the", "is", "in", "it", "of", "to", "and", "or",
            "on", "at", "by", "as", "be", "we", "he", "she", "his", "her",
            "was", "are", "this", "that", "with", "for", "from", "not",
            "but", "so", "if", "its", "into", "up", "out", "now", "then",
            "were", "have", "has", "had", "would", "could", "will", "do",
            "don", "didn", "doesn", "wasn", "weren", "haven", "hasn", "hadn",
            "won", "wouldn", "couldn", "shouldn", "isn", "aren", "ain",
            "ve", "re", "ll", "d", "m", "kind", "sort",
        }
        ref_toks = {t for t in re.findall(r"\w{2,}", norm_ref.lower(), flags=re.UNICODE) if t not in stop_words and not t.isdigit()}
        ref_sentences = [s.strip() for s in re.split(r'[\.\!\?\;\n]+', clean_ref) if s.strip()]

        best_match = None
        best_score = 0.0

        # 1. Preferred Source of Truth: Phase 3B EvidencePackets
        if has_packets:
            for pkt in evidence_packets:
                p_text = pkt.get("source_text", "") if isinstance(pkt, dict) else getattr(pkt, "source_text", "")
                p_id = pkt.get("packet_id", "") if isinstance(pkt, dict) else getattr(pkt, "packet_id", "")
                p_start = pkt.get("movie_start", 0.0) if isinstance(pkt, dict) else getattr(pkt, "movie_start", 0.0)
                p_cue_idx = pkt.get("cue_index", None) if isinstance(pkt, dict) else getattr(pkt, "cue_index", None)

                m = ScriptEngine.score_ref_against_source(
                    clean_ref,
                    p_text,
                    precomputed_norm_ref=norm_ref,
                    precomputed_ref_toks=ref_toks,
                    precomputed_ref_sentences=ref_sentences
                )
                if m and m[0] > best_score:
                    sc, m_type, n_ref, n_src = m
                    best_score = sc
                    best_match = DialogueRefProvenance(
                        status="SOURCE_BOUND",
                        is_source_bound=True,
                        dialogue_ref=clean_ref,
                        source_text=p_text,
                        evidence_ref=p_id,
                        cue_index=p_cue_idx,
                        source_timestamp=float(p_start),
                        match_type=m_type,
                        normalized_ref=n_ref,
                        normalized_source=n_src,
                        reason=f"matched_evidence_packet_{p_id}"
                    )

        # 2. Source cues in dialogue_timeline
        if has_timeline:
            for c_idx, cue in enumerate(dialogue_timeline):
                c_text = cue.get("text", "")
                c_start = float(cue.get("start", 0.0))

                m = ScriptEngine.score_ref_against_source(
                    clean_ref,
                    c_text,
                    precomputed_norm_ref=norm_ref,
                    precomputed_ref_toks=ref_toks,
                    precomputed_ref_sentences=ref_sentences
                )
                if m and m[0] > best_score:
                    sc, m_type, n_ref, n_src = m
                    best_score = sc
                    best_match = DialogueRefProvenance(
                        status="SOURCE_BOUND",
                        is_source_bound=True,
                        dialogue_ref=clean_ref,
                        source_text=c_text,
                        cue_index=c_idx,
                        source_timestamp=c_start,
                        match_type=m_type,
                        normalized_ref=n_ref,
                        normalized_source=n_src,
                        reason=f"matched_source_cue_{c_idx}"
                    )
                    if best_score >= 1000.0:
                        break

        # 3. Direct source_text string
        if has_source_text:
            m = ScriptEngine.score_ref_against_source(
                clean_ref,
                source_text,
                precomputed_norm_ref=norm_ref,
                precomputed_ref_toks=ref_toks,
                precomputed_ref_sentences=ref_sentences
            )
            if m and m[0] > best_score:
                sc, m_type, n_ref, n_src = m
                best_score = sc
                best_match = DialogueRefProvenance(
                    status="SOURCE_BOUND",
                    is_source_bound=True,
                    dialogue_ref=clean_ref,
                    source_text=source_text,
                    match_type=m_type,
                    normalized_ref=n_ref,
                    normalized_source=n_src,
                    reason="matched_source_text"
                )

        if best_match is not None:
            return best_match

        return DialogueRefProvenance(
            status="NOT_SOURCE_BOUND",
            is_source_bound=False,
            dialogue_ref=None,
            normalized_ref=norm_ref,
            reason="no_source_match_found"
        )

    @staticmethod
    def is_dialogue_ref_source_bound(
        dialogue_ref: Optional[str],
        evidence_packets: Optional[List[Any]] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        source_text: Optional[str] = None
    ) -> bool:
        """Convenience boolean check for source-bound provenance."""
        res = ScriptEngine.validate_dialogue_ref_provenance(
            dialogue_ref=dialogue_ref,
            evidence_packets=evidence_packets,
            dialogue_timeline=dialogue_timeline,
            source_text=source_text
        )
        return res.is_source_bound

    @staticmethod
    def validate_storyboard_chronology(
        blocks: List[Any],
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        evidence_packets: Optional[List[Any]] = None,
        story_plan: Optional[List[Any]] = None
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Phase 6G.3: Deterministic Storyboard Chronology Validation.
        Enforces that consecutive FINAL STORYBOARD scenes that both have an authoritative
        source timestamp must be non-decreasing: current_source_ts >= previous_source_ts.

        Contract & Invariants:
        1. Equal source timestamps are allowed (scenes covering the same scene/cue).
        2. Unknown/unresolved source timestamps (None) are allowed and skipped (CONTRACT 5).
        3. Arbitrary nominal [SCENE: MM:SS - MM:SS] timestamps are NEVER used as source chronology (CONTRACT 4).
        4. Authoritative source timestamps come from:
           - block.source_timestamp (if explicitly provided)
           - DialogueRefProvenance (when dialogue_ref is source-bound)
           - EvidencePacket (when evidence_ref is matched)
           - StoryPlan item (when story_step is matched)
        5. Does NOT reorder scenes; only accepts or rejects/flags candidates (CONTRACT 6).
        """
        if not blocks:
            return True, "No storyboard scenes to validate.", {"is_valid": True, "violations": []}

        packet_map = {}
        if evidence_packets:
            for p in evidence_packets:
                p_id = p.get("packet_id") if isinstance(p, dict) else getattr(p, "packet_id", None)
                if p_id:
                    packet_map[p_id] = p

        step_map = {}
        if story_plan:
            for s in story_plan:
                s_step = s.get("step") if isinstance(s, dict) else getattr(s, "step", None)
                if s_step is not None:
                    step_map[s_step] = s

        prev_ts: Optional[float] = None
        prev_idx: Optional[int] = None
        violations = []

        for idx, b in enumerate(blocks):
            # 1. Direct authoritative source_timestamp attribute / dict key
            b_ts = getattr(b, "source_timestamp", None) if hasattr(b, "source_timestamp") else b.get("source_timestamp")

            # 2. Derive from dialogue_ref provenance if not explicitly set
            b_ref = getattr(b, "dialogue_ref", None) if hasattr(b, "dialogue_ref") else b.get("dialogue_ref")
            if b_ts is None and b_ref:
                prov = ScriptEngine.validate_dialogue_ref_provenance(
                    dialogue_ref=b_ref,
                    evidence_packets=evidence_packets,
                    dialogue_timeline=dialogue_timeline
                )
                if prov.is_source_bound and prov.source_timestamp is not None:
                    b_ts = float(prov.source_timestamp)

            # 3. Derive from evidence_ref via evidence_packets if not set
            b_ev_ref = getattr(b, "evidence_ref", None) if hasattr(b, "evidence_ref") else b.get("evidence_ref")
            if b_ts is None and b_ev_ref and b_ev_ref in packet_map:
                pkt = packet_map[b_ev_ref]
                pkt_start = pkt.get("movie_start") if isinstance(pkt, dict) else getattr(pkt, "movie_start", None)
                if pkt_start is not None:
                    b_ts = float(pkt_start)

            # 4. Derive from story_step via story_plan if not set
            b_step = getattr(b, "story_step", None) if hasattr(b, "story_step") else b.get("story_step")
            if b_ts is None and b_step is not None and b_step in step_map:
                sp_item = step_map[b_step]
                sp_ts = sp_item.get("source_timestamp") if isinstance(sp_item, dict) else getattr(sp_item, "source_timestamp", None)
                if sp_ts is not None:
                    b_ts = float(sp_ts)

            # CONTRACT 5: Scenes without authoritative source grounding are skipped
            if b_ts is None:
                continue

            b_ts = float(b_ts)

            if prev_ts is not None and b_ts < prev_ts:
                v_entry = {
                    "scene_index": idx + 1,
                    "previous_scene_index": prev_idx + 1,
                    "current_source_timestamp": b_ts,
                    "previous_source_timestamp": prev_ts,
                    "dialogue_ref": b_ref,
                    "evidence_ref": b_ev_ref
                }
                violations.append(v_entry)
                err_msg = (
                    f"Chronology violation: previous scene (index {prev_idx + 1}) source_timestamp={prev_ts:.2f}, "
                    f"current scene (index {idx + 1}) source_timestamp={b_ts:.2f}, "
                    f"scene_index={idx + 1}, dialogue_ref={repr(b_ref) if b_ref else 'None'}. "
                    f"Source-grounded evidence order must be non-decreasing."
                )
                details = {
                    "is_valid": False,
                    "error": "chronology_violation",
                    "failure_type": "source_grounded_chronology_inversion",
                    "scene_index": idx + 1,
                    "previous_scene_index": prev_idx + 1,
                    "current_source_timestamp": b_ts,
                    "previous_source_timestamp": prev_ts,
                    "dialogue_ref": b_ref,
                    "evidence_ref": b_ev_ref,
                    "violations": violations
                }
                return False, err_msg, details

            prev_ts = b_ts
            prev_idx = idx

        return True, "Storyboard chronology validated successfully.", {
            "is_valid": True,
            "failure_type": None,
            "violations": []
        }

    MAX_CHRONOLOGY_RETRIES: int = 1

    @staticmethod
    def build_chronology_repair_prompt(
        current_script: str,
        chronology_details: Dict[str, Any],
        story_plan: Optional[List[Any]] = None,
        evidence_packets: Optional[List[Any]] = None,
        target_lang: str = "en"
    ) -> str:
        """
        Phase 6G.4: Builds a targeted, diagnostic chronology-repair prompt for exactly one regeneration attempt.
        Informs the LLM of the precise source timestamps and inverted scene index, with strict repair constraints.
        """
        prev_ts = float(chronology_details.get("previous_source_timestamp", 0.0))
        curr_ts = float(chronology_details.get("current_source_timestamp", 0.0))
        sc_idx = chronology_details.get("scene_index", "?")
        prev_idx = chronology_details.get("previous_scene_index", "?")
        d_ref = chronology_details.get("dialogue_ref")
        ev_ref = chronology_details.get("evidence_ref")

        inversion_info = (
            f"- Scene {prev_idx} authoritative source timestamp: {prev_ts:.2f}s\n"
            f"- Scene {sc_idx} authoritative source timestamp: {curr_ts:.2f}s (delta: {curr_ts - prev_ts:.2f}s)\n"
            f"- Inverted Scene Index: {sc_idx}\n"
            f"- Dialogue Reference: {repr(d_ref) if d_ref else 'None'}\n"
            f"- Evidence Reference: {repr(ev_ref) if ev_ref else 'None'}"
        )

        plan_str = ""
        if story_plan:
            plan_str = f"\nAUTHORITATIVE STORY PLAN SEQUENCE TO PRESERVE:\n{ScriptEngine.format_story_plan_for_prompt(story_plan)}\n"

        prompt = f"""CHRONOLOGICAL ORDER REPAIR REQUIRED:
The previously generated storyboard violates authoritative source chronology.
Specifically, a later source-grounded event was placed before an earlier source-grounded event.

DETECTED INVERSION:
{inversion_info}
{plan_str}
STRICT REPAIR INSTRUCTIONS:
1. Preserve the supplied StoryPlan sequence.
2. Do not move a later source-grounded event before an earlier source-grounded event.
3. Do not reverse source chronology.
4. Do not invent or rewrite dialogue references.
5. Preserve narrative content, dramatic style, and wording as much as possible.
6. Do not solve the problem by deleting scenes.
7. Do not solve the problem by changing nominal scene timestamps.
8. The final storyboard scene order must preserve the relative order of authoritative source-grounded evidence.

--- CURRENT SCRIPT TO REPAIR ---
{current_script}
--- END CURRENT SCRIPT ---

Emit the complete repaired storyboard with corrected scene ordering that respects source chronological order."""
        return prompt

    @staticmethod
    def generate_script_with_chronology_guard(
        generate_fn: Callable[[str], Optional[str]],
        initial_prompt: str,
        duration_mins: int,
        voice_speed: str,
        target_lang: str,
        source_video_duration_sec: float,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        evidence_packets: Optional[List[Any]] = None,
        story_plan: Optional[List[Any]] = None,
        expand_fn: Optional[Callable[[str, int], Optional[str]]] = None
    ) -> Tuple[Optional[str], bool, str, int, Optional[Dict[str, Any]]]:
        """
        Phase 6G.4: Controlled Single-Turn Chronology Failure Handling.
        Executes initial generation (Attempt 1). If a deterministic
        SOURCE-GROUNDED CHRONOLOGY INVERSION is detected, executes exactly
        one targeted repair regeneration (Attempt 2, MAX_CHRONOLOGY_RETRIES = 1).

        Returns:
            (script_text, is_valid, integrity_report, attempts, chronology_details)
        """
        attempts = 1
        raw_text = generate_fn(initial_prompt)
        if not raw_text or len(raw_text.strip()) <= 80:
            return None, False, "Generation attempt returned insufficient content.", attempts, None

        text = ScriptEngine.strip_code_and_developer_artifacts(raw_text)

        if expand_fn:
            clean_test, _, _ = ScriptEngine.parse_storyboard(text)
            actual_words = len(clean_test.split())
            expanded = expand_fn(text, actual_words)
            if expanded and len(expanded.split()) > actual_words:
                text = ScriptEngine.strip_code_and_developer_artifacts(expanded.strip())

        text = ScriptEngine.clamp_script_word_budget(
            text.strip(),
            target_duration_mins=duration_mins,
            target_lang=target_lang,
            voice_speed=voice_speed
        )

        is_valid, val_report, val_details = ScriptEngine.validate_script_integrity(
            script_text=text,
            source_duration_sec=source_video_duration_sec,
            target_duration_mins=duration_mins,
            target_lang=target_lang,
            voice_speed=voice_speed,
            dialogue_timeline=dialogue_timeline,
            evidence_packets=evidence_packets,
            story_plan=story_plan,
            return_details=True
        )

        if is_valid:
            return text, True, val_report, attempts, val_details

        failure_type = val_details.get("failure_type") if val_details else None

        # Only trigger retry for deterministic SOURCE-GROUNDED CHRONOLOGY INVERSION
        if failure_type == "source_grounded_chronology_inversion" and attempts <= MAX_CHRONOLOGY_RETRIES:
            attempts += 1
            repair_prompt = ScriptEngine.build_chronology_repair_prompt(
                current_script=text,
                chronology_details=val_details,
                story_plan=story_plan,
                evidence_packets=evidence_packets,
                target_lang=target_lang
            )

            retry_raw = generate_fn(repair_prompt)
            if retry_raw and len(retry_raw.strip()) > 80:
                retry_text = ScriptEngine.strip_code_and_developer_artifacts(retry_raw)
                retry_text = ScriptEngine.clamp_script_word_budget(
                    retry_text.strip(),
                    target_duration_mins=duration_mins,
                    target_lang=target_lang,
                    voice_speed=voice_speed
                )
                is_valid_r, val_report_r, val_details_r = ScriptEngine.validate_script_integrity(
                    script_text=retry_text,
                    source_duration_sec=source_video_duration_sec,
                    target_duration_mins=duration_mins,
                    target_lang=target_lang,
                    voice_speed=voice_speed,
                    dialogue_timeline=dialogue_timeline,
                    evidence_packets=evidence_packets,
                    story_plan=story_plan,
                    return_details=True
                )
                if is_valid_r:
                    return retry_text, True, val_report_r, attempts, val_details_r
                else:
                    err_msg = f"Generated storyboard violates source chronology after one controlled repair attempt: {val_report_r}"
                    return retry_text, False, err_msg, attempts, val_details_r
            else:
                err_msg = "Generated storyboard violates source chronology after one controlled repair attempt: (repair attempt returned empty)"
                return text, False, err_msg, attempts, val_details

        return text, False, val_report, attempts, val_details


    @staticmethod
    def get_configured_embedding_provider() -> Optional[EmbeddingProvider]:
        """
        Factory to instantiate the production embedding provider if configured and enabled (Phase 5B).

        Resolution order:
        1. Explicit toggle: SEMANTIC_RETRIEVAL_ENABLED env var ("1", "true", "yes") or
           "semantic_retrieval_enabled" in ai_settings.json.
           If neither is truthy, returns None (semantic retrieval remains disabled).
        2. Endpoint/Key discovery:
           - EMBEDDING_BASE_URL (or active provider URL from ai_settings.json)
           - EMBEDDING_API_KEY (or active provider key from ai_settings.json / OPENAI_API_KEY)
           - EMBEDDING_MODEL (or provider model, default 'text-embedding-3-small')
        3. Returns OpenAICompatibleEmbeddingProvider instance when enabled.
        4. If credentials/config are missing or initialization fails:
           Safely returns None without crashing the application.
        """
        try:
            # 1. Check explicit enable toggle
            env_enabled = os.environ.get("SEMANTIC_RETRIEVAL_ENABLED", "").strip().lower()

            ai_cfg = {}
            try:
                from app.services.ai_router import load_ai_settings
                ai_cfg = load_ai_settings()
            except Exception:
                pass

            cfg_enabled = bool(ai_cfg.get("semantic_retrieval_enabled", False))

            is_enabled = False
            if env_enabled in ("1", "true", "yes", "on"):
                is_enabled = True
            elif env_enabled in ("0", "false", "no", "off"):
                is_enabled = False
            else:
                is_enabled = cfg_enabled

            if not is_enabled:
                return None

            # 2. Determine provider configuration
            env_prov = os.environ.get("EMBEDDING_PROVIDER", "").strip()
            active_prov = env_prov or ai_cfg.get("active_provider", "openai")
            prov_details = ai_cfg.get("providers", {}).get(active_prov, {})

            # Resolve Base URL
            base_url = os.environ.get("EMBEDDING_BASE_URL", "").strip()
            if not base_url:
                if active_prov == "openai":
                    base_url = "https://api.openai.com/v1"
                else:
                    base_url = prov_details.get("url", "http://127.0.0.1:20128/v1")

            # Refine provider identity if URL points to a specific vendor
            if not env_prov:
                if "openai.com" in base_url.lower():
                    active_prov = "openai"
                elif "localhost:11434" in base_url.lower():
                    active_prov = "ollama"
                elif "127.0.0.1:20128" in base_url.lower() or "9router" in base_url.lower():
                    active_prov = "9router"

            # Resolve API Key
            api_key = os.environ.get("EMBEDDING_API_KEY", "").strip()
            if not api_key:
                if active_prov == "openai":
                    api_key = os.environ.get("OPENAI_API_KEY", "").strip() or prov_details.get("key", "").strip()
                else:
                    api_key = prov_details.get("key", "").strip()

            # Resolve Model Name
            model_name = os.environ.get("EMBEDDING_MODEL", "").strip()
            if not model_name:
                model_name = prov_details.get("embedding_model", "text-embedding-3-small").strip()

            timeout = float(os.environ.get("EMBEDDING_TIMEOUT", "10.0"))

            return OpenAICompatibleEmbeddingProvider(
                base_url=base_url,
                api_key=api_key,
                model_name=model_name,
                timeout=timeout,
                provider_name=active_prov
            )
        except Exception as e:
            print(f"[EmbeddingProvider Notice] Failed to initialize configured provider: {e}")
            return None

    @staticmethod
    def parse_storyboard_blocks(
        raw_script: str,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        embedding_provider: Optional[Any] = None,
        transcript_source: Optional[str] = None,
        evidence_packets: Optional[List[Any]] = None,
        story_plan: Optional[List[Any]] = None,
        enforce_source_provenance: Optional[bool] = None
    ) -> List[SceneBlock]:
        """
        Parses structured SceneBlock objects pairing each scene timestamp cut [SCENE: MM:SS - MM:SS]
        with its clean narration text and word count.

        T-03 Extension: If dialogue_timeline is supplied (list of {start, end, text} cues from
        the source movie transcript), anchor_scenes_to_dialogue() is called automatically after
        parsing to replace AI-invented timestamps with real movie timestamps.
        Omit dialogue_timeline for backward-compatible behavior.
        Phase 5: Optional embedding_provider enables controlled semantic candidate retrieval.
        Phase 6F: Source-bound dialogue reference validation strictly enforces that non-null
        dialogue_ref must be traceable to source evidence (EvidencePacket or dialogue_timeline).
        """
        if not raw_script:
            return []

        def time_to_sec(t: str) -> float:
            parts = t.strip().split(':')
            try:
                if len(parts) == 2:
                    return int(parts[0]) * 60 + float(parts[1])
                elif len(parts) == 3:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            except Exception:
                pass
            return 0.0

        def clean_narration_chunk(txt: str) -> str:
            vo_m = re.search(r'(?:\[VOICEOVER\]|\bVOICEOVER\b\]?)\s*(.*?)(?=(?:\[(?:SCENE|TIME)|SCENE\s*\d*:|===PART|📝|\Z))', txt, flags=re.DOTALL | re.IGNORECASE)
            target = vo_m.group(1) if vo_m else txt

            lines = []
            for l in target.splitlines():
                line = l.strip()
                if not line or line.startswith(('#', '📌', '🏷️', '📝', '---', '===', 'Option:')):
                    continue
                cl = ScriptEngine.strip_production_tags(line)
                if len(cl) > 3:
                    lines.append(cl)
            cleaned = ' '.join(lines)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            return cleaned

        ts_header_pattern = re.compile(
            r'(?:\[SCENE:\s*|\bSCENE\s*\d*:\s*|\[)?(\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—to]+\s*(\d{1,2}:\d{2}(?::\d{2})?)\]?',
            re.IGNORECASE
        )

        matches = list(ts_header_pattern.finditer(raw_script))
        blocks: List[SceneBlock] = []

        if matches:
            for idx, m in enumerate(matches):
                s_sec = time_to_sec(m.group(1))
                e_sec = time_to_sec(m.group(2))
                if e_sec <= s_sec:
                    e_sec = s_sec + 5.0

                start_pos = m.end()
                end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(raw_script)
                chunk = raw_script[start_pos:end_pos]

                d_ref_m = re.search(
                    r'(?:\[DIALOGUE_REF:\s*["\'“”‘’]?(.*?)["\'“”‘’]?\]|\bDIALOGUE_REF:\s*["\'“”‘’]?(.*?)["\'“”‘’]?(?=\n|\Z|\[))',
                    chunk,
                    flags=re.IGNORECASE
                )
                raw_d_ref = ""
                if d_ref_m:
                    raw_d_ref = (d_ref_m.group(1) or d_ref_m.group(2) or "").strip().strip('"\'“”‘’')

                cleaned = clean_narration_chunk(chunk)
                if not cleaned and idx == 0:
                    cleaned = clean_narration_chunk(raw_script[:m.start()])

                w_count = len(cleaned.split()) if cleaned else 0
                if cleaned and w_count > 0:
                    dialogue_ref = raw_d_ref if raw_d_ref else None
                    evidence_ref = None

                    # Phase 6F: Source-Bound Dialogue Reference Validation
                    # If source evidence is available (dialogue_timeline, evidence_packets, or enforce flag),
                    # strictly verify provenance. If not source-bound, safely convert to None (null).
                    should_validate = enforce_source_provenance if enforce_source_provenance is not None else (
                        (dialogue_timeline is not None) or (evidence_packets is not None)
                    )
                    source_timestamp = None
                    if should_validate:
                        if dialogue_ref:
                            prov = ScriptEngine.validate_dialogue_ref_provenance(
                                dialogue_ref=dialogue_ref,
                                evidence_packets=evidence_packets,
                                dialogue_timeline=dialogue_timeline
                            )
                            if prov.is_source_bound:
                                dialogue_ref = prov.dialogue_ref
                                evidence_ref = prov.evidence_ref
                                source_timestamp = prov.source_timestamp
                            else:
                                dialogue_ref = None
                        else:
                            dialogue_ref = None

                    blocks.append(SceneBlock(
                        movie_start=s_sec,
                        movie_end=e_sec,
                        narration_text=cleaned,
                        word_count=w_count,
                        dialogue_ref=dialogue_ref,
                        evidence_ref=evidence_ref,
                        source_timestamp=source_timestamp
                    ))

        if not blocks:
            final_text, ranges, _ = ScriptEngine.parse_storyboard(raw_script)
            if final_text:
                sentences = [s.strip() for s in re.split(r'[.!?۔।\n]+', final_text) if len(s.strip()) > 5]

                # ── T-FIX: 3-Act Proportional Fallback ─────────────────────────
                # If no [SCENE:] tags exist (e.g. plain ChatGPT text), build proportional
                # ranges spread across Acts 1/2/3 of the movie instead of a single
                # (0.0, 60.0) block that causes the full video to loop one clip.
                if not ranges:
                    n_scenes = max(4, len(sentences))
                    movie_dur_guess = 5400.0  # assume ~90-min film as safe default
                    # Act 1 (20%): clips from 2–20% of movie
                    # Act 2 (60%): clips from 20–75% of movie
                    # Act 3 (20%): clips from 75–92% of movie
                    act_defs = [
                        (int(n_scenes * 0.20), 0.02  * movie_dur_guess, 0.20 * movie_dur_guess),
                        (int(n_scenes * 0.60), 0.20  * movie_dur_guess, 0.75 * movie_dur_guess),
                        (n_scenes - int(n_scenes * 0.20) - int(n_scenes * 0.60),
                         0.75 * movie_dur_guess, 0.92 * movie_dur_guess),
                    ]
                    ranges = []
                    clip_dur = 4.5
                    for act_count, act_start, act_end in act_defs:
                        if act_count <= 0:
                            continue
                        step = (act_end - act_start) / max(1, act_count)
                        for i in range(act_count):
                            s = act_start + i * step
                            ranges.append((round(s, 1), round(s + clip_dur, 1)))
                # ── End T-FIX ──────────────────────────────────────────────────

                step = len(sentences) / max(1, len(ranges))
                for r_idx, (r_s, r_e) in enumerate(ranges):
                    start_s_idx = int(r_idx * step)
                    end_s_idx = int((r_idx + 1) * step) if r_idx < len(ranges) - 1 else len(sentences)
                    scene_text = " ".join(sentences[start_s_idx:end_s_idx])
                    if not scene_text and sentences:
                        scene_text = sentences[min(r_idx, len(sentences) - 1)]
                    wc = len(scene_text.split())
                    blocks.append(SceneBlock(
                        movie_start=r_s,
                        movie_end=r_e,
                        narration_text=scene_text,
                        word_count=max(1, wc)
                    ))

        # Phase 6G.3: Storyboard Source Chronology Validation Gate
        if dialogue_timeline:
            is_chron_valid, chron_report, chron_details = ScriptEngine.validate_storyboard_chronology(
                blocks=blocks,
                dialogue_timeline=dialogue_timeline,
                evidence_packets=evidence_packets,
                story_plan=story_plan
            )
            if not is_chron_valid:
                # Halt visual anchoring: DO NOT proceed into anchor_scenes_to_dialogue()
                for b in blocks:
                    b.chronology_valid = False
                    b.chronology_error = chron_report
                    b.is_authoritative = False
                print(f"[Chronology Gate Blocked] {chron_report}")
            else:
                # Chronology valid -> proceed with visual anchoring
                blocks = ScriptEngine.anchor_scenes_to_dialogue(
                    blocks,
                    dialogue_timeline,
                    embedding_provider=embedding_provider
                )

        # Phase 3B/6F: Link story_plan and evidence_ref to SceneBlocks if provided
        if story_plan and blocks:
            for b in blocks:
                b_start = float(b.movie_start)
                matched_plan = min(
                    story_plan,
                    key=lambda it: abs(float(it.get("source_timestamp", 0.0) if isinstance(it, dict) else getattr(it, "source_timestamp", 0.0)) - b_start)
                )
                plan_step = matched_plan.get("step") if isinstance(matched_plan, dict) else getattr(matched_plan, "step", None)
                plan_ref = matched_plan.get("evidence_ref") if isinstance(matched_plan, dict) else getattr(matched_plan, "evidence_ref", None)
                if not b.story_step and plan_step is not None:
                    b.story_step = plan_step
                if not b.evidence_ref and plan_ref:
                    b.evidence_ref = plan_ref

        # Phase 6A: Tag blocks with transcript source if provided or inferred
        resolved_source = transcript_source
        if not resolved_source:
            if dialogue_timeline and len(dialogue_timeline) > 0:
                resolved_source = dialogue_timeline[0].get("source", "existing_subtitles")
            else:
                resolved_source = "none"

        for b in blocks:
            b.transcript_source = resolved_source

        return blocks

    @staticmethod
    def anchor_scenes_to_dialogue(
        blocks: List["SceneBlock"],
        dialogue_timeline: List[Dict[str, Any]],
        min_scene_dur: float = 5.0,
        max_scene_dur: float = 90.0,
        embedding_provider: Optional[Any] = None,
        semantic_top_k: int = 5,
        min_semantic_sim: float = 0.40,
        semantic_weight: float = 1.50
    ) -> List["SceneBlock"]:
        """
        Dialogue-Anchor Algorithm (T-01).

        Replaces AI-invented [SCENE: MM:SS] timestamps in each SceneBlock with
        REAL timestamps from the source movie's dialogue_timeline, ensuring that
        the video clip cut corresponds to the actual movie moment being narrated.

        Strategy (keyword overlap — no external deps):
          1. Tokenise each block's narration_text into a set of meaningful words.
          2. For every dialogue_timeline cue, count the number of shared tokens with
             the block's narration.
          3. The cue with the highest overlap score becomes the anchor.
          4. Chronological integrity: each block's anchor must be >= previous block's
             anchor (stable sort).
          5. Graceful fallback: if no useful match is found (score == 0), the block
             keeps its original AI timestamp — never silently dropped.

        Args:
            blocks:            SceneBlocks parsed from the AI-generated script.
            dialogue_timeline: [{start, end, text}, ...] from parse_raw_transcript_text().
            min_scene_dur:     Minimum scene window in seconds (default 5.0s).
            max_scene_dur:     Maximum scene window in seconds (default 90.0s).

        Returns:
            Same list of SceneBlocks with movie_start / movie_end updated to real
            timestamps where a confident match was found.
        """
        if not blocks:
            return []
        if not dialogue_timeline:
            return blocks  # graceful fallback: keep AI timestamps

        # --- Stop-word filter (language-agnostic common words to ignore) ---
        STOP_WORDS = {
            "a", "an", "the", "is", "in", "it", "of", "to", "and", "or",
            "on", "at", "by", "as", "be", "we", "he", "she", "his", "her",
            "was", "are", "this", "that", "with", "for", "from", "not",
            "but", "so", "if", "its", "into", "up", "out", "now", "then",
            "were", "have", "has", "had", "would", "could", "will", "do",
            # Contraction stems & conversational fillers (Phase 6E.2 hardening)
            "don", "didn", "doesn", "wasn", "weren", "haven", "hasn", "hadn",
            "won", "wouldn", "couldn", "shouldn", "isn", "aren", "ain",
            "ve", "re", "ll", "d", "m", "kind", "sort",
        }

        def normalize_str(s: str) -> str:
            if not s:
                return ""
            norm = unicodedata.normalize("NFKC", str(s))
            norm = re.sub(r'[""«»„]', '"', norm)
            norm = re.sub(r"['']", "'", norm)
            norm = re.sub(r"n't\b", " not", norm)
            norm = re.sub(r"'re\b", " are", norm)
            norm = re.sub(r"'ve\b", " have", norm)
            norm = re.sub(r"'ll\b", " will", norm)
            norm = re.sub(r"'d\b", " would", norm)
            norm = re.sub(r"'m\b", " am", norm)
            norm = re.sub(r"[^\w\s]", " ", norm, flags=re.UNICODE)
            return re.sub(r"\s+", " ", norm.lower(), flags=re.UNICODE).strip()

        def tokenize(text: str) -> set:
            """Unicode alpha tokens for English, Urdu, Hindi, Arabic, etc., dropping stop-words and pure digits."""
            if not text:
                return set()
            norm = unicodedata.normalize("NFKC", str(text))
            norm = re.sub(r"n't\b", " not", norm)
            norm = re.sub(r"'re\b", " are", norm)
            norm = re.sub(r"'ve\b", " have", norm)
            norm = re.sub(r"'ll\b", " will", norm)
            norm = re.sub(r"'d\b", " would", norm)
            norm = re.sub(r"'m\b", " am", norm)
            tokens = re.findall(r"\w{2,}", norm.lower(), flags=re.UNICODE)
            return {t for t in tokens if t not in STOP_WORDS and not t.isdigit()}

        def longest_common_substring(s1: str, s2: str) -> str:
            """Finds the longest contiguous common substring between two normalized strings."""
            if not s1 or not s2:
                return ""
            matcher = difflib.SequenceMatcher(None, s1, s2)
            match = matcher.find_longest_match(0, len(s1), 0, len(s2))
            if match.size > 0:
                return s1[match.a : match.a + match.size].strip()
            return ""

        def get_stems(w: str) -> set:
            """Lightweight deterministic English inflection & stem generator."""
            w = w.lower().strip()
            if len(w) < 3:
                return {w}
            stems = {w}
            # Plural / 3rd person -s, -es, -ies
            if w.endswith("ies") and len(w) > 4:
                stems.add(w[:-3] + "y")
            elif w.endswith("es") and len(w) > 4 and not w.endswith(("ees", "ies")):
                stems.add(w[:-2])
                stems.add(w[:-1])
            elif w.endswith("s") and len(w) > 3 and not w.endswith(("ss", "us", "is")):
                stems.add(w[:-1])
            # Past tense / participle -ed, -ied
            if w.endswith("ied") and len(w) > 4:
                stems.add(w[:-3] + "y")
            elif w.endswith("ed") and len(w) > 4:
                stems.add(w[:-2])
                stems.add(w[:-1])
            # Present participle -ing
            if w.endswith("ing") and len(w) > 5:
                base = w[:-3]
                stems.add(base)
                stems.add(base + "e")
                if len(base) >= 3 and base[-1] == base[-2]:
                    stems.add(base[:-1])
            # Agent noun -er, -or
            if w.endswith("er") and len(w) > 4:
                stems.add(w[:-2])
                stems.add(w[:-1])
            elif w.endswith("or") and len(w) > 4:
                stems.add(w[:-2])
            # Silent -e
            if w.endswith("e") and len(w) > 3 and not w.endswith(("ee", "ye", "oe")):
                stems.add(w[:-1])
            return stems

        def score_match(
            b_tokens: set,
            c_tokens: set,
            b_stems: Optional[Dict[str, set]] = None,
            c_stems: Optional[Dict[str, set]] = None,
        ) -> Tuple[int, int, float]:
            """
            Phase 2 Deterministic Lexical & Fuzzy Candidate Scoring:
            1. Exact non-stopword token overlap (weight: 1.0 per exact match).
            2. Morphological stem overlap & pre-filtered fuzzy match (weight: 0.7 per fuzzy match).
            Returns (exact_count, fuzzy_count, total_score).
            """
            if not b_tokens or not c_tokens:
                return 0, 0, 0.0

            exact = b_tokens & c_tokens
            exact_count = len(exact)

            unmatched_b = b_tokens - exact
            unmatched_c = set(c_tokens - exact)

            fuzzy_count = 0
            if unmatched_b and unmatched_c:
                for bt in unmatched_b:
                    if len(bt) < 4:
                        continue
                    stems_b = b_stems.get(bt) if b_stems else get_stems(bt)
                    matched_ct = None
                    for ct in unmatched_c:
                        if len(ct) < 4:
                            continue
                        stems_c = c_stems.get(ct) if c_stems else get_stems(ct)
                        # 1. Morphological stem overlap (O(1))
                        if stems_b and stems_c and (stems_b & stems_c):
                            matched_ct = ct
                            break
                        # 2. Pre-filtered difflib check for OCR/typos
                        if bt[0] == ct[0] and abs(len(bt) - len(ct)) <= 2:
                            min_l, max_l = min(len(bt), len(ct)), max(len(bt), len(ct))
                            if min_l / max_l >= 0.70:
                                if difflib.SequenceMatcher(None, bt, ct).ratio() >= 0.82:
                                    matched_ct = ct
                                    break
                    if matched_ct:
                        fuzzy_count += 1
                        unmatched_c.remove(matched_ct)

            total_score = round(float(exact_count) * 1.0 + float(fuzzy_count) * 0.70, 2)
            return exact_count, fuzzy_count, total_score

        # Pre-tokenise all blocks and cues once, and precompute stems
        block_token_sets = [tokenize(b.narration_text) for b in blocks]
        cue_token_sets = [tokenize(c.get("text", "")) for c in dialogue_timeline]

        block_stem_maps = [{t: get_stems(t) for t in ts} for ts in block_token_sets]
        cue_stem_maps = [{t: get_stems(t) for t in ts} for ts in cue_token_sets]

        tl_start = float(dialogue_timeline[0].get("start", 0.0)) if dialogue_timeline else 0.0
        tl_end = float(dialogue_timeline[-1].get("start", 0.0)) if dialogue_timeline else 0.0
        timeline_span = max(1.0, tl_end - tl_start)
        n_blocks = len(blocks)
        nominal_spacing = timeline_span / n_blocks if n_blocks > 1 else max(30.0, timeline_span * 0.15)

        # Phase 5 / 5B: Pre-embed dialogue timeline cues using batch embedding and namespace-isolated cache
        cue_embeddings: List[Optional[List[float]]] = []
        if embedding_provider is not None:
            try:
                namespace = getattr(embedding_provider, "namespace", "default")

                # Step 1: Identify uncached cues needing batch embedding
                uncached_to_fetch: List[Tuple[int, str]] = []
                for c_idx, cue in enumerate(dialogue_timeline):
                    txt = (cue.get("text") or "").strip()
                    if txt:
                        cached = _GLOBAL_EMBEDDING_CACHE.get(txt, namespace=namespace)
                        if cached is None:
                            uncached_to_fetch.append((c_idx, txt))

                # Step 2: Batch embed uncached cues
                if uncached_to_fetch:
                    texts_to_embed = [item[1] for item in uncached_to_fetch]
                    new_vectors = embedding_provider.embed_batch(texts_to_embed)
                    for (c_idx, txt), vec in zip(uncached_to_fetch, new_vectors):
                        if vec is not None and isinstance(vec, list):
                            _GLOBAL_EMBEDDING_CACHE.put(txt, vec, namespace=namespace)

                # Step 3: Populate cue_embeddings aligned 1:1 with dialogue_timeline
                for cue in dialogue_timeline:
                    txt = (cue.get("text") or "").strip()
                    if not txt:
                        cue_embeddings.append(None)
                    else:
                        v = _GLOBAL_EMBEDDING_CACHE.get(txt, namespace=namespace)
                        cue_embeddings.append(v)

            except Exception as e:
                # Security Rule 8: log failure details and fallback
                print(f"[SemanticRetrieval Notice] Cue embedding failed, falling back to lexical: {e}")
                embedding_provider = None
                cue_embeddings = []

        # Find best-matching cue for each block (monotonic grounding with anchor integrity hardening)
        anchors: List[float] = []  # matched movie_start for each block
        anchor_strengths: List[bool] = []  # True if strong anchor, False if weak or fallback
        last_strong_anchor = 0.0
        prev_anchor = 0.0

        for b_idx, block in enumerate(blocks):
            b_tokens = block_token_sets[b_idx]
            b_stems = block_stem_maps[b_idx]
            d_ref = getattr(block, "dialogue_ref", "") or ""
            norm_ref = normalize_str(d_ref) if d_ref else ""
            ref_tokens = tokenize(d_ref) if d_ref else set()
            ref_stems = {t: get_stems(t) for t in ref_tokens} if ref_tokens else {}

            target_ts = float(getattr(block, "movie_start", 0.0))
            block_dur = max(10.0, float(getattr(block, "movie_end", target_ts + 30.0)) - target_ts)
            # Duration-adaptive contextual window radius (Phase 2.1):
            # - Scales with scene duration and inter-scene spacing.
            # - Locks to standard 15% span radius (30% total coverage) on medium/long-form content.
            # - Bounded to at most 25% span radius (50% max coverage) to prevent full-movie dilation on short videos.
            base_radius = max(block_dur * 1.5, nominal_spacing * 1.5, timeline_span * 0.15)
            window_radius = max(min(timeline_span * 0.25, base_radius), min(block_dur, timeline_span * 0.5))

            block_vec = None
            if embedding_provider is not None and getattr(block, "narration_text", ""):
                try:
                    namespace = getattr(embedding_provider, "namespace", "default")
                    b_txt = block.narration_text.strip()
                    cached_b = _GLOBAL_EMBEDDING_CACHE.get(b_txt, namespace=namespace)
                    if cached_b is not None:
                        block_vec = cached_b
                    else:
                        block_vec = embedding_provider.embed_text(b_txt)
                        if block_vec is not None and isinstance(block_vec, list):
                            _GLOBAL_EMBEDDING_CACHE.put(b_txt, block_vec, namespace=namespace)
                except Exception as e:
                    print(f"[SemanticRetrieval Notice] Query embedding failed for block {b_idx}: {e}")
                    block_vec = None

            if not b_tokens and not ref_tokens and block_vec is None:
                # No meaningful tokens and no semantic vector → keep original timestamp
                fallback = max(last_strong_anchor, max(prev_anchor, block.movie_start))
                anchors.append(fallback)
                anchor_strengths.append(False)
                prev_anchor = fallback
                continue

            candidates = []

            for c_idx, cue in enumerate(dialogue_timeline):
                cue_start = float(cue.get("start", 0.0))
                # Only consider cues AFTER the last strong anchor (chronological anchor lock)
                if cue_start < last_strong_anchor:
                    continue
                cue_text = cue.get("text", "")
                norm_cue = normalize_str(cue_text)
                cue_tokens = cue_token_sets[c_idx]
                c_stems = cue_stem_maps[c_idx]

                ref_score = 0.0
                if norm_ref:
                    # Phase 6E.2 Hardening: Substantive dialogue_ref match vs generic conversational overlap
                    # 1. Direct quote substring containment
                    is_quote_contained = norm_ref in norm_cue and (
                        len(norm_ref) >= 8 and (len(ref_tokens) >= 2 or any(len(t) >= 5 for t in ref_tokens))
                    )
                    is_cue_subquote = norm_cue in norm_ref and (
                        len(norm_cue) >= 8 and (len(cue_tokens) >= 2 or any(len(t) >= 5 for t in cue_tokens))
                    )
                    if is_quote_contained:
                        ref_score = 1000.0 + len(ref_tokens)
                    elif is_cue_subquote:
                        ref_score = 1000.0 + len(cue_tokens)
                    else:
                        # 2. Sentence / clause verbatim containment (e.g. multi-sentence quotes like Scene 02)
                        ref_sentences = [s.strip() for s in re.split(r'[\.\!\?\;\n]+', block.dialogue_ref or "") if s.strip()]
                        cue_sentences = [s.strip() for s in re.split(r'[\.\!\?\;\n]+', cue_text or "") if s.strip()]

                        matched_sent_score = 0.0
                        for r_s in ref_sentences:
                            n_rs = normalize_str(r_s)
                            if n_rs and n_rs in norm_cue:
                                t_rs = tokenize(n_rs)
                                if len(n_rs) >= 8 and (len(t_rs) >= 2 or any(len(t) >= 5 for t in t_rs)):
                                    matched_sent_score = max(matched_sent_score, 1000.0 + len(t_rs))

                        for c_s in cue_sentences:
                            n_cs = normalize_str(c_s)
                            if n_cs and n_cs in norm_ref:
                                t_cs = tokenize(n_cs)
                                if len(n_cs) >= 8 and (len(t_cs) >= 2 or any(len(t) >= 5 for t in t_cs)):
                                    matched_sent_score = max(matched_sent_score, 1000.0 + len(t_cs))

                        if matched_sent_score > 0.0:
                            ref_score = matched_sent_score
                        elif ref_tokens and cue_tokens:
                            # 3. High substantive recall with at least two distinctive content words (len >= 6)
                            matched = ref_tokens & cue_tokens
                            distinctive_matched = [t for t in matched if len(t) >= 6]
                            recall = len(matched) / len(ref_tokens)
                            if len(distinctive_matched) >= 2 and recall >= 0.70:
                                ref_score = 500.0 + 10.0 * len(matched)

                exact_cnt, fuzzy_cnt, match_sc = score_match(b_tokens, cue_tokens, b_stems, c_stems)
                dist = abs(cue_start - target_ts)

                # Phase 5: Semantic similarity & composite scoring
                sem_sim = 0.0
                sem_bonus = 0.0
                if block_vec is not None and c_idx < len(cue_embeddings) and cue_embeddings[c_idx] is not None:
                    sem_sim = cosine_similarity(block_vec, cue_embeddings[c_idx])
                    if sem_sim >= min_semantic_sim:
                        sem_bonus = round(sem_sim * semantic_weight, 2)

                combined_sc = round(match_sc + sem_bonus, 2)
                matching_exact_tokens = b_tokens & cue_tokens
                max_exact_token_len = max((len(t) for t in matching_exact_tokens), default=0)

                if ref_score > 0.0 or match_sc > 0.0 or sem_bonus > 0.0:
                    candidates.append({
                        "start": cue_start,
                        "ref_score": ref_score,
                        "exact_count": exact_cnt,
                        "fuzzy_count": fuzzy_cnt,
                        "match_score": match_sc,
                        "semantic_score": sem_sim,
                        "semantic_bonus": sem_bonus,
                        "combined_score": combined_sc,
                        "dist": dist,
                        "in_primary": dist <= window_radius,
                        "max_exact_token_len": max_exact_token_len,
                    })

            def qualifies_for_tier(cand: dict, tier_mult: float) -> bool:
                """Phase 6E Requirement A: Outlier rejection for progressive widening tiers."""
                if cand["ref_score"] >= 100.0:
                    return True
                # Tier 1.0 (inside primary contextual window)
                if tier_mult <= 1.0:
                    return cand["combined_score"] >= 1.0 or cand["match_score"] >= 1.0
                # Tier 2.0 (dist <= 2.0 * window_radius)
                if tier_mult <= 2.0:
                    if cand["exact_count"] >= 2 or cand["semantic_bonus"] >= 0.70 or cand["combined_score"] >= 1.4:
                        return True
                    if cand["exact_count"] >= 1 and cand.get("max_exact_token_len", 0) >= 7:
                        return True
                    return False
                # Tier 3.0 (dist <= 3.0 * window_radius)
                if tier_mult <= 3.0:
                    if cand["exact_count"] >= 2 or cand["semantic_bonus"] >= 0.70 or cand["combined_score"] >= 1.7:
                        return True
                    if cand["exact_count"] >= 1 and cand.get("max_exact_token_len", 0) >= 7:
                        return True
                    return False
                # Global Tier (tier_mult > 3.0, e.g. 999.0):
                # Rejects distant incidental single words (taking, work, time, man, help, get, make).
                # Requires >=2 exact tokens, semantic support (>=0.70), composite score >=2.0,
                # or a distinctive long keyword (>=8 chars, e.g. "prophecy").
                if cand["exact_count"] >= 2 or cand["semantic_bonus"] >= 0.70 or cand["combined_score"] >= 2.0:
                    return True
                if cand["exact_count"] >= 1 and cand.get("max_exact_token_len", 0) >= 8:
                    return True
                return False

            def is_candidate_strong(cand: Optional[dict]) -> bool:
                """Phase 6E Requirement B: Classify candidate confidence to prevent forward starvation."""
                if cand is None:
                    return False
                if cand["ref_score"] >= 100.0:
                    return True
                if cand["exact_count"] >= 2:
                    return True
                if cand["match_score"] >= 2.0:
                    return True
                if cand["semantic_bonus"] >= 0.70:
                    return True
                if cand["in_primary"] and cand["combined_score"] >= 1.4:
                    return True
                if cand["dist"] <= 2.0 * window_radius and cand.get("max_exact_token_len", 0) >= 8 and cand["combined_score"] >= 1.0:
                    return True
                return False

            best_cand = None

            if candidates:
                # Stage 1: Explicit dialogue_ref priority (Rule D)
                ref_cands = [c for c in candidates if c["ref_score"] >= 100.0]
                if ref_cands:
                    best_ref = min(ref_cands, key=lambda c: (-c["ref_score"], c["dist"]))
                    best_cand = best_ref
                else:
                    # Stage 2: Strong global exact matches (Rule A)
                    # When a distant candidate has overwhelming exact evidence (>=3 exact tokens, score >= 3.0),
                    # it overrides weak nearby fuzzy/incidental evidence.
                    strong_global = [c for c in candidates if c["exact_count"] >= 3 and c["match_score"] >= 3.0]
                    in_window = [c for c in candidates if c["in_primary"]]
                    best_in = max(in_window, key=lambda c: (c["combined_score"], -c["dist"])) if in_window else None

                    if strong_global and (not best_in or best_in["combined_score"] < 2.5):
                        best_cand = max(strong_global, key=lambda c: (c["match_score"], -c["dist"]))
                    elif best_in and best_in["combined_score"] >= 1.4:
                        # Corroborated evidence in primary contextual window (Rule C: prevents distant incidental hijack)
                        best_cand = best_in
                    else:
                        # Stage 3: Progressive Window Widening with Outlier Rejection
                        for tier_mult in [1.0, 2.0, 3.0, 999.0]:
                            tier_cands = [
                                c for c in candidates
                                if c["dist"] <= tier_mult * window_radius and qualifies_for_tier(c, tier_mult)
                            ]
                            if tier_cands:
                                best_cand = max(tier_cands, key=lambda c: (c["combined_score"], -c["dist"]))
                                break

            strong = is_candidate_strong(best_cand)

            if best_cand is not None:
                cue_ts = best_cand["start"]
                if strong:
                    # Strong anchor: can anchor at cue_ts (>= last_strong_anchor) and advance both bounds
                    anchor_start = cue_ts
                    last_strong_anchor = cue_ts
                    prev_anchor = cue_ts
                else:
                    # Weak anchor: respects forward progress from prev_anchor
                    anchor_start = max(prev_anchor, cue_ts)
                    prev_anchor = anchor_start
                anchors.append(anchor_start)
                anchor_strengths.append(strong)
            else:
                # No match → keep original AI timestamp but respect chronological order
                fallback = max(last_strong_anchor, max(prev_anchor, block.movie_start))
                anchors.append(fallback)
                anchor_strengths.append(False)
                prev_anchor = fallback

        # Phase 6E: Chronological Reconciliation Pass
        # Reconciles weak/fallback anchors between established strong anchors to prevent forward starvation
        strong_indices = [i for i, s in enumerate(anchor_strengths) if s]
        has_inversion = any(anchors[i] > anchors[i + 1] for i in range(len(anchors) - 1))

        if has_inversion:
            if not strong_indices:
                # No strong anchors: monotonic forward clamp
                for i in range(1, len(anchors)):
                    anchors[i] = max(anchors[i], anchors[i - 1])
            else:
                # Reconcile segment before first strong anchor
                first_strong_idx = strong_indices[0]
                first_strong_ts = anchors[first_strong_idx]
                first_orig_ts = blocks[first_strong_idx].movie_start
                for k in range(first_strong_idx):
                    if anchors[k] > first_strong_ts:
                        if first_orig_ts > tl_start:
                            r = max(0.0, min(1.0, (blocks[k].movie_start - tl_start) / (first_orig_ts - tl_start)))
                            anchors[k] = round(tl_start + r * (first_strong_ts - tl_start), 2)
                        else:
                            f = (k + 1) / (first_strong_idx + 1)
                            anchors[k] = round(tl_start + f * (first_strong_ts - tl_start), 2)
                for k in range(1, first_strong_idx):
                    anchors[k] = max(anchors[k], anchors[k - 1])

                # Reconcile segments between consecutive strong anchors
                for s_i in range(len(strong_indices) - 1):
                    idx_prev = strong_indices[s_i]
                    idx_next = strong_indices[s_i + 1]
                    ts_prev = anchors[idx_prev]
                    ts_next = anchors[idx_next]
                    orig_prev = blocks[idx_prev].movie_start
                    orig_next = blocks[idx_next].movie_start

                    sub = list(range(idx_prev + 1, idx_next))
                    if sub and any(anchors[k] > ts_next or anchors[k] < ts_prev for k in sub):
                        for k in sub:
                            if orig_next > orig_prev:
                                r = max(0.0, min(1.0, (blocks[k].movie_start - orig_prev) / (orig_next - orig_prev)))
                                anchors[k] = round(ts_prev + r * (ts_next - ts_prev), 2)
                            else:
                                f = (k - idx_prev) / (idx_next - idx_prev)
                                anchors[k] = round(ts_prev + f * (ts_next - ts_prev), 2)
                        for k in sub:
                            anchors[k] = max(anchors[k], anchors[k - 1])
                            anchors[k] = min(anchors[k], ts_next)

                # Reconcile segment after last strong anchor
                last_strong_idx = strong_indices[-1]
                last_strong_ts = anchors[last_strong_idx]
                for k in range(last_strong_idx + 1, len(anchors)):
                    anchors[k] = max(anchors[k], anchors[k - 1], last_strong_ts)

        # Apply anchors back to SceneBlocks
        for b_idx, block in enumerate(blocks):
            new_start = anchors[b_idx]
            # Compute window: preserve original span but clamp to [min, max]
            original_span = max(min_scene_dur, block.movie_end - block.movie_start)
            clamped_span = min(original_span, max_scene_dur)
            new_end = round(new_start + clamped_span, 2)
            block.movie_start = round(new_start, 2)
            block.movie_end = new_end

        return blocks

    @staticmethod
    def explain_candidate_match(
        narration_text: str,
        cue_text: str,
        embedding_provider: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Test and auditing helper for source-grounding transparency (Phase 2 Step 9 / Phase 5).
        Provides a deterministic breakdown of tokens, exact matches, morphological stems,
        and optional semantic similarity metrics.
        """
        import difflib
        import re
        import unicodedata

        STOP_WORDS = {
            "a", "an", "the", "is", "in", "it", "of", "to", "and", "or",
            "on", "at", "by", "as", "be", "we", "he", "she", "his", "her",
            "was", "are", "this", "that", "with", "for", "from", "not",
            "but", "so", "if", "its", "into", "up", "out", "now", "then",
            "were", "have", "has", "had", "would", "could", "will", "do",
            # Contraction stems & conversational fillers (Phase 6E.2 hardening)
            "don", "didn", "doesn", "wasn", "weren", "haven", "hasn", "hadn",
            "won", "wouldn", "couldn", "shouldn", "isn", "aren", "ain",
            "ve", "re", "ll", "d", "m", "kind", "sort",
        }

        def tokenize(text: str) -> set:
            if not text:
                return set()
            norm = unicodedata.normalize("NFKC", str(text))
            norm = re.sub(r"n't\b", " not", norm)
            norm = re.sub(r"'re\b", " are", norm)
            norm = re.sub(r"'ve\b", " have", norm)
            norm = re.sub(r"'ll\b", " will", norm)
            norm = re.sub(r"'d\b", " would", norm)
            norm = re.sub(r"'m\b", " am", norm)
            tokens = re.findall(r"\w{2,}", norm.lower(), flags=re.UNICODE)
            return {t for t in tokens if t not in STOP_WORDS and not t.isdigit()}

        def get_stems(w: str) -> set:
            w = w.lower().strip()
            if len(w) < 3:
                return {w}
            stems = {w}
            if w.endswith("ies") and len(w) > 4:
                stems.add(w[:-3] + "y")
            elif w.endswith("es") and len(w) > 4 and not w.endswith(("ees", "ies")):
                stems.add(w[:-2])
                stems.add(w[:-1])
            elif w.endswith("s") and len(w) > 3 and not w.endswith(("ss", "us", "is")):
                stems.add(w[:-1])
            if w.endswith("ied") and len(w) > 4:
                stems.add(w[:-3] + "y")
            elif w.endswith("ed") and len(w) > 4:
                stems.add(w[:-2])
                stems.add(w[:-1])
            if w.endswith("ing") and len(w) > 5:
                base = w[:-3]
                stems.add(base)
                stems.add(base + "e")
                if len(base) >= 3 and base[-1] == base[-2]:
                    stems.add(base[:-1])
            if w.endswith("er") and len(w) > 4:
                stems.add(w[:-2])
                stems.add(w[:-1])
            elif w.endswith("or") and len(w) > 4:
                stems.add(w[:-2])
            if w.endswith("e") and len(w) > 3 and not w.endswith(("ee", "ye", "oe")):
                stems.add(w[:-1])
            return stems

        b_tokens = tokenize(narration_text)
        c_tokens = tokenize(cue_text)
        exact = sorted(list(b_tokens & c_tokens))
        exact_count = len(exact)

        unmatched_b = b_tokens - set(exact)
        unmatched_c = set(c_tokens - set(exact))

        fuzzy_pairs = []
        if unmatched_b and unmatched_c:
            for bt in unmatched_b:
                if len(bt) < 4:
                    continue
                stems_b = get_stems(bt)
                matched_ct = None
                match_type = ""
                for ct in unmatched_c:
                    if len(ct) < 4:
                        continue
                    stems_c = get_stems(ct)
                    if stems_b & stems_c:
                        matched_ct = ct
                        match_type = "morphological_stem"
                        break
                    if bt[0] == ct[0] and abs(len(bt) - len(ct)) <= 2:
                        min_l, max_l = min(len(bt), len(ct)), max(len(bt), len(ct))
                        if min_l / max_l >= 0.70:
                            if difflib.SequenceMatcher(None, bt, ct).ratio() >= 0.82:
                                matched_ct = ct
                                match_type = "sequence_matcher"
                                break
                if matched_ct:
                    fuzzy_pairs.append((bt, matched_ct, match_type))
                    unmatched_c.remove(matched_ct)

        fuzzy_count = len(fuzzy_pairs)
        score = round(float(exact_count) * 1.0 + float(fuzzy_count) * 0.70, 2)

        sem_sim = 0.0
        combined_sc = score
        if embedding_provider is not None:
            try:
                v1 = embedding_provider.embed_text(narration_text)
                v2 = embedding_provider.embed_text(cue_text)
                sem_sim = cosine_similarity(v1, v2)
                sem_bonus = round(sem_sim * 1.50, 2) if sem_sim >= 0.40 else 0.0
                combined_sc = round(score + sem_bonus, 2)
            except Exception as e:
                print(f"[SemanticRetrieval Notice] explain_candidate_match embedding failed: {e}")

        res = {
            "narration_tokens": sorted(list(b_tokens)),
            "cue_tokens": sorted(list(c_tokens)),
            "exact_matches": exact,
            "exact_count": exact_count,
            "fuzzy_pairs": fuzzy_pairs,
            "fuzzy_count": fuzzy_count,
            "match_score": score,
        }
        if embedding_provider is not None:
            res["semantic_similarity"] = sem_sim
            res["combined_score"] = combined_sc

        return res

    @staticmethod
    def assign_narration_timing(
        blocks: List[SceneBlock],
        total_speech_dur: float,
        cues: Optional[List[Dict[str, Any]]] = None
    ) -> List[SceneBlock]:
        """
        Locks each SceneBlock to its exact spoken duration and start/end time.
        Level 1 (Authoritative): Matches against Edge-TTS sentence boundary cues (_cues.json).
        Level 2 (Proportional Fallback): Allocates duration based on word-count weighting.
        Enforces mathematical invariant: sum(block.speech_dur) == total_speech_dur.
        Phase 4A: Records estimated_duration vs actual_duration and marks blocks authoritative.
        """
        if not blocks:
            return []

        import math
        try:
            total_val = float(total_speech_dur)
            if not math.isfinite(total_val) or total_val <= 0.0:
                raise ValueError(f"Invalid total_speech_dur: {total_speech_dur}. Must be a finite positive number.")
        except (TypeError, ValueError) as ve:
            raise ValueError(f"Invalid total_speech_dur: {total_speech_dur}. Must be a finite positive number.") from ve

        total_speech_dur = round(total_val, 3)

        if len(blocks) == 1:
            if blocks[0].estimated_duration <= 0.0:
                blocks[0].estimated_duration = round(blocks[0].speech_dur, 3) if blocks[0].speech_dur > 0.0 else total_speech_dur
            blocks[0].actual_duration = total_speech_dur
            blocks[0].speech_dur = total_speech_dur
            blocks[0].narration_start = 0.0
            blocks[0].narration_end = total_speech_dur
            blocks[0].is_authoritative = True
            if not blocks[0].block_id:
                blocks[0].block_id = "SCENE_1"
            return blocks

        # Preserve / compute pre-TTS estimates if not already populated
        total_words = sum(max(1, b.word_count) for b in blocks)
        for idx, b in enumerate(blocks):
            if not b.block_id:
                b.block_id = f"SCENE_{idx + 1}"
            if b.estimated_duration <= 0.0:
                if b.speech_dur > 0.0:
                    b.estimated_duration = round(b.speech_dur, 3)
                else:
                    b.estimated_duration = round((max(1, b.word_count) / max(1, total_words)) * total_speech_dur, 3)

        used_cues = False
        if cues and len(cues) > 0:
            try:
                def norm(t: str) -> str:
                    return re.sub(r'[^\w\s]', '', t.lower()).strip()

                cue_idx = 0
                block_boundaries: List[Tuple[float, float]] = []

                for b_idx, b in enumerate(blocks):
                    b_words = norm(b.narration_text).split()
                    start_t = cues[min(cue_idx, len(cues) - 1)]["start"] if b_idx > 0 else 0.0

                    matched_words = 0
                    target_words = max(1, len(b_words))
                    last_end = start_t

                    while cue_idx < len(cues):
                        c = cues[cue_idx]
                        c_words = norm(c.get("text", "")).split()
                        matched_words += len(c_words)
                        last_end = c.get("end", last_end)
                        cue_idx += 1

                        if b_idx == len(blocks) - 1:
                            if cue_idx < len(cues):
                                continue
                        if matched_words >= target_words * 0.85:
                            break

                    block_boundaries.append((start_t, last_end))

                if len(block_boundaries) == len(blocks):
                    curr_t = 0.0
                    for i, b in enumerate(blocks):
                        s_t, e_t = block_boundaries[i]
                        b.narration_start = round(curr_t, 3)
                        remaining_blocks = len(blocks) - 1 - i
                        max_e_t = max(curr_t + 1.0, total_speech_dur - remaining_blocks * 1.0)
                        e_t = max(curr_t + 1.0, min(e_t, max_e_t))
                        if i == len(blocks) - 1:
                            e_t = max(e_t, total_speech_dur)
                        b.narration_end = round(e_t, 3)
                        b.speech_dur = round(b.narration_end - b.narration_start, 3)
                        curr_t = b.narration_end

                    blocks[-1].narration_end = round(total_speech_dur, 3)
                    blocks[-1].speech_dur = round(blocks[-1].narration_end - blocks[-1].narration_start, 3)
                    used_cues = True
            except Exception as ce:
                print(f"[Assign Narration Timing Notice] Cue match fallback: {ce}")
                used_cues = False

        if not used_cues:
            curr_t = 0.0
            for i, b in enumerate(blocks):
                w = max(1, b.word_count)
                dur = (w / total_words) * total_speech_dur
                b.speech_dur = round(dur, 3)
                b.narration_start = round(curr_t, 3)
                curr_t += dur
                b.narration_end = round(curr_t, 3)

            diff = total_speech_dur - blocks[-1].narration_end
            blocks[-1].narration_end = round(total_speech_dur, 3)
            blocks[-1].speech_dur = round(blocks[-1].narration_end - blocks[-1].narration_start, 3)

        for b in blocks:
            b.actual_duration = round(b.speech_dur, 3)
            b.is_authoritative = True

        return blocks

    @staticmethod
    def estimate_block_durations(
        blocks: List[SceneBlock],
        target_output_duration_sec: Optional[float] = None,
        language: str = "en",
        voice_speed: str = "fast"
    ) -> List[SceneBlock]:
        """
        Phase 4A: Computes pre-TTS duration estimates based on word count.
        Populates b.estimated_duration and sets pre-TTS placeholder in b.speech_dur.
        Does NOT set b.is_authoritative (remains False until actual TTS audio is synthesized).
        """
        if not blocks:
            return []
        total_words = sum(max(1, b.word_count) for b in blocks)
        if target_output_duration_sec is not None and target_output_duration_sec > 0:
            target_sec = float(target_output_duration_sec)
            for idx, b in enumerate(blocks):
                w = max(1, b.word_count)
                b.estimated_duration = round((w / max(1, total_words)) * target_sec, 3)
                b.speech_dur = b.estimated_duration
                if not b.block_id:
                    b.block_id = f"SCENE_{idx + 1}"
                b.is_authoritative = False
        else:
            base_wpm = ScriptEngine.LANGUAGE_WPM.get(language, 150)
            mult = ScriptEngine.SPEED_MULTIPLIER.get(voice_speed, 1.15)
            eff_wpm = max(50.0, base_wpm * mult)
            for idx, b in enumerate(blocks):
                w = max(1, b.word_count)
                b.estimated_duration = round((w / eff_wpm) * 60.0, 3)
                b.speech_dur = b.estimated_duration
                if not b.block_id:
                    b.block_id = f"SCENE_{idx + 1}"
                b.is_authoritative = False
        return blocks

    @staticmethod
    def build_authoritative_narration_timeline(
        blocks: List[SceneBlock],
        actual_durations: Any,
        cues: Optional[List[Dict[str, Any]]] = None,
        estimated_durations: Optional[List[float]] = None
    ) -> List[SceneBlock]:
        """
        Phase 4A: Authoritative Narration Timeline Authority.
        Establishes synthesized TTS audio duration as the sole timing authority for narration blocks,
        maintaining strict mathematical invariants and keeping source movie coordinates strictly separate
        from output narration coordinates.

        Coordinate Hierarchy:
        1. Source movie timestamps (b.movie_start, b.movie_end) = FACTUAL SOURCE ANCHORS (strictly untouched).
        2. Planned narration duration (b.estimated_duration) = PRE-TTS ESTIMATE ONLY.
        3. Actual synthesized audio duration (b.actual_duration) = AUTHORITATIVE DURATION.
        4. Final narration timeline (b.narration_start, b.narration_end) = SEQUENTIAL ACCUMULATION.

        Mathematical Invariants:
        - narration_start_0 = 0.0
        - narration_start_i = narration_end_{i-1}
        - sum(b.actual_duration) == (blocks[-1].narration_end - blocks[0].narration_start)
        - movie_start and movie_end are never modified or conflated with narration timings.
        """
        import math
        from app.services.voice_engine import VoiceEngine

        if not blocks:
            return []

        if actual_durations is None:
            raise ValueError("actual_durations cannot be None")

        # Case A: Single total duration provided (float or int)
        if isinstance(actual_durations, (int, float)):
            val = float(actual_durations)
            if not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"Invalid actual audio duration: {actual_durations}. Must be a finite positive number.")

            # Record explicit estimated durations if provided
            if estimated_durations:
                for idx, b in enumerate(blocks):
                    if idx < len(estimated_durations):
                        b.estimated_duration = round(float(estimated_durations[idx]), 3)

            return ScriptEngine.assign_narration_timing(blocks, val, cues=cues)

        # Case B: List of durations or audio file paths
        if isinstance(actual_durations, list):
            if len(actual_durations) != len(blocks):
                raise ValueError(
                    f"Block count ({len(blocks)}) does not match actual_durations count ({len(actual_durations)})."
                )

            parsed_durations: List[float] = []
            for item in actual_durations:
                if isinstance(item, str):
                    dur = VoiceEngine.get_audio_duration(item)
                    if not math.isfinite(dur) or dur <= 0.0:
                        raise ValueError(f"Audio file '{item}' yielded invalid duration: {dur}")
                    parsed_durations.append(round(dur, 3))
                elif isinstance(item, (int, float)):
                    val = float(item)
                    if not math.isfinite(val) or val <= 0.0:
                        raise ValueError(f"Invalid duration: {item}. Must be a finite positive number.")
                    parsed_durations.append(round(val, 3))
                else:
                    raise ValueError(f"Unsupported duration type in actual_durations: {type(item)}")

            curr_t = 0.0
            for idx, (b, dur) in enumerate(zip(blocks, parsed_durations)):
                # Preserve or record pre-TTS estimate
                if estimated_durations and idx < len(estimated_durations):
                    b.estimated_duration = round(float(estimated_durations[idx]), 3)
                elif b.estimated_duration <= 0.0:
                    if b.speech_dur > 0.0:
                        b.estimated_duration = round(b.speech_dur, 3)

                b.actual_duration = dur
                b.speech_dur = dur
                b.narration_start = round(curr_t, 3)
                curr_t = round(curr_t + dur, 3)
                b.narration_end = curr_t
                b.is_authoritative = True
                if not b.block_id:
                    b.block_id = f"SCENE_{idx + 1}"

            # Strict verification of sum invariant
            total_actual = round(sum(b.actual_duration for b in blocks), 3)
            timeline_span = round(blocks[-1].narration_end - blocks[0].narration_start, 3)
            assert abs(total_actual - timeline_span) < 1e-3, (
                f"Timeline invariant failed: sum(actual)={total_actual} != span={timeline_span}"
            )

            return blocks

        raise ValueError(f"Invalid type for actual_durations: {type(actual_durations)}")

    @staticmethod
    def detect_duration_mismatch(blocks: List[SceneBlock]) -> Dict[str, Any]:
        """
        Phase 4A: Observability mechanism comparing estimated vs actual durations.
        Calculates absolute and relative deltas globally and per block.
        """
        if not blocks:
            return {
                "total_estimated_sec": 0.0,
                "total_actual_sec": 0.0,
                "absolute_delta": 0.0,
                "relative_delta": 0.0,
                "max_block_delta": 0.0,
                "block_mismatches": [],
                "is_authoritative": False
            }

        total_est = round(sum(b.estimated_duration for b in blocks), 3)
        total_act = round(sum(b.actual_duration if b.is_authoritative else b.speech_dur for b in blocks), 3)
        abs_delta = round(total_act - total_est, 3)
        rel_delta = round(abs_delta / total_est, 4) if total_est > 0 else 0.0

        block_mismatches = []
        max_delta = 0.0
        all_auth = True

        for idx, b in enumerate(blocks):
            act = b.actual_duration if b.is_authoritative else b.speech_dur
            est = b.estimated_duration
            b_abs = round(act - est, 3)
            b_rel = round(b_abs / est, 4) if est > 0 else 0.0
            if abs(b_abs) > max_delta:
                max_delta = abs(b_abs)
            if not b.is_authoritative:
                all_auth = False
            block_mismatches.append({
                "block_index": idx,
                "block_id": b.block_id or f"SCENE_{idx + 1}",
                "estimated_duration": est,
                "actual_duration": act,
                "absolute_delta": b_abs,
                "relative_delta": b_rel,
                "is_authoritative": b.is_authoritative
            })

        return {
            "total_estimated_sec": total_est,
            "total_actual_sec": total_act,
            "absolute_delta": abs_delta,
            "relative_delta": rel_delta,
            "max_block_delta": round(max_delta, 3),
            "block_mismatches": block_mismatches,
            "is_authoritative": all_auth
        }


    @staticmethod
    def extract_sfx_cues(raw_script: str, total_duration: float = 60.0) -> List[Dict[str, Any]]:
        """
        Extracts emotional [SFX: ...] tags from the script and maps them to chronological timestamps.
        Supported tags: [SFX: HEARTBEAT], [SFX: SUB_BOOM], [SFX: WHOOSH], [SFX: CLOCK_TICK], [SFX: CASH_CHIME].
        """
        if not raw_script:
            return []

        alias_map = {
            "heartbeat": "heartbeat", "heart_beat": "heartbeat", "pulse": "heartbeat",
            "sub_boom": "sub_boom", "boom": "sub_boom", "impact": "sub_boom", "explosion": "sub_boom",
            "whoosh": "whoosh", "transition": "whoosh", "swoosh": "whoosh",
            "clock_tick": "clock_tick", "tick": "clock_tick", "countdown": "clock_tick",
            "cash_chime": "cash_chime", "chime": "cash_chime", "ding": "cash_chime",
            "riser": "sub_boom", "dramatic_riser": "sub_boom", "suspense": "heartbeat"
        }

        volume_map = {
            "heartbeat": 0.45,
            "sub_boom": 0.55,
            "whoosh": 0.40,
            "clock_tick": 0.35,
            "cash_chime": 0.40
        }

        cues = []
        clean_len = max(1, len(raw_script))
        dur = max(5.0, total_duration)

        matches = list(re.finditer(r'\[SFX:\s*([a-zA-Z0-9_\s-]+)\]', raw_script, re.IGNORECASE))
        for m in matches:
            tag_raw = m.group(1).strip().lower().replace(" ", "_")
            canonical = alias_map.get(tag_raw, "whoosh")
            vol = volume_map.get(canonical, 0.40)

            # Position relative to entire script text
            char_pos = m.start()
            t_sec = (char_pos / clean_len) * dur
            t_sec = max(0.5, min(dur - 2.0, t_sec))
            cues.append({
                "time": round(t_sec, 2),
                "sfx": canonical,
                "volume": vol
            })

        cues.sort(key=lambda x: x["time"])
        return cues

    LANGUAGE_WPM = {
        "ur": 200,  # Urdu (Edge-TTS Asad/Uzma speaks ~195-205 WPM at 1.0x)
        "hi": 160,  # Hindi (Edge-TTS Madhur/Swara speaks ~155-165 WPM at 1.0x)
        "es": 165,  # Spanish (Edge-TTS Alvaro/Elvira speaks ~160-170 WPM)
        "pt": 160,  # Portuguese (Edge-TTS Antonio/Francisca ~155-165 WPM)
        "id": 155,  # Indonesian (Edge-TTS Ardi/Gadis ~150-160 WPM)
        "vi": 160,  # Vietnamese (Edge-TTS NamMinh/HoaiMy ~155-165 WPM)
        "en": 150,  # English (Edge-TTS Christopher/Guy/Aria ~145-155 WPM)
        "fr": 150,  # French (Edge-TTS Henri/Denise ~145-155 WPM)
        "it": 155,  # Italian (Edge-TTS Diego/Elsa ~150-160 WPM)
        "tr": 155,  # Turkish (Edge-TTS Ahmet/Emel ~150-160 WPM)
        "de": 140,  # German (Edge-TTS Conrad/Katja ~135-145 WPM)
        "ar": 145,  # Arabic (Edge-TTS Shakir/Hamed ~140-150 WPM)
        "ru": 135,  # Russian (Edge-TTS Dmitry/Svetlana ~130-140 WPM)
        "th": 155,  # Thai (Edge-TTS Niwat/Premwadee ~150-160 WPM)
        "ja": 280,  # Japanese characters/min (Edge-TTS Keita/Nanami)
        "ko": 200,  # Korean blocks/min (Edge-TTS InJoon/SunHi)
    }

    SPEED_MULTIPLIER = {
        "normal": 1.0,
        "fast": 1.15,
        "ultra_fast": 1.25,
    }

    @staticmethod
    def calculate_target_words(duration_mins: int, voice_speed: str = "fast", target_lang: str = "en") -> int:
        """Calculates spoken target word count dynamically based on duration, language pace, and speed without caps."""
        base_wpm = ScriptEngine.LANGUAGE_WPM.get(target_lang, 150)
        mult = ScriptEngine.SPEED_MULTIPLIER.get(voice_speed, 1.15)
        d_mins = max(1, int(duration_mins)) if duration_mins else 5
        return max(100, int(round(d_mins * base_wpm * mult)))

    @staticmethod
    def calculate_dynamic_pacing(source_duration_sec: float) -> Dict[str, Any]:
        """
        Feature #2: Dynamic Pacing & Scene Segmentation Formula.
        Calculates optimal explainer duration and scene block count based on source length.
        """
        sec = float(source_duration_sec) if source_duration_sec and source_duration_sec > 0 else 3600.0
        
        if sec < 900:  # Short Video (< 15 mins)
            target_duration_mins = 3
            target_scenes = 5
            category = "short"
        elif sec <= 2700:  # Medium / Drama (15 to 45 mins)
            target_duration_mins = 5
            target_scenes = 7
            category = "medium"
        else:  # Full Movie (1 to 3+ hours)
            target_duration_mins = 8
            target_scenes = 11
            category = "feature_film"

        return {
            "source_duration_sec": sec,
            "target_duration_mins": target_duration_mins,
            "target_scenes": target_scenes,
            "category": category,
            "rule_description": f"{category.upper()}: {target_duration_mins} mins explainer across ~{target_scenes} scenes"
        }

    @staticmethod
    def partition_timeline(
        source_duration_sec: float,
        target_duration_mins: int = 10,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Universal 5-Act Timeline Milestone Partitioner with Smart Transcript-Driven Boundary Detection.
        If dialogue_timeline is available, anchors the start boundary to the first spoken dialogue
        (skipping empty intro logos and silence) and the end boundary to the final spoken dialogue
        (preserving 100% of the climax while naturally omitting silent rolling credits).
        """
        total_sec = float(source_duration_sec) if source_duration_sec and source_duration_sec > 60 else float(target_duration_mins * 60 * 6)

        start_boundary_s = 0.0
        end_boundary_s = total_sec

        if dialogue_timeline and len(dialogue_timeline) > 0:
            first_cue_start = float(dialogue_timeline[0].get("start", 0.0))
            last_cue_end = max((float(c.get("end", 0.0)) for c in dialogue_timeline), default=0.0)

            # Intro guard: If first dialogue is after initial logos/silence, skip the blank intro
            if first_cue_start > 15.0:
                start_boundary_s = max(0.0, first_cue_start - 5.0)

            # True climax guard: End boundary follows the last spoken dialogue + 15s scene resolution
            if last_cue_end > 60.0:
                end_boundary_s = min(total_sec, last_cue_end + 15.0)
        else:
            # Fallback if no dialogue timeline provided
            if total_sec > 600:
                credits_margin = max(120.0, min(total_sec * 0.065, 360.0))
                end_boundary_s = max(300.0, total_sec - credits_margin)

        active_story_sec = max(60.0, end_boundary_s - start_boundary_s)

        def sec_to_ts(s: float) -> str:
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02d}:{sec:02d}"

        acts_def = [
            ("Act 1", "Opening Hook & Inciting Incident", 0.0, 0.20, "20%"),
            ("Act 2A", "Rising Stakes & Early Conflict", 0.20, 0.45, "25%"),
            ("Act 2B", "Midpoint Twist & Deep Crisis", 0.45, 0.70, "25%"),
            ("Act 3", "The Climax & Killer Reveal / Final Confrontation", 0.70, 0.90, "20%"),
            ("Epilogue", "Resolution, Character Fate & Short Review", 0.90, 1.00, "10%"),
        ]

        milestones = []
        for act_name, label, start_ratio, end_ratio, budget_pct in acts_def:
            start_s = round(start_boundary_s + active_story_sec * start_ratio)
            end_s = round(end_boundary_s) if end_ratio == 1.00 else round(start_boundary_s + active_story_sec * end_ratio)
            milestones.append({
                "act": act_name,
                "label": label,
                "start_sec": start_s,
                "end_sec": end_s,
                "timestamp_range": f"{sec_to_ts(start_s)} - {sec_to_ts(end_s)}",
                "budget_pct": budget_pct
            })
        return milestones

    @staticmethod
    def validate_script_integrity(
        script_text: str,
        source_duration_sec: float = 0,
        target_duration_mins: int = 10,
        target_lang: str = "en",
        voice_speed: str = "fast",
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None,
        evidence_packets: Optional[List[Any]] = None,
        story_plan: Optional[List[Any]] = None,
        return_details: bool = False
    ) -> Union[Tuple[bool, str], Tuple[bool, str, Dict[str, Any]]]:
        """
        Universal Automated Quality Gatekeeper.
        Verifies:
        1. Timeline Coverage: Last scene timestamp covers >= 85% of source video timeline.
        2. Word Budget Drift: Actual words are within acceptable range (not severely under-budget).
        3. Structural Pillars: Valid scene format and narrative closure.
        4. Phase 6G.3: Storyboard Source Chronology Gate (monotonic non-decreasing source evidence).
        """
        if not script_text or not script_text.strip():
            msg = "Script is empty."
            details = {"is_valid": False, "error": "empty_script", "failure_type": "empty_script", "violations": []}
            return (False, msg, details) if return_details else (False, msg)

        # 1. Timeline Coverage Check
        ts_matches = re.findall(r'(?:\[(?:SCENE:\s*)?|\b)(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\]?', script_text)
        max_end_sec = 0.0
        if ts_matches:
            for m in ts_matches:
                end_m, end_s = int(m[2]), int(m[3])
                end_sec = end_m * 60 + end_s
                if end_sec > max_end_sec:
                    max_end_sec = end_sec

        if source_duration_sec and source_duration_sec > 120:
            if max_end_sec == 0:
                msg = "Missing scene timestamps across narrative."
                details = {"is_valid": False, "error": "missing_timestamps", "failure_type": "missing_timestamps", "violations": []}
                return (False, msg, details) if return_details else (False, msg)
            coverage_pct = max_end_sec / source_duration_sec
            if coverage_pct < 0.85:
                msg = f"Timeline coverage insufficient (covers {coverage_pct*100:.1f}%, minimum required 85%). Missing ending/climax."
                details = {"is_valid": False, "error": "insufficient_coverage", "failure_type": "insufficient_coverage", "coverage_pct": coverage_pct, "violations": []}
                return (False, msg, details) if return_details else (False, msg)

        # 2. Word Budget Check (Measured on clean spoken narration)
        clean_narr, _, _ = ScriptEngine.parse_storyboard(script_text)
        spoken_words = len(clean_narr.split()) if clean_narr else len(script_text.split())
        target_words = ScriptEngine.calculate_target_words(target_duration_mins, voice_speed, target_lang)
        min_allowed = int(target_words * 0.55) if target_duration_mins >= 5 else int(target_words * 0.50)
        if spoken_words < min_allowed:
            msg = f"Script is severely under-budget ({spoken_words} spoken words, minimum expected {min_allowed} for {target_duration_mins}m video)."
            details = {"is_valid": False, "error": "under_budget", "failure_type": "under_budget", "spoken_words": spoken_words, "min_allowed": min_allowed, "violations": []}
            return (False, msg, details) if return_details else (False, msg)

        # 3. Phase 6G.3: Storyboard Source Chronology Gate
        chron_details = {"is_valid": True, "violations": [], "failure_type": None}
        if (dialogue_timeline and len(dialogue_timeline) > 0) or (evidence_packets and len(evidence_packets) > 0):
            val_blocks = ScriptEngine.parse_storyboard_blocks(
                raw_script=script_text,
                dialogue_timeline=dialogue_timeline,
                evidence_packets=evidence_packets,
                story_plan=story_plan,
                enforce_source_provenance=True
            )
            is_chron_valid, chron_msg, chron_details = ScriptEngine.validate_storyboard_chronology(
                blocks=val_blocks,
                dialogue_timeline=dialogue_timeline,
                evidence_packets=evidence_packets,
                story_plan=story_plan
            )
            if not is_chron_valid:
                res_msg = f"Script failed chronology gate: {chron_msg}"
                return (False, res_msg, chron_details) if return_details else (False, res_msg)

        res_msg = "Script passed all universal integrity gates."
        return (True, res_msg, chron_details) if return_details else (True, res_msg)

    @staticmethod
    def build_prompt_for_genre(
        genre: str,
        title: str,
        description: str,
        subs_text: str,
        target_lang: str = "en",
        duration_mins: int = 5,
        plot_summary: str = "",
        persona: str = "hollywood_trailer",
        mood: str = "suspense",
        spoiler_mode: str = "full_recap",
        voice_speed: str = "fast",
        source_video_duration_sec: float = 0,
        story_beats: Optional[List[Dict[str, Any]]] = None,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Builds tailored, multi-act prompt blueprint for universal video genres with strict length quotas."""
        lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["en"])
        lang_name = lang_info["name"]
        target_words = ScriptEngine.calculate_target_words(duration_mins, voice_speed, target_lang)

        act1_words = int(round(target_words * 0.25))
        act2_words = int(round(target_words * 0.50))
        act3_words = int(round(target_words * 0.25))

        source_pacing_note = ""
        if source_video_duration_sec and source_video_duration_sec > 60:
            s_mins = round(source_video_duration_sec / 60, 1)
            ratio = round(s_mins / max(1, duration_mins), 1)
            source_pacing_note = f"\nSource Video Total Duration: {s_mins} minutes (Compression Ratio: {ratio}x).\nCover the entire narrative from opening events to the final climax proportionally."

        genre_configs = {
            "biography": {
                "role": f"World-Class Biographical Storyteller & Documentarian in {lang_name} ({lang_info['native']})",
                "label": "Biography & Real Story",
                "structure": f"""- Opening Hook (First 5 seconds): The dramatic defining moment, paradox, or highest achievement of this icon.
- Act 1 (~{act1_words} words): Early Life, Humble Beginnings, formative struggles, and their initial spark.
- Act 2 (~{act2_words} words): The Breakthrough, relentless grit, pivotal turning points, failures, and astronomical rise.
- Act 3 (~{act3_words} words): Enduring Legacy, life-defining lessons, and their eternal mark on history.
- Call to Action: Punchy closing inspiring viewers to like and subscribe for more legendary true stories!"""
            },
            "documentary": {
                "role": f"Investigative Crime & Historical Documentary Chronicler in {lang_name} ({lang_info['native']})",
                "label": "Investigative / True Crime / Historical Documentary",
                "structure": f"""- Opening Hook (First 5 seconds): The terrifying anomaly, unsolved crime, or historical turning point.
- Act 1 (~{act1_words} words): The Inciting Mystery, initial shock, discovery of evidence, and early investigations.
- Act 2 (~{act2_words} words): Deep Forensic Breakdown, conflicting testimonies, cover-ups, and escalating theories.
- Act 3 (~{act3_words} words): The Breakthrough, hard facts, lingering mysteries, and societal aftermath.
- Call to Action: Thought-provoking outro urging viewers to comment their theories and subscribe!"""
            },
            "true_crime": {
                "role": f"Investigative True Crime & Forensic Documentarian in {lang_name} ({lang_info['native']})",
                "label": "True Crime & Forensic Investigation",
                "structure": f"""- Opening Hook (First 5 seconds): The chilling crime scene, shocking disappearance, or forensic contradiction.
- Act 1 (~{act1_words} words): The Incident & First 48 Hours, timeline of disappearance/crime, and initial suspects.
- Act 2 (~{act2_words} words): Cold Case Reopened & Forensic Clues, digital forensics, DNA revelations, and interrogations.
- Act 3 (~{act3_words} words): The Trial, Final Confession / Verdict, and unsolved questions.
- Call to Action: Gripping outro inviting viewers to discuss theories in comments!"""
            },
            "tech_science": {
                "role": f"Visionary Tech & Science Chronicler in {lang_name} ({lang_info['native']})",
                "label": "Science, Technology & Future Innovation",
                "structure": f"""- Opening Hook (First 5 seconds): The mind-bending breakthrough, paradigm shift, or existential threat.
- Act 1 (~{act1_words} words): The Problem / Origin Story, why previous paradigms failed, and the breakthrough idea.
- Act 2 (~{act2_words} words): How It Works & Engineering Genius, the breakthroughs, obstacles, and revolutionary tech.
- Act 3 (~{act3_words} words): Future Impact & Society, ethical questions, what happens next.
- Call to Action: Exciting closing inviting viewers to share what tech they want explained next!"""
            },
            "video_essay": {
                "role": f"Master Cultural Critic & Visual Essayist in {lang_name} ({lang_info['native']})",
                "label": "Cultural Video Essay & Philosophy",
                "structure": f"""- Opening Hook (First 5 seconds): The central paradox or cultural critique that challenges common beliefs.
- Act 1 (~{act1_words} words): The Thesis & Cultural Context, breaking down the illusion.
- Act 2 (~{act2_words} words): The Evidence, cinematic/historical parallels, psychology, and hidden motifs.
- Act 3 (~{act3_words} words): The Synthesis, why this matters today, and philosophical takeaway.
- Call to Action: Thoughtful closing question to spark high-engagement comments!"""
            },
            "movie_recap": {
                "role": f"Master Hollywood Cinema Storyteller & Explainer in {lang_name} ({lang_info['native']})",
                "label": "Cinematic Movie Story Recap",
                "structure": f"""- Opening Hook (First 5 seconds): The high-stakes inciting incident or intense teaser moment.
- Act 1 (~{act1_words} words): Protagonist introduction, world setup, the inciting event, and initial stakes.
- Act 2 (~{act2_words} words): The Escalation, rising tension, plot twists, betrayals, and deep crisis.
- Act 3 (~{act3_words} words): The Climax, ultimate confrontation, killer/mastermind reveal, and full resolution.
- Short Review & Outro: A 15-20 second review & moral takeaway followed by like & subscribe call-to-action!"""
            }
        }

        cfg = genre_configs.get(genre, genre_configs["movie_recap"])

        persona_map = {
            "hollywood_trailer": "Epic, dramatic, cinematic, high-stakes with breathless pacing.",
            "viral_fast": "Hyper-fast, punchy, high-energy, modern TikTok/Reels retention style.",
            "sarcastic_roaster": "Witty, humorous, sarcastic commentary pointing out absurd plot choices.",
            "documentary": "Serious, objective, chilling, investigative tone like true crime docuseries."
        }
        persona_guide = persona_map.get(persona, persona_map["hollywood_trailer"])

        spoiler_rule = "Deliver the complete ending, final plot twists, and character fates clearly without withholding information." if spoiler_mode == "full_recap" else "Build maximum suspense up to the final cliffhanger without revealing the ultimate ending!"

        beats_section = ""
        if story_beats:
            beats_lines = ["\nCHRONOLOGICAL STORY BEATS DETECTED BY DETECTIVE AGENT:"]
            for b in story_beats:
                beat_num = b.get("beat", "")
                ts = b.get("time_range") or b.get("timestamp", "")
                btitle = b.get("title", "")
                action = b.get("action", "")
                line = f"- Beat {beat_num} [{ts}]: {btitle}"
                if action:
                    line += f" - {action}"
                beats_lines.append(line)
            beats_section = "\n".join(beats_lines) + "\n"

        # Compress transcript into full-movie roadmap & build Phase 3B evidence packets + story plan
        if (subs_text and subs_text.strip()) or (dialogue_timeline and len(dialogue_timeline) > 0):
            roadmap = ScriptEngine.compress_transcript_to_roadmap(
                subs_text=subs_text or "",
                total_movie_dur=float(source_video_duration_sec or (duration_mins * 60.0 * 6.0)),
                target_output_dur_mins=duration_mins,
                dialogue_timeline=dialogue_timeline
            )
            fallback_sample = ScriptEngine.extract_balanced_transcript_sample(subs_text or "", max_chars=4000)

            # Phase 3B: Grounded Evidence Packets + Story Plan
            evidence_packets = ScriptEngine.build_evidence_packets(
                subs_text=subs_text or "",
                total_movie_dur=float(source_video_duration_sec or (duration_mins * 60.0 * 6.0)),
                target_output_dur_mins=duration_mins,
                dialogue_timeline=dialogue_timeline
            )
            story_plan = ScriptEngine.create_grounded_story_plan(
                evidence_packets=evidence_packets,
                target_duration_mins=duration_mins,
                genre=genre,
                target_lang=target_lang,
                voice_speed=voice_speed
            )

            grounding_sections = []
            if roadmap:
                grounding_sections.append(f"Full-Movie Dialogue & Event Roadmap (Beginning to Climax):\n{roadmap}")
            if evidence_packets:
                packets_formatted = ScriptEngine.format_evidence_packets_for_prompt(evidence_packets[:45])
                grounding_sections.append(f"=== MANDATORY SOURCE EVIDENCE PACKETS (FACTUAL AUTHORITY) ===\n{packets_formatted}")
            if story_plan:
                plan_formatted = ScriptEngine.format_story_plan_for_prompt(story_plan[:45])
                grounding_sections.append(f"=== MANDATORY CHRONOLOGICAL STORY PLAN (STRUCTURAL AUTHORITY) ===\n{plan_formatted}")

            transcript_section = "\n\n".join(grounding_sections) if grounding_sections else f"Source Transcript Highlights:\n{fallback_sample}"
        else:
            transcript_section = "Source Transcript: None provided. Structure narrative from beginning to climax based on plot guide."

        milestones = ScriptEngine.partition_timeline(source_video_duration_sec, duration_mins, dialogue_timeline=dialogue_timeline)
        milestone_lines = ["\nMANDATORY 5-ACT TIMELINE PROGRESSION (FULL MOVIE COVERAGE REQUIRED):"]
        milestone_lines.append("You MUST structure your narrative across these chronological acts and ensure your timestamps reach the final climax and ending:")
        for m in milestones:
            milestone_lines.append(f"- {m['act']} [{m['timestamp_range']}]: {m['label']} (Target Word Budget: ~{m['budget_pct']})")
        milestone_lines.append(f"CRITICAL MILESTONE LOCK: The final scene MUST reach the Epilogue timeframe ({milestones[-1]['timestamp_range']}) to deliver the full climax and resolution!")
        milestone_section = "\n".join(milestone_lines) + "\n"

        ep_info = ScriptEngine.detect_episode_info(title, description)
        episodic_instructions = ""
        if ep_info.get("is_episodic"):
            c_num = ep_info["episode_num"]
            n_num = ep_info["next_episode_num"]
            episodic_instructions = f"""
8. MANDATORY EPISODIC CLIFFHANGER & NEXT EPISODE CTA:
   - This video covers Episode {c_num}!
   - Establish character stakes and interpersonal conflicts clearly in Act 1.
   - Act 3 MUST end with an intense cliffhanger on the major unanswered dramatic question of this episode!
   - Your closing Call-To-Action (CTA) in {lang_name} MUST explicitly instruct viewers to watch Episode {n_num} on the channel:
     "To find out what happens next, watch Episode {n_num} right now on our channel! Don't forget to like and subscribe!"
     (In Urdu: "کہانی کا اگلا سنسنی خیز موڑ جاننے کے لیے Episode {n_num} ابھی ہمارے چینل پر دیکھیں! ویڈیو کو لائک کریں اور چینل کو سبسکرائب کریں!")
"""

        prompt = f"""You are a {cfg['role']}.
Title: {title}
Genre: {cfg['label']}
Plot Guide / Extra Notes: {plot_summary}
Description / Background: {description[:800]}
{transcript_section}
{beats_section}
{milestone_section}
OBJECTIVES:
1. Write a captivating, immersive THIRD-PERSON {genre} narrative in natural, colloquial {lang_name}.
   - STORY ARCHITECTURE & CHARACTER MOTIVATION: Do NOT merely produce a chronological list of isolated dialogue quotes. In Act 1, introduce the protagonist and main figures, explain the premise/logline and dramatic conflict (who are they, what is their feud or goal?), and weave spoken dialogues naturally into narrative sentences (e.g. 'As the party spiraled into chaos, Dawood coldly warned Arbaaz: ...').
2. Tone & Master Storyteller Voice: {persona_guide} (Overall Mood: {mood.upper()}).
   - CONVERSATIONAL STORYTELLING: Deliver the story in an engaging, conversational tone — as if you are telling an intense, captivating story directly to a friend. Maintain suspense, dramatic momentum, and curiosity throughout.
3. MANDATORY LENGTH REQUIREMENT: You MUST write at least {target_words} spoken words to match a full {duration_mins}-minute video (at {voice_speed} pace). DO NOT summarize briefly or skip scenes. Elaborate on dialogues, character emotions, and scene details.
4. Narrative Act Quotas:
- Hook & Act 1 Target: ~{act1_words} words
- Act 2 Target: ~{act2_words} words
- Act 3 Target: ~{act3_words} words
5. Ending Rule & Short Review: {spoiler_rule}
   - In the final 15-20 seconds of Act 3, provide a punchy conclusion and short review / moral takeaway summarizing the core theme or fate of the characters before the call-to-action!
6. DIALOGUE & CHARACTER QUOTING: You MUST naturally quote and reference key dialogues and character exchanges throughout the story (e.g. hero shouts: 'Get out of the way!' while firing; heroine reveals the truth: 'He was never on our side'; villain threatens...). Narrate critical turning-point actions (explosions, gunfire, car chases, confrontations) at their exact timestamps from the roadmap. This creates an authentic, emotionally charged story and guarantees perfect synchronization with the movie footage.
7. STRICT ANTI-CODE RULE: Do NOT include code blocks, python scripts, unit tests, or markdown backticks under any circumstance. Output pure spoken storytelling narration.
{episodic_instructions}
{source_pacing_note}

NARRATIVE STRUCTURE:
{cfg['structure']}

FORMATTING & AI DIRECTOR REQUIREMENTS:
1. SCENE TIMESTAMPS & DIALOGUE ANCHORING: Every narrative scene block MUST strictly follow this exact structure:
   [SCENE: MM:SS - MM:SS]
   [DIALOGUE_REF: "exact quote or dialogue from source transcript/roadmap"]
   [VOICEOVER]
   Your narrative text here...

   - MANDATORY DIALOGUE REFERENCE: You MUST include [DIALOGUE_REF: "..."] with the exact quote or phrase from the source transcript/roadmap that occurs at this moment. The video studio relies on this exact reference to lock the visual cut with 100% precision.
   - SOURCE-BOUND INTEGRITY: Do NOT invent, paraphrase, or hallucinate fictional dialogue quotes in [DIALOGUE_REF: "..."]. Every dialogue reference must match an actual spoken sentence from the Source Evidence Packets or Roadmap above. If a scene depicts visual action without spoken dialogue, omit [DIALOGUE_REF: ...] entirely. Any invented dialogue reference will be automatically invalidated.
   - Anchor your timestamps to the chronological Full-Movie Roadmap and 5-Act Milestones above!
   - Match your timestamps directly to the actual dialogues/events in the Roadmap. When narrating what a character says, or a major action (gunfire, chase, explosion, confrontation), use the real timestamp from the dialogue roadmap where that event happens.
   - Do NOT invent arbitrary or fictional timestamps. The video studio cuts the exact video footage at these timestamps to sync with your voiceover!
   - Every scene MUST begin with [SCENE: MM:SS - MM:SS] followed by [DIALOGUE_REF: "..."] and [VOICEOVER].
   - The scene timestamps MUST progress chronologically across the entire film from Act 1 (opening) through Act 2 (middle) to Act 3 (climax) and Epilogue (ending).
   - NEVER stay in the first 10 or 50 minutes of the movie. Visuals are auto-sliced from these exact timestamps!
2. EMOTIONAL SFX CUES: At key emotional moments, insert sound cues inside brackets:
   - [SFX: HEARTBEAT] for tension, suspicion, or creeping danger.
   - [SFX: SUB_BOOM] for sudden shocking reveals, jumpscares, or plot twists.
   - [SFX: WHOOSH] for rapid chapter or scene transitions.
   - [SFX: CLOCK_TICK] for racing against time or countdowns.
3. Keep the narration natural and engaging; the voice engine will speak the story while our studio automatically cuts the corresponding scenes and triggers the sound effects!
"""
        return prompt

    @staticmethod
    def generate_script(
        title: str,
        description: str,
        subs_text: str,
        target_lang: str = "en",
        persona: str = "hollywood_trailer",
        mood: str = "suspense",
        format_mode: str = "reels_parts",
        num_parts: int = 3,
        duration_mins: int = 3,
        spoiler_mode: str = "full_recap",
        plot_summary: str = "",
        gemini_api_key: Optional[str] = None,
        voice_speed: str = "fast",
        genre: str = "movie_recap",
        source_video_duration_sec: float = 0,
        story_beats: Optional[List[Dict[str, Any]]] = None,
        openai_api_key: Optional[str] = None,
        ai_provider: str = "auto",
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        Generates a viral cinematic storytelling recap or universal explainer in any of the 15+ supported languages.
        Guarantees length precision with automatic multi-act verification and expansion.
        """
        api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        target_words = ScriptEngine.calculate_target_words(duration_mins, voice_speed, target_lang)

        # Phase 3B: Grounded Evidence Packets + Story Plan Construction & Validation
        evidence_packets = []
        story_plan = []
        is_plan_valid = True
        plan_validation_report = "No source provided"
        if (subs_text and subs_text.strip()) or (dialogue_timeline and len(dialogue_timeline) > 0):
            evidence_packets = ScriptEngine.build_evidence_packets(
                subs_text=subs_text or "",
                total_movie_dur=float(source_video_duration_sec or (duration_mins * 60.0 * 6.0)),
                target_output_dur_mins=duration_mins,
                dialogue_timeline=dialogue_timeline
            )
            story_plan = ScriptEngine.create_grounded_story_plan(
                evidence_packets=evidence_packets,
                target_duration_mins=duration_mins,
                genre=genre,
                target_lang=target_lang,
                voice_speed=voice_speed
            )
            is_plan_valid, plan_validation_report, _ = ScriptEngine.validate_story_plan(story_plan, evidence_packets)

        # Pass 1: If story_beats not provided but subs_text available, extract story beats via 9Router
        if story_beats is None and subs_text:
            try:
                from app.services.nine_router_client import is_ninerouter_available, extract_story_beats_with_9router
                if is_ninerouter_available(timeout_sec=5.0):
                    story_beats = extract_story_beats_with_9router(
                        title=title,
                        dialogues_text=subs_text,
                        genre=genre,
                        duration_sec=source_video_duration_sec
                    )
            except Exception:
                pass

        prompt = ScriptEngine.build_prompt_for_genre(
            genre=genre,
            title=title,
            description=description,
            subs_text=subs_text,
            target_lang=target_lang,
            duration_mins=duration_mins,
            plot_summary=plot_summary,
            persona=persona,
            mood=mood,
            spoiler_mode=spoiler_mode,
            voice_speed=voice_speed,
            source_video_duration_sec=source_video_duration_sec,
            story_beats=story_beats,
            dialogue_timeline=dialogue_timeline
        )

        if format_mode == "reels_parts" and num_parts > 1:
            prompt += f"""\nDivide the story into {num_parts} distinct parts (Part 1 to Part {num_parts}).
Each part must begin with a powerful hook.
Separate each part strictly with '===PART===' on its own line."""

        # 0. Check if active provider is Gemini or Custom via ai_router
        try:
            from app.services.ai_router import load_ai_settings, generate_narrative_text
            ai_cfg = load_ai_settings()
            current_active = ai_cfg.get("active_provider", "9router")
            if current_active in ("gemini", "custom"):
                lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["en"])
                system_instruction = f"You are an elite, world-class viral YouTube movie & drama narrator and storyboard director in natural colloquial {lang_info['name']}."
                gen_text = generate_narrative_text(prompt, system_prompt=system_instruction, max_tokens=4000)
                if gen_text and len(gen_text.strip()) > 80:
                    gen_text = ScriptEngine.strip_code_and_developer_artifacts(gen_text)
                    gen_text = ScriptEngine.clamp_script_word_budget(
                        gen_text.strip(),
                        target_duration_mins=duration_mins,
                        target_lang=target_lang,
                        voice_speed=voice_speed
                    )
                    clean_narr_g, _, _ = ScriptEngine.parse_storyboard(gen_text)
                    spoken_word_count_g = len(clean_narr_g.split()) if clean_narr_g else len(gen_text.split())
                    hook_metrics_g = ScriptEngine.calculate_hook_score(gen_text, target_lang)
                    p_model = ai_cfg["providers"][current_active].get("model", current_active)
                    return {
                        "success": True,
                        "model": f"{current_active}:{p_model}",
                        "script": gen_text.strip(),
                        "language": target_lang,
                        "genre": genre,
                        "target_words": target_words,
                        "actual_words": spoken_word_count_g,
                        "raw_words": len(gen_text.split()),
                        "hook_score": hook_metrics_g,
                        "story_beats": story_beats or [],
                        "format_mode": format_mode,
                        "num_parts": num_parts,
                        "audio_mode": audio_mode,
                        "evidence_packets": [p.to_dict() if hasattr(p, "to_dict") else p for p in evidence_packets],
                        "story_plan": [s.to_dict() if hasattr(s, "to_dict") else s for s in story_plan],
                        "is_plan_valid": is_plan_valid,
                        "plan_validation_report": plan_validation_report
                    }
        except Exception as e:
            print(f"[AIRouter Dispatch Notice] {e}")

        # 0b. Attempt generation via OpenAI ChatGPT (GPT-4o) if requested or available
        try:
            from app.services.openai_client import is_openai_available, call_chatgpt_llm, load_openai_settings
            cfg_oa = load_openai_settings()
            oa_key = (openai_api_key or cfg_oa.get("api_key", "")).strip()
            use_openai = bool(oa_key and (ai_provider in ("openai", "auto") or is_openai_available()))
            if use_openai:
                lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["en"])
                system_instruction = f"You are an elite, world-class viral YouTube movie & drama narrator and storyboard director in natural colloquial {lang_info['name']}."
                gpt_model = cfg_oa.get("model", "gpt-4o")

                def oa_gen(p_str: str) -> Optional[str]:
                    return call_chatgpt_llm(
                        prompt=p_str,
                        system_prompt=system_instruction,
                        model=gpt_model,
                        max_tokens=4000,
                        api_key=oa_key
                    )

                def oa_expand(s_str: str, actual_w: int) -> Optional[str]:
                    if duration_mins >= 3 and actual_w < int(target_words * 0.80):
                        exp_prompt = f"""The following {lang_info['name']} script is only {actual_w} words, but the video duration requires AT LEAST {target_words} words:

--- CURRENT SCRIPT ---
{s_str}
--- END ---

TASK: Elaborate, expand and enrich the story across Act 1, Act 2, and Act 3 with detailed character dialogues, dramatic internal monologues, intense scene descriptions, and escalating emotional stakes to reach {target_words} words. Return the complete, expanded narrative with milestone timestamp brackets like [01:15 - 02:30]."""
                        try:
                            return call_chatgpt_llm(prompt=exp_prompt, system_prompt=system_instruction, model=gpt_model, max_tokens=4000, api_key=oa_key)
                        except Exception:
                            return None
                    return None

                gpt_text, is_valid, val_report, attempts, val_details = ScriptEngine.generate_script_with_chronology_guard(
                    generate_fn=oa_gen,
                    initial_prompt=prompt,
                    duration_mins=duration_mins,
                    voice_speed=voice_speed,
                    target_lang=target_lang,
                    source_video_duration_sec=source_video_duration_sec,
                    dialogue_timeline=dialogue_timeline,
                    evidence_packets=evidence_packets,
                    story_plan=story_plan,
                    expand_fn=oa_expand if (duration_mins >= 3) else None
                )
                if gpt_text:
                    clean_narr_oa, _, _ = ScriptEngine.parse_storyboard(gpt_text)
                    spoken_word_count_oa = len(clean_narr_oa.split()) if clean_narr_oa else len(gpt_text.split())
                    hook_metrics = ScriptEngine.calculate_hook_score(gpt_text, target_lang)
                    res = {
                        "success": True,
                        "model": f"openai:{gpt_model}",
                        "script": gpt_text.strip(),
                        "language": target_lang,
                        "genre": genre,
                        "target_words": target_words,
                        "actual_words": spoken_word_count_oa,
                        "raw_words": len(gpt_text.split()),
                        "hook_score": hook_metrics,
                        "story_beats": story_beats or [],
                        "is_valid": is_valid,
                        "integrity_report": val_report,
                        "attempts": attempts,
                        "evidence_packets": [p.to_dict() if hasattr(p, "to_dict") else p for p in evidence_packets],
                        "story_plan": [s.to_dict() if hasattr(s, "to_dict") else s for s in story_plan],
                        "is_plan_valid": is_plan_valid,
                        "plan_validation_report": plan_validation_report
                    }
                    if not is_valid and val_details and val_details.get("error") == "chronology_violation":
                        res["failure_type"] = "chronology_violation"
                        res["error"] = val_report
                        res["chronology_details"] = val_details
                    return res
        except Exception as e:
            print(f"[OpenAI ChatGPT Integration Notice] Fallback triggered: {e}")

        # 1. Attempt generation via 9Router (Primary Local / Cloud LLM)
        try:
            from app.services.nine_router_client import is_ninerouter_available, call_ninerouter_llm
            if is_ninerouter_available(timeout_sec=8.0):
                lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["en"])
                system_instruction = f"You are an elite, viral YouTube video narrator and storyboard writer in natural colloquial {lang_info['name']}."

                def nine_gen(p_str: str) -> Optional[str]:
                    return call_ninerouter_llm(prompt=p_str, system_prompt=system_instruction, timeout_sec=90, max_tokens=4000)

                def nine_expand(s_str: str, actual_w: int) -> Optional[str]:
                    if duration_mins >= 3 and actual_w < int(target_words * 0.80):
                        exp_prompt = f"""The following {lang_info['name']} script is only {actual_w} words, but the video duration requires AT LEAST {target_words} words:

--- CURRENT SCRIPT ---
{s_str}
--- END ---

TASK: Elaborate, expand and enrich the story across Act 1, Act 2, and Act 3 with detailed character dialogues, dramatic internal monologues, intense scene descriptions, and escalating emotional stakes to reach {target_words} words. Return the complete, expanded narrative with milestone timestamp brackets like [01:15 - 02:30]."""
                        try:
                            return call_ninerouter_llm(prompt=exp_prompt, system_prompt=system_instruction, timeout_sec=90, max_tokens=4000)
                        except Exception:
                            return None
                    return None

                nine_text, is_valid, val_report, attempts, val_details = ScriptEngine.generate_script_with_chronology_guard(
                    generate_fn=nine_gen,
                    initial_prompt=prompt,
                    duration_mins=duration_mins,
                    voice_speed=voice_speed,
                    target_lang=target_lang,
                    source_video_duration_sec=source_video_duration_sec,
                    dialogue_timeline=dialogue_timeline,
                    evidence_packets=evidence_packets,
                    story_plan=story_plan,
                    expand_fn=nine_expand if (duration_mins >= 3) else None
                )
                if nine_text:
                    clean_narr, _, _ = ScriptEngine.parse_storyboard(nine_text)
                    spoken_word_count = len(clean_narr.split()) if clean_narr else len(nine_text.split())
                    hook_metrics = ScriptEngine.calculate_hook_score(nine_text, target_lang)
                    res = {
                        "success": True,
                        "model": "9router:new-combo",
                        "script": nine_text.strip(),
                        "language": target_lang,
                        "genre": genre,
                        "target_words": target_words,
                        "actual_words": spoken_word_count,
                        "raw_words": len(nine_text.split()),
                        "hook_score": hook_metrics,
                        "story_beats": story_beats or [],
                        "is_valid": is_valid,
                        "integrity_report": val_report,
                        "attempts": attempts,
                        "evidence_packets": [p.to_dict() if hasattr(p, "to_dict") else p for p in evidence_packets],
                        "story_plan": [s.to_dict() if hasattr(s, "to_dict") else s for s in story_plan],
                        "is_plan_valid": is_plan_valid,
                        "plan_validation_report": plan_validation_report
                    }
                    if not is_valid and val_details and val_details.get("error") == "chronology_violation":
                        res["failure_type"] = "chronology_violation"
                        res["error"] = val_report
                        res["chronology_details"] = val_details
                    return res
        except Exception as e:
            print(f"[9Router Integration Warning] {e}")

        # 2. Attempt generation via Gemini API if key is available
        if api_key:
            for model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]:
                def gemini_gen(p_str: str) -> Optional[str]:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                    payload = json.dumps({"contents": [{"parts": [{"text": p_str}]}]}).encode("utf-8")
                    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                    with urllib.request.urlopen(req, timeout=35) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        return res_json["candidates"][0]["content"]["parts"][0]["text"].strip()

                def gemini_expand(s_str: str, actual_w: int) -> Optional[str]:
                    if duration_mins >= 3 and actual_w < int(target_words * 0.80):
                        exp_res = ScriptEngine.expand_script(
                            current_script=s_str,
                            target_lang=target_lang,
                            duration_mins=duration_mins,
                            voice_speed=voice_speed,
                            genre=genre,
                            gemini_api_key=api_key
                        )
                        if exp_res.get("success") and exp_res.get("script"):
                            return exp_res["script"]
                    return None

                try:
                    text, is_valid, val_report, attempts, val_details = ScriptEngine.generate_script_with_chronology_guard(
                        generate_fn=gemini_gen,
                        initial_prompt=prompt,
                        duration_mins=duration_mins,
                        voice_speed=voice_speed,
                        target_lang=target_lang,
                        source_video_duration_sec=source_video_duration_sec,
                        dialogue_timeline=dialogue_timeline,
                        evidence_packets=evidence_packets,
                        story_plan=story_plan,
                        expand_fn=gemini_expand if (duration_mins >= 3) else None
                    )
                    if text:
                        clean_narr_g, _, _ = ScriptEngine.parse_storyboard(text)
                        spoken_word_count_g = len(clean_narr_g.split()) if clean_narr_g else len(text.split())
                        hook_metrics = ScriptEngine.calculate_hook_score(text, target_lang)
                        res = {
                            "success": True,
                            "model": model,
                            "script": text,
                            "language": target_lang,
                            "genre": genre,
                            "target_words": target_words,
                            "actual_words": spoken_word_count_g,
                            "raw_words": len(text.split()),
                            "hook_score": hook_metrics,
                            "story_beats": story_beats or [],
                            "is_valid": is_valid,
                            "integrity_report": val_report,
                            "attempts": attempts,
                            "evidence_packets": [p.to_dict() if hasattr(p, "to_dict") else p for p in evidence_packets],
                            "story_plan": [s.to_dict() if hasattr(s, "to_dict") else s for s in story_plan],
                            "is_plan_valid": is_plan_valid,
                            "plan_validation_report": plan_validation_report
                        }
                        if not is_valid and val_details and val_details.get("error") == "chronology_violation":
                            res["failure_type"] = "chronology_violation"
                            res["error"] = val_report
                            res["chronology_details"] = val_details
                        return res
                except Exception:
                    continue

        # 3. Fallback multi-language template generator
        fallback_text = ScriptEngine._generate_fallback_script(title, target_lang, mood, persona, duration_mins)
        hook_metrics = ScriptEngine.calculate_hook_score(fallback_text, target_lang)
        return {
            "success": True,
            "model": "local_fallback_engine",
            "script": fallback_text,
            "language": target_lang,
            "genre": genre,
            "target_words": target_words,
            "hook_score": hook_metrics,
            "story_beats": story_beats or [],
            "is_valid": True,
            "integrity_report": "Local fallback template generated.",
            "attempts": 1,
            "evidence_packets": [p.to_dict() if hasattr(p, "to_dict") else p for p in evidence_packets],
            "story_plan": [s.to_dict() if hasattr(s, "to_dict") else s for s in story_plan],
            "is_plan_valid": is_plan_valid,
            "plan_validation_report": plan_validation_report
        }

    @staticmethod
    def _generate_fallback_script(title: str, lang: str, mood: str, persona: str, duration_mins: int = 3) -> str:
        """Resilient fallback storytelling templates for when LLM API is unreachable.
        Scales scene count and word budget to match the requested duration."""

        # Words per minute by language (approximate spoken rate at 'fast' speed)
        wpm_map = {"ur": 120, "ar": 120, "hi": 140, "ja": 100, "ko": 100, "th": 90, "default": 145}
        wpm = wpm_map.get(lang, wpm_map["default"])
        target_words = max(80, wpm * duration_mins)
        # Each scene block ~ 100 words; clamp between 1 and 12 scenes
        num_scenes = max(1, min(12, round(target_words / 100)))

        # Per-language scene templates — list of (timestamp_end_min, narration)
        def en_scenes(n):
            beats = [
                (0.5,  f"Nobody could have predicted the horrific secret hidden behind {title}. When our protagonist stepped into this dark mystery, every exit was already sealed."),
                (1.0,  f"The deeper they searched, the more dangerous the truth became. Every ally turned out to be a stranger. Every door led to a new nightmare."),
                (1.5,  f"Act Two begins in silence — but silence was the most deceptive weapon of all. The enemy was closer than anyone imagined."),
                (2.0,  f"A shocking revelation tore apart everything the protagonist believed. The conspiracy ran deeper than any single person, and time was running out."),
                (2.5,  f"With no allies left and no way out, the protagonist had only one option: face the truth head-on, no matter the cost."),
                (3.0,  f"The climax erupts in a single, breathtaking confrontation. Every secret, every lie, every sacrifice — it all comes down to this one moment."),
                (4.0,  f"In the chaos of the final battle, one truth stands above all: the real enemy was never the one they expected."),
                (5.0,  f"When the dust settles, nothing will ever be the same. The protagonist walks away changed — scarred, wiser, and forever altered by what they uncovered."),
                (6.5,  f"But even in victory, a shadow remains. One loose end. One unanswered question. One face they will never forget."),
                (8.0,  f"The epilogue is quieter than the storm that came before — but no less chilling. Because in stories like {title}, endings are just new beginnings."),
                (10.0, f"And so the cycle continues. New players. New secrets. But the same deadly game. Will the truth ever fully surface? Only time will tell."),
                (12.5, f"Make sure to follow and like for more cinematic recaps — because every story has a secret worth uncovering, and we are just getting started."),
            ]
            return beats[:n]

        def ur_scenes(n):
            beats = [
                (0.5,  f"یہ کہانی شروع ہوتی ہے ایک ایسے پراسرار موڑ سے جہاں ہر لمحہ جان لیوا ثابت ہو سکتا ہے۔ {title} کی اس داستان میں ایک تاریک راز چھپا ہے جو سب کچھ بدل کر رکھ دے گا۔"),
                (1.0,  f"مرکزی کردار کو جب حقیقت کی پہلی جھلک ملی تو وہ سمجھ گیا کہ دشمن بہت قریب ہے — اتنا قریب کہ سانس لینا بھی خطرناک لگنے لگا۔"),
                (1.5,  f"دوسرے ایکٹ میں خاموشی نے سب سے بڑا وار کیا۔ جو دوست سمجھے تھے وہ غیر نکلے، اور جو غیر تھے وہ اصل ساتھی۔"),
                (2.0,  f"اب وقت آ گیا تھا فیصلے کا۔ ایک طرف سچ، دوسری طرف موت — اور بیچ میں صرف ہمارا ہیرو، اکیلا، لیکن پرعزم۔"),
                (2.5,  f"کلائمیکس میں وہ لمحہ آیا جب سب کچھ داؤ پر لگا تھا۔ دھماکے، راز، آنسو — سب ایک ساتھ، سب بیک وقت۔"),
                (3.0,  f"آخر میں جو سچ سامنے آیا وہ سب سے بڑا جھٹکا تھا۔ اور اب آپ کا کام ہے: لائک کریں اور فالو کریں اگلی داستان کے لیے!"),
            ]
            return beats[:n]

        def hi_scenes(n):
            beats = [
                (0.5,  f"यह कहानी शुरू होती है एक ऐसे ख़ौफ़नाक मोड़ से जहाँ हर कदम पर मौत खड़ी थी। {title} की इस दुनिया में एक भयानक सच छिपा था।"),
                (1.0,  f"जैसे-जैसे नायक आगे बढ़ा, हर राज़ एक नए दरवाज़े की तरह खुलता गया — और हर दरवाज़े के पीछे था एक और ख़तरा।"),
                (1.5,  f"दूसरे अंक में साजिश का पर्दा उठा। दोस्त दुश्मन निकले, और दुश्मन कुछ और ही साबित हुए।"),
                (2.0,  f"अब लड़ाई सिर्फ जीने-मरने की नहीं थी — यह सच और झूठ की, विश्वास और धोखे की लड़ाई थी।"),
                (2.5,  f"क्लाइमेक्स में सब कुछ एक पल में सिमट आया। वो एक सवाल जो पूरी फिल्म में गूँजता रहा — आखिरकार उसका जवाब मिला।"),
                (3.0,  f"आगे की पूरी कहानी जानने के लिए अभी फ़ॉलो और लाइक करें — क्योंकि यह सिर्फ शुरुआत है!"),
            ]
            return beats[:n]

        def ar_scenes(n):
            beats = [
                (0.5,  f"تبدأ هذه القصة مع لغز غامض ومرعب في {title} لا يمكن لأحد توقعه."),
                (1.0,  f"عندما اقترب البطل من كشف الحقيقة، أدرك أن الخطر يحيط به من كل جانب."),
                (1.5,  f"في الفصل الثاني، تنكشف خيانة مروعة تقلب كل المعادلات رأساً على عقب."),
                (2.0,  f"في ذروة الأحداث، يُجبر البطل على خيار مصيري: الحقيقة أم النجاة؟"),
                (2.5,  f"والنهاية؟ كانت أكثر إدهاشاً مما توقعه أي أحد. تابعنا الآن لمشاهدة القصة كاملة!"),
            ]
            return beats[:n]

        def generic_scenes(n, lang_template_fn):
            return lang_template_fn(n)

        scene_fns = {"en": en_scenes, "ur": ur_scenes, "hi": hi_scenes, "ar": ar_scenes}
        scene_fn = scene_fns.get(lang, en_scenes)
        scenes = scene_fn(num_scenes)

        def fmt(m: float) -> str:
            mm = int(m)
            ss = int(round((m - mm) * 60))
            return f"{mm:02d}:{ss:02d}"

        lines = []
        for i, (end_min, narration) in enumerate(scenes):
            start_min = 0.0 if i == 0 else scenes[i - 1][0]
            lines.append(f"[SCENE: {fmt(start_min)} - {fmt(end_min)}]")
            lines.append("[VOICEOVER]")
            lines.append(narration)
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def translate_script_to_languages(primary_script: str, languages: List[str]) -> Dict[str, str]:
        """Translates a primary script into multiple target languages using chunked translation."""
        results = {}
        if not primary_script:
            return results

        from deep_translator import GoogleTranslator
        for lang in languages:
            l_code = lang.strip().lower()
            if not l_code:
                continue
            if l_code == "en":
                results[l_code] = primary_script
                continue
            try:
                if len(primary_script) > 2200:
                    chunks = [primary_script[i:i+2000] for i in range(0, len(primary_script), 2000)]
                    translated_chunks = [GoogleTranslator(source="auto", target=l_code).translate(c) for c in chunks]
                    results[l_code] = " ".join(translated_chunks)
                else:
                    results[l_code] = GoogleTranslator(source="auto", target=l_code).translate(primary_script)
            except Exception as e:
                print(f"[Translate Scripts Error {l_code}] {e}")
                results[l_code] = primary_script
        return results

    @staticmethod
    def expand_script(
        current_script: str,
        target_lang: str = "en",
        duration_mins: int = 10,
        voice_speed: str = "fast",
        genre: str = "movie_recap",
        gemini_api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """Expands an existing script to reach the full target word count."""
        target_words = ScriptEngine.calculate_target_words(duration_mins, voice_speed, target_lang)
        lang_info = SUPPORTED_LANGUAGES.get(target_lang, SUPPORTED_LANGUAGES["en"])
        clean_text, _, _ = ScriptEngine.parse_storyboard(current_script)
        current_words = len(clean_text.split())

        prompt = f"""You are an elite YouTube storytelling storyboard writer in natural colloquial {lang_info['name']}.
The creator requires a full {duration_mins}-minute explainer which needs at least {target_words} spoken words, but the current script only has {current_words} words.

CURRENT SCRIPT:
{current_script}

EXPANSION INSTRUCTIONS:
1. Preserve the core story arc, character names, tone, and final climax/twist.
2. Greatly expand and elaborate on Act 1 and Act 2 by detailing scene interactions, character dialogues, inner turmoil, and escalating dramatic confrontations.
3. Bring the total script length to AT LEAST {target_words} spoken words.
4. Maintain milestone scene timestamp brackets like [01:15 - 02:30].
Return the complete, expanded storyboard narrative."""

        # 1. 9Router expansion
        try:
            from app.services.nine_router_client import is_ninerouter_available, call_ninerouter_llm
            if is_ninerouter_available(timeout_sec=8.0):
                system_instruction = f"You are an elite YouTube video scriptwriter in {lang_info['name']}."
                exp_text = call_ninerouter_llm(prompt=prompt, system_prompt=system_instruction, timeout_sec=90, max_tokens=4000)
                if exp_text and len(exp_text.strip()) > 100:
                    exp_text = ScriptEngine.strip_code_and_developer_artifacts(exp_text)
                    hook_metrics = ScriptEngine.calculate_hook_score(exp_text, target_lang)
                    return {
                        "success": True,
                        "script": exp_text.strip(),
                        "target_words": target_words,
                        "actual_words": len(exp_text.split()),
                        "hook_score": hook_metrics
                    }
        except Exception as e:
            print(f"[expand_script 9Router error] {e}")

        # 2. Gemini expansion fallback
        api_key = gemini_api_key or os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            for model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=45) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if text:
                            text = ScriptEngine.strip_code_and_developer_artifacts(text)
                            hook_metrics = ScriptEngine.calculate_hook_score(text, target_lang)
                            return {
                                "success": True,
                                "script": text.strip(),
                                "target_words": target_words,
                                "actual_words": len(text.split()),
                                "hook_score": hook_metrics
                            }
                except Exception as ge:
                    print(f"[expand_script Gemini error] {ge}")
                    continue

        return {"success": False, "error": "LLM expansion unavailable", "script": current_script}

