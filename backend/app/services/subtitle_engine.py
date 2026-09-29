import re
from typing import List, Tuple, Dict, Any, Optional
from pathlib import Path


class SubtitleEngine:
    """
    Precision Subtitle & Closed-Caption (.SRT / .VTT) Engine.
    Converts multi-language storyboard scripts into timed captions matching video/audio duration.
    """

    @staticmethod
    def format_timestamp_srt(seconds: float) -> str:
        """Converts float seconds into SRT timestamp format: HH:MM:SS,mmm"""
        seconds = max(0.0, float(seconds))
        total_secs = int(seconds)
        millis = int(round((seconds - total_secs) * 1000))
        if millis >= 1000:
            millis = 0
            total_secs += 1

        hrs = total_secs // 3600
        mins = (total_secs % 3600) // 60
        secs = total_secs % 60
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    @staticmethod
    def format_timestamp_vtt(seconds: float) -> str:
        """Converts float seconds into WebVTT timestamp format: HH:MM:SS.mmm"""
        return SubtitleEngine.format_timestamp_srt(seconds).replace(",", ".")

    @staticmethod
    def split_script_into_cues(
        script_text: str,
        total_duration: float,
        timed_cues: Optional[List[Dict[str, Any]]] = None
    ) -> List[Tuple[float, float, str]]:
        """
        Splits narration script into timed subtitle cues.
        If authoritative timed_cues from Edge-TTS are provided, uses them directly.
        Otherwise falls back to sentence-chunked proportional allocation.
        """
        if timed_cues and len(timed_cues) > 0:
            cues_out: List[Tuple[float, float, str]] = []
            for c in timed_cues:
                t_s = max(0.0, float(c.get("start", 0.0)))
                t_e = min(total_duration, float(c.get("end", t_s + 2.0)))
                txt = str(c.get("text", "")).strip()
                if txt and t_e > t_s:
                    cues_out.append((t_s, t_e, txt))
            if cues_out:
                return cues_out

        if not script_text or not script_text.strip():
            return []

        # Split by sentence terminators (including Urdu '۔') or newlines
        raw_sentences = [s.strip() for s in re.split(r"[.!?।؟۔\n]+", script_text) if s.strip()]
        if not raw_sentences:
            raw_sentences = [script_text.strip()]

        # Break long sentences (>80 chars) into natural chunks
        cues_text: List[str] = []
        for s in raw_sentences:
            if len(s) <= 80:
                cues_text.append(s)
            else:
                words = s.split()
                chunk: List[str] = []
                cur_len = 0
                for w in words:
                    chunk.append(w)
                    cur_len += len(w) + 1
                    if cur_len >= 55:
                        cues_text.append(" ".join(chunk))
                        chunk = []
                        cur_len = 0
                if chunk:
                    cues_text.append(" ".join(chunk))

        if not cues_text:
            return []

        # Allocate durations proportionally based on string length
        total_chars = sum(max(1, len(t)) for t in cues_text)
        min_cue_dur = 1.6
        cues: List[Tuple[float, float, str]] = []

        current_time = 0.0
        for i, text in enumerate(cues_text):
            prop = len(text) / total_chars
            cue_dur = max(min_cue_dur, prop * total_duration)

            start_time = current_time
            end_time = min(total_duration, start_time + cue_dur)
            # Ensure last cue covers through total duration
            if i == len(cues_text) - 1:
                end_time = total_duration

            if end_time > start_time:
                cues.append((start_time, end_time, text))
                current_time = end_time

        return cues

    @classmethod
    def generate_srt_content(
        cls,
        script_text: str,
        total_duration: float,
        timed_cues: Optional[List[Dict[str, Any]]] = None
    ) -> str:
        """Generates standard SubRip (.srt) subtitle string."""
        cues = cls.split_script_into_cues(script_text, total_duration, timed_cues=timed_cues)
        if not cues:
            return ""

        srt_blocks: List[str] = []
        for idx, (start_t, end_t, text) in enumerate(cues, start=1):
            s_str = cls.format_timestamp_srt(start_t)
            e_str = cls.format_timestamp_srt(end_t)
            srt_blocks.append(f"{idx}\n{s_str} --> {e_str}\n{text}\n")

        return "\n".join(srt_blocks)

    @classmethod
    def save_srt_file(
        cls,
        script_text: str,
        total_duration: float,
        output_path: str,
        timed_cues: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """Generates and writes .srt file to disk."""
        try:
            content = cls.generate_srt_content(script_text, total_duration, timed_cues=timed_cues)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
            return True
        except Exception as e:
            print(f"[SubtitleEngine Error] {e}")
            return False
