import os
import re
import math
import shutil
import unicodedata
import subprocess
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple

from app.core.logger import log_event


class ASRSegment:
    """
    Standardized ASR segment representation (Phase 6A).
    Decouples raw ASR engine outputs from downstream dialogue timeline cues.
    """
    def __init__(
        self,
        start: float,
        end: float,
        text: str,
        language: Optional[str] = None,
        confidence: Optional[float] = None,
        segment_id: Optional[int] = None
    ):
        self.start = float(start)
        self.end = float(end)
        self.text = str(text)
        self.language = language
        self.confidence = confidence
        self.segment_id = segment_id

    def to_dict(self) -> Dict[str, Any]:
        res: Dict[str, Any] = {
            "start": round(self.start, 2),
            "end": round(self.end, 2),
            "text": self.text
        }
        if self.language:
            res["language"] = self.language
        if self.confidence is not None:
            res["confidence"] = round(self.confidence, 4)
        if self.segment_id is not None:
            res["segment_id"] = self.segment_id
        return res


class ASRProvider(ABC):
    """
    Abstract Base Class for Automated Speech Recognition providers (Phase 6A).
    Downstream code must depend only on this interface.
    """
    @abstractmethod
    def transcribe(self, audio_path: str) -> List[ASRSegment]:
        """Transcribes audio file to timestamped ASR segments."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Returns True if the provider dependencies and models are functional."""
        pass

    @abstractmethod
    def provider_name(self) -> str:
        """Returns canonical provider identifier."""
        pass


class FasterWhisperASRProvider(ASRProvider):
    """
    Local ASR Provider using faster-whisper (CTranslate2-based Whisper).
    Lazy initialization: model is only loaded when transcribe() is called.
    """
    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        compute_type: Optional[str] = None,
        language: Optional[str] = None
    ):
        self.model_name = model_name or os.environ.get("ASR_MODEL", "base")
        self.device = device or os.environ.get("ASR_DEVICE", "cpu")
        self.compute_type = compute_type or os.environ.get("ASR_COMPUTE_TYPE", "int8")
        self.language = language or os.environ.get("ASR_LANGUAGE", None)
        self._model = None

    def provider_name(self) -> str:
        return "faster-whisper"

    def is_available(self) -> bool:
        """Checks if faster_whisper module can be imported without crashing."""
        try:
            import faster_whisper  # noqa: F401
            return True
        except (ImportError, Exception):
            return False

    def _get_model(self):
        """Lazy model loader with device fallback (CUDA -> CPU)."""
        if self._model is not None:
            return self._model
        if not self.is_available():
            raise RuntimeError("faster_whisper package is not installed or importable.")

        from faster_whisper import WhisperModel

        try:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type
            )
        except Exception as e:
            if self.device != "cpu":
                log_event(f"⚠️ ASR model failed on {self.device} ({e}), falling back to CPU int8...", "WARNING")
                self.device = "cpu"
                self.compute_type = "int8"
                self._model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8"
                )
            else:
                raise e
        return self._model

    def transcribe(self, audio_path: str) -> List[ASRSegment]:
        try:
            if not audio_path or not os.path.exists(audio_path) or os.path.getsize(audio_path) == 0:
                log_event(f"⚠️ ASR transcribe called on invalid or empty audio path: {audio_path}", "WARNING")
                return []
        except OSError:
            log_event(f"⚠️ ASR transcribe called on inaccessible audio path: {audio_path}", "WARNING")
            return []

        try:
            model = self._get_model()
        except Exception as e:
            log_event(f"⚠️ ASR model initialization failed ({e}); skipping ASR", "WARNING")
            return []

        try:
            transcribe_kwargs: Dict[str, Any] = {
                "beam_size": 5,
                "vad_filter": True
            }
            if self.language:
                transcribe_kwargs["language"] = self.language

            segments, info = model.transcribe(audio_path, **transcribe_kwargs)
            detected_lang = getattr(info, "language", None)

            out_segments: List[ASRSegment] = []
            for seg in segments:
                out_segments.append(ASRSegment(
                    start=float(seg.start),
                    end=float(seg.end),
                    text=seg.text,
                    language=detected_lang,
                    confidence=getattr(seg, "avg_logprob", None),
                    segment_id=getattr(seg, "id", None)
                ))
            return out_segments
        except Exception as e:
            log_event(f"⚠️ ASR transcription execution error ({e}); skipping ASR", "WARNING")
            return []


class MockASRProvider(ASRProvider):
    """
    Mock ASR Provider for deterministic testing and simulated offline runs.
    """
    def __init__(self, segments: Optional[List[ASRSegment]] = None, available: bool = True):
        self._segments = segments if segments is not None else []
        self._available = available

    def provider_name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return self._available

    def transcribe(self, audio_path: str) -> List[ASRSegment]:
        if not self._available:
            raise RuntimeError("Mock ASR provider is unavailable.")
        return list(self._segments)


class ASREngine:
    """
    Automated Speech Recognition Engine (Phase 6A).
    Coordinates audio extraction, transcription, dialogue cue sanitation,
    and downstream transcript formatting.
    """

    @staticmethod
    def get_ffmpeg_binary() -> str:
        from app.services.video_engine import get_ffmpeg_binary
        return get_ffmpeg_binary()

    @staticmethod
    def extract_audio_for_asr(
        media_path: str,
        output_wav_path: str,
        timeout_sec: float = 60.0
    ) -> bool:
        """
        Extracts 16kHz mono 16-bit PCM audio from media using FFmpeg.
        Guarantees cleanup on failure and respects timeout limits.
        """
        try:
            if not media_path or not os.path.exists(media_path) or os.path.getsize(media_path) == 0:
                return False
        except OSError:
            return False

        ffmpeg_bin = ASREngine.get_ffmpeg_binary()
        cmd = [
            ffmpeg_bin, "-y",
            "-i", media_path,
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            output_wav_path
        ]

        try:
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_sec
            )
            success = False
            try:
                if res.returncode == 0 and os.path.exists(output_wav_path) and os.path.getsize(output_wav_path) > 100:
                    success = True
            except OSError:
                success = False

            if success:
                return True
            else:
                if os.path.exists(output_wav_path):
                    try:
                        os.remove(output_wav_path)
                    except OSError:
                        pass
                return False
        except (subprocess.TimeoutExpired, Exception) as e:
            log_event(f"⚠️ FFmpeg audio extraction for ASR failed: {e}", "WARNING")
            if os.path.exists(output_wav_path):
                try:
                    os.remove(output_wav_path)
                except OSError:
                    pass
            return False

    @staticmethod
    def segments_to_dialogue_cues(segments: List[ASRSegment]) -> List[Dict[str, Any]]:
        """
        Converts ASRSegment objects into sanitized dialogue cues [{start, end, text, source}].
        Enforces strict validation:
          1. Finite timestamps (no NaN/Inf)
          2. Non-negative start time
          3. start < end
          4. Non-empty text with normalized whitespace
          5. Preserves Unicode / RTL characters (Urdu, Hindi, Arabic)
          6. Deduplicates adjacent identical cues within < 0.5s
          7. Strict chronological ordering (stable sort)
        """
        if not segments:
            return []

        cues: List[Dict[str, Any]] = []
        for s in segments:
            # 1. Finite timestamp validation
            if not math.isfinite(s.start) or not math.isfinite(s.end):
                continue
            # 2. Non-negative start
            if s.start < 0.0 or s.end < 0.0:
                continue
            # 3. start < end
            if s.end <= s.start:
                continue

            # 4. Text cleaning and Unicode normalization
            raw_t = s.text or ""
            norm_t = unicodedata.normalize("NFKC", raw_t)
            clean_t = re.sub(r"\s+", " ", norm_t).strip()
            if not clean_t:
                continue

            cues.append({
                "start": round(s.start, 2),
                "end": round(s.end, 2),
                "text": clean_t,
                "source": "asr"
            })

        if not cues:
            return []

        # 5. Stable chronological sort
        cues.sort(key=lambda c: c["start"])

        # 6. Deduplication of adjacent identical phrases
        deduped: List[Dict[str, Any]] = []
        for cue in cues:
            if not deduped:
                deduped.append(cue)
                continue
            prev = deduped[-1]
            if cue["text"] == prev["text"] and abs(cue["start"] - prev["start"]) < 0.5:
                # Merge end time forward if needed
                prev["end"] = max(prev["end"], cue["end"])
                continue
            deduped.append(cue)

        return deduped

    @staticmethod
    def format_cues_to_subtitles_text(cues: List[Dict[str, Any]]) -> str:
        """
        Formats dialogue cues into the project's standard timestamped subtitle format:
        [MM:SS - MM:SS] Dialogue text
        Compatible with VideoEngine.parse_raw_transcript_text and ScriptEngine.
        """
        def sec_to_ts(s: float) -> str:
            m = int(s // 60)
            sec = int(s % 60)
            return f"{m:02d}:{sec:02d}"

        lines = []
        for c in cues:
            st = sec_to_ts(c["start"])
            et = sec_to_ts(c["end"])
            lines.append(f"[{st} - {et}] {c['text']}")
        return "\n".join(lines)

    @staticmethod
    def get_configured_asr_provider() -> Optional[ASRProvider]:
        """
        Factory to instantiate the configured ASR provider (Phase 6A).
        Returns None if ASR is disabled.
        """
        env_enabled = os.environ.get("ASR_ENABLED", "true").strip().lower()
        if env_enabled in ("0", "false", "no", "off"):
            return None

        provider_type = os.environ.get("ASR_PROVIDER", "faster-whisper").strip().lower()
        if provider_type == "mock":
            return MockASRProvider()

        # Default: FasterWhisperASRProvider
        return FasterWhisperASRProvider()

    @staticmethod
    def transcribe_media_to_dialogue(
        media_path: str,
        temp_dir: str,
        job_id: str,
        provider: Optional[ASRProvider] = None
    ) -> Tuple[List[Dict[str, Any]], str, str]:
        """
        Complete end-to-end ASR execution pipeline:
          1. Resolves provider.
          2. Extracts audio to temporary 16kHz mono WAV.
          3. Transcribes audio into raw ASR segments.
          4. Sanitizes and validates dialogue cues.
          5. Cleans up intermediate WAV in finally block (Rule 7).
          6. Returns (dialogue_timeline, subtitles_text, transcript_source).
        """
        active_provider = provider or ASREngine.get_configured_asr_provider()
        if active_provider is None or not active_provider.is_available():
            return [], "", "none"

        if not media_path or not os.path.exists(media_path):
            return [], "", "none"

        temp_wav = os.path.join(temp_dir, f"{job_id}_asr_audio.wav")
        try:
            extracted = ASREngine.extract_audio_for_asr(media_path, temp_wav)
            if not extracted:
                log_event("⚠️ ASR audio extraction could not produce valid WAV", "WARNING")
                return [], "", "none"

            raw_segments = active_provider.transcribe(temp_wav)
            if not raw_segments:
                return [], "", "none"

            dialogue_cues = ASREngine.segments_to_dialogue_cues(raw_segments)
            if not dialogue_cues:
                return [], "", "none"

            subtitles_text = ASREngine.format_cues_to_subtitles_text(dialogue_cues)
            return dialogue_cues, subtitles_text, "asr"
        except Exception as e:
            log_event(f"⚠️ ASREngine transcription failed gracefully: {e}", "WARNING")
            return [], "", "none"
        finally:
            if os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass
