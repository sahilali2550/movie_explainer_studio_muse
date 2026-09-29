import os
import re
import json
import uuid
import subprocess
import math
from typing import Dict, List, Tuple, Optional, Any
from app.core.config import get_ffmpeg_binary, get_ffprobe_binary, TEMP_DIR, UPLOADS_DIR, OUTPUTS_DIR, FONTS_DIR

from urllib.parse import urlparse

class VideoEngine:
    """
    Core Video Ingestion, Timeline Milestone Slicing & FFmpeg Assembly Engine.
    Handles anti-copyright protection, blurred backdrops, typography, and multi-part series.
    """

    @staticmethod
    def is_valid_youtube_url(url: str) -> bool:
        """Validates that a URL is a legitimate YouTube video URL (prevents SSRF and flag injection)."""
        if not url or not isinstance(url, str):
            return False
        url = url.strip()
        if url.startswith("-"):
            return False
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            hostname = (parsed.hostname or "").lower()
            if hostname in ("youtube.com", "www.youtube.com", "m.youtube.com"):
                return parsed.path in ("/watch", "/watch_popup") or parsed.path.startswith(("/shorts/", "/embed/"))
            elif hostname in ("youtu.be", "www.youtu.be"):
                return len(parsed.path.strip("/")) > 0
            return False
        except Exception:
            return False

    @staticmethod
    def escape_ffmpeg_drawtext(text: str) -> str:
        """
        Escapes special characters for FFmpeg drawtext filter:
        %, comma, colons, single/double quotes, and backslashes.
        """
        if not text:
            return ""
        s = text.replace("\r", " ").replace("\n", " ")
        s = s.replace("\\", "\\\\")
        s = s.replace("'", "\\'")
        s = s.replace("%", "\\%")
        s = s.replace(":", "\\:")
        s = s.replace(",", "\\,")
        return s

    @staticmethod
    def get_font_for_lang(lang: str = "en") -> str:
        """Returns safe, escaped FFmpeg fontfile path matching the language."""
        cand = None
        if lang in ["ur", "ar"]:
            cand = FONTS_DIR / "NotoNastaliqUrdu.ttf"
            if not cand.exists():
                cand = FONTS_DIR / "arabtype.ttf"
        elif lang == "hi":
            cand = FONTS_DIR / "NirmalaB.ttf"
        else:
            cand = FONTS_DIR / "arialbd.ttf"

        if not cand or not cand.exists():
            cand = FONTS_DIR / "arialbd.ttf"

        if cand.exists():
            p = str(cand.resolve()).replace("\\", "/")
            return p.replace(":", "\\:")
        return ""

    @staticmethod
    def probe_media(video_path: str) -> Dict[str, Any]:
        """
        Feature #1 Upgrade: Bulletproof Metadata Inspection.
        Extracts duration, resolution, FPS, and stream codecs accurately without guessing.
        """
        if not video_path or not os.path.exists(video_path):
            raise FileNotFoundError(f"Source video not found: {video_path}")

        ffprobe = get_ffprobe_binary()
        cmd = [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,duration",
            "-of", "json",
            video_path
        ]
        
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            info = json.loads(res.stdout)
            
            # Duration calculation (Format duration fallback to Stream duration)
            fmt_dur = info.get("format", {}).get("duration")
            v_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
            a_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
            
            video_dur = None
            if fmt_dur and fmt_dur != "N/A":
                video_dur = float(fmt_dur)
            elif v_streams and v_streams[0].get("duration") and v_streams[0].get("duration") != "N/A":
                video_dur = float(v_streams[0]["duration"])
            
            if not video_dur or video_dur <= 0:
                raise ValueError(f"Could not determine valid duration for '{video_path}'. File may be corrupt.")

            # FPS calculation
            fps = 30.0
            if v_streams:
                r_fps = v_streams[0].get("r_frame_rate", "30/1")
                if "/" in r_fps:
                    num, den = r_fps.split("/")
                    fps = round(float(num) / float(den), 2) if float(den) > 0 else 30.0

            width = int(v_streams[0].get("width", 1920)) if v_streams else 1920
            height = int(v_streams[0].get("height", 1080)) if v_streams else 1080

            return {
                "file_path": video_path,
                "duration": video_dur,
                "width": width,
                "height": height,
                "fps": fps,
                "aspect_ratio": "vertical" if height > width else ("square" if height == width else "horizontal"),
                "has_audio": len(a_streams) > 0,
                "video_codec": v_streams[0].get("codec_name") if v_streams else "unknown",
                "audio_codec": a_streams[0].get("codec_name") if a_streams else "none"
            }
        except Exception as e:
            raise RuntimeError(f"MediaProbeError for '{video_path}': {str(e)}")

    @staticmethod
    def get_duration(video_path: str) -> float:
        """Safe wrapper that relies on comprehensive probe_media instead of hardcoded 60s fallback."""
        try:
            meta = VideoEngine.probe_media(video_path)
            return meta["duration"]
        except Exception:
            ffprobe = get_ffprobe_binary()
            cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", video_path]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
            raise RuntimeError(f"Unable to determine duration for source: {video_path}")

    @staticmethod
    def _timestamp_to_seconds(t_str: str) -> float:
        """Converts MM:SS.mmm or HH:MM:SS.mmm string to seconds."""
        t_str = t_str.strip().replace(",", ".")
        parts = t_str.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
        except Exception:
            pass
        return 0.0

    @staticmethod
    def parse_timed_subtitles(subtitle_content: str) -> List[Dict[str, Any]]:
        """Parses WebVTT or SRT subtitle content into structured timed cues."""
        if not subtitle_content:
            return []
        cues = []
        blocks = re.split(r'\n\s*\n', subtitle_content.strip())
        pattern = re.compile(r'((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})')

        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            time_match = None
            text_lines = []
            for line in lines:
                m = pattern.search(line)
                if m:
                    time_match = m
                elif time_match:
                    clean = re.sub(r'<[^>]+>', '', line).strip()
                    if clean:
                        text_lines.append(clean)
            if time_match and text_lines:
                start_sec = VideoEngine._timestamp_to_seconds(time_match.group(1))
                end_sec = VideoEngine._timestamp_to_seconds(time_match.group(2))
                combined_text = " ".join(text_lines)
                cues.append({
                    "start": start_sec,
                    "end": end_sec,
                    "text": combined_text
                })
        return cues

    @staticmethod
    def build_timeline_summary(timed_cues: List[Dict[str, Any]], max_events: int = 25) -> str:
        """Picks spaced milestone dialogue cues across the timeline with timecodes."""
        if not timed_cues:
            return ""
        if len(timed_cues) <= max_events:
            selected = timed_cues
        else:
            step = len(timed_cues) / max_events
            selected = [timed_cues[int(i * step)] for i in range(max_events)]

        def fmt_time(seconds: float) -> str:
            m = int(seconds // 60)
            s = int(seconds % 60)
            return f"[{m:02d}:{s:02d}]"

        lines = []
        for cue in selected:
            t_str = fmt_time(cue["start"])
            text = cue["text"].replace("\n", " ").strip()
            lines.append(f"{t_str} {text}")
        return "\n".join(lines)

    @staticmethod
    def _get_block_narration_dur(block: Any) -> float:
        """
        Extracts authoritative narration duration for a scene block.
        Precedence:
        1. actual_duration (if block.is_authoritative and actual_duration > 0.0)
        2. speech_dur (if speech_dur > 0.0)
        3. narration_end - narration_start (if narration_end > narration_start)
        4. actual_duration (if actual_duration > 0.0)
        5. 3.5 (default minimum)
        """
        if block is None:
            return 3.5

        is_auth = block.get("is_authoritative", False) if isinstance(block, dict) else getattr(block, "is_authoritative", False)
        act_dur = float(block.get("actual_duration", 0.0) if isinstance(block, dict) else getattr(block, "actual_duration", 0.0))
        sp_dur = float(block.get("speech_dur", 0.0) if isinstance(block, dict) else getattr(block, "speech_dur", 0.0))
        n_start = float(block.get("narration_start", 0.0) if isinstance(block, dict) else getattr(block, "narration_start", 0.0))
        n_end = float(block.get("narration_end", 0.0) if isinstance(block, dict) else getattr(block, "narration_end", 0.0))

        if is_auth and act_dur > 0.0:
            return round(act_dur, 3)
        if sp_dur > 0.0:
            return round(sp_dur, 3)
        if n_end > n_start:
            return round(n_end - n_start, 3)
        if act_dur > 0.0:
            return round(act_dur, 3)
        return 3.5

    @staticmethod
    def calculate_source_cut_plan(
        scene_ranges: Optional[List[Tuple[float, float]]] = None,
        total_movie_dur: float = 3600.0,
        target_duration: float = 60.0,
        micro_clip_dur: float = 3.8,
        scene_blocks: Optional[List[Any]] = None
    ) -> List[Tuple[float, float]]:
        """
        Alias for build_chronological_scene_map for source cut planning.
        """
        return VideoEngine.build_chronological_scene_map(
            scene_ranges=scene_ranges,
            total_movie_dur=total_movie_dur,
            target_duration=target_duration,
            micro_clip_dur=micro_clip_dur,
            scene_blocks=scene_blocks
        )

    @staticmethod
    def verify_timeline_drift(
        scene_blocks: List[Any],
        clip_durations: Optional[List[float]] = None,
        tolerance_sec: float = 0.05
    ) -> Dict[str, Any]:
        """
        Phase 4B Timeline & Synchronization Drift Verifier.
        Validates that:
        1. Each scene block's video duration matches authoritative narration duration within tolerance_sec.
        2. Cumulative timeline is strictly contiguous (no gaps or overlaps between consecutive blocks).
        3. Overall timeline drift |sum(clips) - sum(narration)| <= tolerance_sec.
        """
        if not scene_blocks:
            return {
                "is_aligned": True,
                "total_drift": 0.0,
                "max_scene_drift": 0.0,
                "scene_count": 0,
                "tolerance_sec": tolerance_sec,
                "details": [],
                "total_expected_duration": 0.0,
                "total_actual_duration": 0.0,
                "is_contiguous": True
            }

        details = []
        is_contiguous = True
        prev_end = 0.0
        expected_durations = [VideoEngine._get_block_narration_dur(b) for b in scene_blocks]

        for idx, b in enumerate(scene_blocks):
            exp_dur = expected_durations[idx]
            n_start = float(b.get("narration_start", 0.0) if isinstance(b, dict) else getattr(b, "narration_start", 0.0))
            n_end = float(b.get("narration_end", 0.0) if isinstance(b, dict) else getattr(b, "narration_end", 0.0))

            if idx == 0:
                if abs(n_start) > tolerance_sec:
                    is_contiguous = False
            else:
                if abs(n_start - prev_end) > tolerance_sec:
                    is_contiguous = False

            if n_end > n_start:
                prev_end = n_end
            else:
                prev_end += exp_dur

        if clip_durations is not None:
            if len(clip_durations) != len(scene_blocks):
                return {
                    "is_aligned": False,
                    "error": f"Clip count mismatch: {len(clip_durations)} clips vs {len(scene_blocks)} scene blocks",
                    "total_drift": 999.0,
                    "max_scene_drift": 999.0,
                    "scene_count": len(scene_blocks),
                    "tolerance_sec": tolerance_sec,
                    "details": [],
                    "total_expected_duration": round(sum(expected_durations), 3),
                    "total_actual_duration": round(sum(clip_durations), 3),
                    "is_contiguous": is_contiguous
                }

            diffs = []
            for idx, (exp_dur, act_dur) in enumerate(zip(expected_durations, clip_durations)):
                diff = abs(act_dur - exp_dur)
                diffs.append(diff)
                details.append({
                    "scene_idx": idx,
                    "expected_duration": round(exp_dur, 3),
                    "actual_duration": round(act_dur, 3),
                    "drift": round(diff, 4),
                    "aligned": diff <= tolerance_sec
                })

            total_expected = sum(expected_durations)
            total_actual = sum(clip_durations)
            total_drift = abs(total_actual - total_expected)
            max_drift = max(diffs) if diffs else 0.0
            is_aligned = (total_drift <= tolerance_sec) and (max_drift <= tolerance_sec) and is_contiguous

            return {
                "is_aligned": is_aligned,
                "total_drift": round(total_drift, 4),
                "max_scene_drift": round(max_drift, 4),
                "scene_count": len(scene_blocks),
                "tolerance_sec": tolerance_sec,
                "details": details,
                "total_expected_duration": round(total_expected, 3),
                "total_actual_duration": round(total_actual, 3),
                "is_contiguous": is_contiguous
            }
        else:
            diffs = []
            for idx, b in enumerate(scene_blocks):
                exp_dur = expected_durations[idx]
                n_start = float(b.get("narration_start", 0.0) if isinstance(b, dict) else getattr(b, "narration_start", 0.0))
                n_end = float(b.get("narration_end", 0.0) if isinstance(b, dict) else getattr(b, "narration_end", 0.0))
                block_span = n_end - n_start if n_end > n_start else exp_dur
                diff = abs(block_span - exp_dur)
                diffs.append(diff)
                details.append({
                    "scene_idx": idx,
                    "expected_duration": round(exp_dur, 3),
                    "narration_span": round(block_span, 3),
                    "drift": round(diff, 4),
                    "aligned": diff <= tolerance_sec
                })

            total_expected = sum(expected_durations)
            max_drift = max(diffs) if diffs else 0.0
            is_aligned = (max_drift <= tolerance_sec) and is_contiguous

            return {
                "is_aligned": is_aligned,
                "total_drift": round(max_drift, 4),
                "max_scene_drift": round(max_drift, 4),
                "scene_count": len(scene_blocks),
                "tolerance_sec": tolerance_sec,
                "details": details,
                "total_expected_duration": round(total_expected, 3),
                "total_actual_duration": round(total_expected, 3),
                "is_contiguous": is_contiguous
            }

    @staticmethod
    def build_chronological_scene_map(
        scene_ranges: Optional[List[Tuple[float, float]]] = None,
        total_movie_dur: float = 3600.0,
        target_duration: float = 60.0,
        micro_clip_dur: float = 3.8,
        scene_blocks: Optional[List[Any]] = None
    ) -> List[Tuple[float, float]]:
        """
        Creates a strictly chronological series of 3-5s micro-clips spanning the entire story.
        When scene_blocks is provided, clips are allocated proportionally to each block's actual
        spoken narration duration, locking visuals 100% to narration without drift.
        """
        if total_movie_dur <= 0:
            total_movie_dur = 3600.0

        if scene_blocks and len(scene_blocks) > 0:
            # Proportional Time-Locked Slicing:
            # Each block's micro-clips are sized strictly by that scene's spoken duration.
            # Zero drift: When narration finishes Scene X, visuals immediately cut to Scene X+1.
            cuts: List[Tuple[float, float]] = []

            for b in scene_blocks:
                b_dur = VideoEngine._get_block_narration_dur(b)
                if b_dur <= 0.0:
                    b_dur = max(2.5, target_duration / len(scene_blocks))

                # Micro-clip count for this scene block
                n_clips = max(1, int(round(b_dur / micro_clip_dur)))
                base_c_dur = b_dur / n_clips

                raw_m_start = b.get("movie_start", 0.0) if isinstance(b, dict) else getattr(b, "movie_start", 0.0)
                raw_m_end = b.get("movie_end", raw_m_start + 5.0) if isinstance(b, dict) else getattr(b, "movie_end", raw_m_start + 5.0)
                m_start = max(0.0, min(total_movie_dur - 1.5, raw_m_start))
                m_end = max(m_start + 1.5, min(total_movie_dur, raw_m_end))
                span = max(1.0, m_end - m_start)

                if span <= base_c_dur:
                    # Narrow window: clamp clips strictly inside [m_start, m_end]
                    for j in range(n_clips):
                        sub_dur = min(span, base_c_dur)
                        max_s = max(m_start, m_end - sub_dur)
                        s = m_start + ((j % 3) * 0.5 * (max_s - m_start)) if max_s > m_start else m_start
                        e = min(m_end, s + sub_dur)
                        if e <= s:
                            e = min(m_end, s + 1.0)
                        cuts.append((round(s, 2), round(e, 2)))
                else:
                    max_start = max(m_start, m_end - base_c_dur)
                    step = (max_start - m_start) / max(1, n_clips - 1) if n_clips > 1 else 0.0
                    for j in range(n_clips):
                        c_dur = round(base_c_dur, 2)
                        s = m_start + j * step
                        s = max(m_start, min(max_start, s))
                        e = min(m_end, s + c_dur)
                        if e <= s:
                            e = min(m_end, s + 1.5)
                        cuts.append((round(s, 2), round(e, 2)))

            return cuts

        # Fallback to scene_ranges when scene_blocks not provided
        scene_ranges = scene_ranges or []

        # Rhythmic clip duration pattern (varying between 3.0s and 4.6s for dynamic cinematic editing)
        rhythm_durations = [3.4, 4.2, 3.2, 4.6, 3.8, 4.0, 3.6, 4.4]

        # Calculate clips to fill target_duration
        clip_lengths: List[float] = []
        accum = 0.0
        r_idx = 0
        while accum < target_duration:
            dur_cand = rhythm_durations[r_idx % len(rhythm_durations)]
            r_idx += 1
            if accum + dur_cand > target_duration:
                rem = target_duration - accum
                if rem >= 2.0:
                    clip_lengths.append(round(rem, 2))
                elif clip_lengths:
                    clip_lengths[-1] = round(clip_lengths[-1] + rem, 2)
                accum = target_duration
                break
            clip_lengths.append(dur_cand)
            accum += dur_cand

        num_clips = max(8, len(clip_lengths))

        # Check if scene_ranges are valid or clustered in opening 2 minutes or shorter than 70% of target
        clean_ranges = [(s, e) for s, e in scene_ranges if e > s]
        covered_span = sum(e - s for s, e in clean_ranges)
        max_ts = max([e for _, e in clean_ranges], default=0.0)
        is_clustered = (
            len(clean_ranges) < 4
            or covered_span < (target_duration * 0.70)
            or max_ts <= 120.0
            or (total_movie_dur > 600 and max_ts < 0.20 * total_movie_dur)
        )

        cuts = []
        if is_clustered:
            # Proportional 3-Act Chronological Slicing across the entire film:
            # Act 1 (Hook & Setup): 20% clips from 2% to 25% of movie
            # Act 2 (Investigation & Confrontations): 60% clips from 25% to 75% of movie
            # Act 3 (Climax & Resolution): 20% clips from 75% to 92% of movie (before end credits)
            n1 = max(2, int(round(num_clips * 0.20)))
            n2 = max(4, int(round(num_clips * 0.60)))
            n3 = max(2, num_clips - n1 - n2)

            act_configs = [
                (n1, 0.02 * total_movie_dur, 0.25 * total_movie_dur),
                (n2, 0.25 * total_movie_dur, 0.75 * total_movie_dur),
                (n3, 0.75 * total_movie_dur, 0.92 * total_movie_dur)
            ]

            clip_idx = 0
            for count, start_bound, end_bound in act_configs:
                span = max(1.0, end_bound - start_bound)
                step = span / max(1, count)
                for i in range(count):
                    c_dur = clip_lengths[clip_idx] if clip_idx < len(clip_lengths) else 3.6
                    clip_idx += 1
                    s = start_bound + i * step
                    s = max(0.0, min(total_movie_dur - c_dur, s))
                    e = s + c_dur
                    cuts.append((round(s, 2), round(e, 2)))
        else:
            # Valid storyboard timestamp ranges across the movie: distribute micro-clips chronologically
            clean_ranges.sort(key=lambda x: x[0])
            clips_per_range = max(1, num_clips // len(clean_ranges))
            remaining = num_clips
            clip_idx = 0

            for r_idx, (s_sec, e_sec) in enumerate(clean_ranges):
                k = clips_per_range if r_idx < len(clean_ranges) - 1 else remaining
                k = max(1, k)
                remaining -= k

                s_sec = max(0.0, min(total_movie_dur - 3.5, s_sec))
                e_sec = max(s_sec + 3.5, min(total_movie_dur, e_sec))
                span = max(1.0, e_sec - s_sec)
                step = span / max(1, k)

                for j in range(k):
                    c_dur = clip_lengths[clip_idx] if clip_idx < len(clip_lengths) else 3.6
                    clip_idx += 1
                    ideal_s = s_sec + j * step
                    c_s = max(s_sec, min(max(s_sec, e_sec - c_dur), ideal_s))
                    c_e = min(e_sec, c_s + c_dur)
                    if c_e <= c_s:
                        c_e = min(total_movie_dur, c_s + c_dur)
                    cuts.append((round(c_s, 2), round(c_e, 2)))

        cuts.sort(key=lambda x: x[0])
        return cuts

    @staticmethod
    def extract_youtube_info(url: str, output_dir: str, job_id: str) -> Dict[str, Any]:
        """
        Fast metadata and multi-language subtitle extraction via yt-dlp without downloading full video.
        """
        if not VideoEngine.is_valid_youtube_url(url):
            return {"title": "Movie Story Explanation", "duration": 60.0, "subtitles_text": "", "timeline_summary": ""}

        meta_prefix = os.path.join(output_dir, f"{job_id}_info")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "-i",
            "--write-subs",
            "--write-auto-subs",
            "--sub-lang", "en,es,id,ur,hi,ar,fr,de,pt,ru,vi,th,ja,ko",
            "--sub-format", "vtt/srt/best",
            "--write-info-json",
            "--no-check-certificates",
            "-o", meta_prefix,
            "--",
            url
        ]

        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
        except Exception:
            pass

        meta = {
            "title": "Movie Story Explanation",
            "description": "",
            "duration": 0,
            "subtitles_text": "",
            "timeline_summary": ""
        }

        # Parse info.json
        for f in os.listdir(output_dir):
            if f.startswith(f"{job_id}_info") and f.endswith(".info.json"):
                fp = os.path.join(output_dir, f)
                try:
                    with open(fp, "r", encoding="utf-8") as jf:
                        d = json.load(jf)
                        meta["title"] = d.get("title", meta["title"])
                        meta["description"] = d.get("description", "")
                        meta["duration"] = d.get("duration", 0)
                    os.remove(fp)
                except Exception:
                    pass
                break

        # Parse subtitle transcripts (.vtt / .srt) with timestamps
        timed_cues = []
        for f in os.listdir(output_dir):
            if f.startswith(f"{job_id}_info") and (f.endswith(".vtt") or f.endswith(".srt")):
                fp = os.path.join(output_dir, f)
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as sf:
                        content = sf.read()
                        cues = VideoEngine.parse_timed_subtitles(content)
                        if cues:
                            timed_cues.extend(cues)
                    os.remove(fp)
                except Exception:
                    pass

        if timed_cues:
            timed_cues.sort(key=lambda x: x["start"])
            meta["timeline_summary"] = VideoEngine.build_timeline_summary(timed_cues, max_events=30)
            dialogue_texts = [f"[{int(c['start']//60):02d}:{int(c['start']%60):02d}] {c['text']}" for c in timed_cues[:400]]
            meta["subtitles_text"] = f"Key Timeline Milestones:\n{meta['timeline_summary']}\n\nDialogue Excerpts:\n" + "\n".join(dialogue_texts)
            meta["dialogue_timeline"] = timed_cues

        return meta

    @staticmethod
    def parse_raw_transcript_text(raw_text: str) -> Dict[str, Any]:
        """
        Parses raw transcript text from various formats:
        1. YouTube Web UI copy-paste (timestamp on separate line, text on next line)
        2. Same-line timestamp: '00:15 text' or '[00:15] text'
        3. Standard WebVTT / SRT subtitle text
        Returns structured dict with dialogue_timeline, timeline_summary, subtitles_text, total_duration.
        """
        empty_res = {
            "dialogue_timeline": [],
            "subtitles_text": "",
            "timeline_summary": "",
            "total_duration": 0.0
        }
        if not raw_text or not raw_text.strip():
            return empty_res

        timed_cues: List[Dict[str, Any]] = []

        # Check if it's WebVTT or SRT with -->
        is_vtt_or_srt = "-->" in raw_text or raw_text.strip().startswith("WEBVTT")
        if is_vtt_or_srt:
            timed_cues = VideoEngine.parse_timed_subtitles(raw_text)
        else:
            def clean_yt_snippet(t_raw: str) -> str:
                # Remove accessibility aria strings like '1 hour, 20 minutes, 45 seconds'
                t_clean = re.sub(r'^\d+\s*hours?,\s*\d+\s*minutes?,\s*\d+\s*seconds?', '', t_raw, flags=re.IGNORECASE)
                t_clean = re.sub(r'^\d+\s*minutes?,\s*\d+\s*seconds?', '', t_clean, flags=re.IGNORECASE)
                t_clean = re.sub(r'^\d+\s*seconds?', '', t_clean, flags=re.IGNORECASE)
                # Remove sound annotations like [Music] or [Applause]
                t_clean = re.sub(r'\[(?:Music|Applause|Sound|Laughter|Silence|Cheering)\]', '', t_clean, flags=re.IGNORECASE)
                t_clean = re.sub(r'\s+', ' ', t_clean).strip()
                return t_clean

            lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
            ts_pattern = re.compile(r'^\[?(\d{1,2}:\d{2}(?::\d{2})?(?:[\.,]\d{1,3})?)\]?\s*(.*)$')
            i = 0
            while i < len(lines):
                line = lines[i]
                m = ts_pattern.match(line)
                if m:
                    ts_str = m.group(1)
                    raw_rest = m.group(2).strip()
                    clean_rest = clean_yt_snippet(raw_rest)
                    start_sec = VideoEngine._timestamp_to_seconds(ts_str)
                    if clean_rest:
                        timed_cues.append({
                            "start": start_sec,
                            "end": start_sec + 5.0,
                            "text": clean_rest
                        })
                        i += 1
                    else:
                        i += 1
                        text_accum = []
                        while i < len(lines):
                            next_line = lines[i]
                            if ts_pattern.match(next_line):
                                break
                            clean_nl = clean_yt_snippet(next_line)
                            if clean_nl:
                                text_accum.append(clean_nl)
                            i += 1
                        if text_accum:
                            timed_cues.append({
                                "start": start_sec,
                                "end": start_sec + 5.0,
                                "text": " ".join(text_accum)
                            })
                else:
                    i += 1

        if not timed_cues:
            return empty_res

        timed_cues.sort(key=lambda x: x["start"])
        if not is_vtt_or_srt:
            for j in range(len(timed_cues)):
                if j + 1 < len(timed_cues):
                    next_start = timed_cues[j + 1]["start"]
                    if next_start > timed_cues[j]["start"]:
                        timed_cues[j]["end"] = min(timed_cues[j]["start"] + 15.0, next_start)
                    else:
                        timed_cues[j]["end"] = timed_cues[j]["start"] + 5.0
                else:
                    timed_cues[j]["end"] = timed_cues[j]["start"] + 5.0

        max_end = max([c["end"] for c in timed_cues], default=0.0)
        timeline_summary = VideoEngine.build_timeline_summary(timed_cues, max_events=30)
        dialogue_texts = [f"[{int(c['start']//60):02d}:{int(c['start']%60):02d}] {c['text']}" for c in timed_cues[:400]]
        subtitles_text = f"Key Timeline Milestones:\n{timeline_summary}\n\nDialogue Excerpts:\n" + "\n".join(dialogue_texts)

        return {
            "dialogue_timeline": timed_cues,
            "subtitles_text": subtitles_text,
            "timeline_summary": timeline_summary,
            "total_duration": max_end
        }

    @staticmethod
    def build_yt_dlp_section_args(scene_ranges: List[Tuple[float, float]]) -> List[str]:
        """
        Converts scene time ranges [(start_sec, end_sec)] into yt-dlp --download-sections arguments.
        Example: [(18.0, 53.0)] -> ["--download-sections", "*00:18-00:53"]
        Supports HH:MM:SS format for timestamps exceeding 1 hour.
        """
        if not scene_ranges:
            return []

        def sec_to_time(s: float) -> str:
            h = int(s // 3600)
            m = int((s % 3600) // 60)
            sec = int(s % 60)
            if h > 0:
                return f"{h:02d}:{m:02d}:{sec:02d}"
            return f"{m:02d}:{sec:02d}"

        args = []
        for start, end in scene_ranges:
            if end > start:
                args.extend(["--download-sections", f"*{sec_to_time(start)}-{sec_to_time(end)}"])
        return args

    @staticmethod
    def get_yt_dlp_download_cmd(url: str, output_path: str, resolution: str = "720p") -> List[str]:
        """
        Builds optimized yt-dlp download command with -N 5 multi-threading,
        forced overwrites, and 720p preference to prevent YouTube bandwidth throttling.
        """
        res_filter = "height<=720" if resolution == "720p" else "height<=1080"
        format_spec = f"bestvideo[{res_filter}][ext=mp4]+bestaudio[ext=m4a]/best[{res_filter}][ext=mp4]/best"
        return [
            "yt-dlp",
            "--force-overwrites",
            "--no-continue",
            "--no-playlist",
            "--no-interactive",
            "--no-warnings",
            "--no-progress",
            "--socket-timeout", "20",
            "--retries", "10",
            "--fragment-retries", "10",
            "-N", "5",
            "-f", format_spec,
            "--no-check-certificates",
            "-o", output_path,
            "--",
            url
        ]

    @staticmethod
    def download_youtube_video(url: str, output_path: str, resolution: str = "720p", force: bool = False) -> bool:
        """Downloads 720p/1080p source video cleanly and fast via multi-threaded yt-dlp."""
        if not VideoEngine.is_valid_youtube_url(url):
            return False
        if force and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except Exception:
                pass
        cmd = VideoEngine.get_yt_dlp_download_cmd(url, output_path, resolution=resolution)
        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=300
            )
            return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        except Exception as e:
            print(f"[download_youtube_video error] {e}")
            return False

    @staticmethod
    def download_youtube_sections(
        url: str,
        scene_ranges: List[Tuple[float, float]],
        output_video: str,
        temp_dir: str,
        job_id: str
    ) -> bool:
        """
        Selectively downloads ONLY the required timestamp sections from YouTube
        using yt-dlp --download-sections, saving 95%+ download time and bandwidth.
        """
        sec_args = VideoEngine.build_yt_dlp_section_args(scene_ranges)
        if not sec_args or not VideoEngine.is_valid_youtube_url(url):
            return False

        sec_out_pattern = os.path.join(temp_dir, f"{job_id}_sec_%(section_number)s.%(ext)s")
        cmd = [
            "yt-dlp",
            "--no-warnings",
            "--no-progress",
            "--no-playlist",
            "--socket-timeout", "20",
            "--retries", "10",
            "--fragment-retries", "10",
            "-N", "5",
            "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]/best",
            "--merge-output-format", "mp4",
            "--no-check-certificates"
        ] + sec_args + [
            "-o", sec_out_pattern,
            "--",
            url
        ]

        try:
            res = subprocess.run(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180
            )
        except Exception:
            pass

        sec_files = []
        try:
            if os.path.exists(temp_dir):
                for f in os.listdir(temp_dir):
                    if f.startswith(f"{job_id}_sec_") and not f.endswith(".part") and not f.endswith(".ytdl"):
                        fp = os.path.join(temp_dir, f)
                        try:
                            if os.path.exists(fp) and os.path.getsize(fp) > 1000:
                                sec_files.append(fp)
                        except Exception:
                            pass
        except Exception:
            pass

        if not sec_files:
            return False

        sec_files.sort()

        if len(sec_files) == 1:
            try:
                # Re-encode to valid mp4 — handles webm (VP9/Opus) → mp4 (H.264/AAC)
                ffmpeg_bin = get_ffmpeg_binary()
                r = subprocess.run(
                    [ffmpeg_bin, "-y", "-i", sec_files[0],
                     "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                     "-c:a", "aac", "-b:a", "128k",
                     output_video],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                if r.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
                    return True
                # Fallback: plain copy if encode also failed
                shutil.copyfile(sec_files[0], output_video)
                return os.path.exists(output_video) and os.path.getsize(output_video) > 1000
            except Exception:
                pass
            return False

        ffmpeg_bin = get_ffmpeg_binary()
        concat_list = os.path.join(temp_dir, f"{job_id}_concat_secs.txt")
        try:
            with open(concat_list, "w", encoding="utf-8") as f:
                for sf in sec_files:
                    clean_p = sf.replace("\\", "/")
                    f.write(f"file '{clean_p}'\n")

            # Re-encode (not -c copy) so mixed webm/mp4 containers all merge cleanly
            c_cmd = [
                ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                output_video
            ]
            c_res = subprocess.run(c_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if c_res.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 1000:
                return True
        except Exception:
            pass

        return os.path.exists(output_video) and os.path.getsize(output_video) > 1000

    @staticmethod
    def ensure_footage_integrity(
        url: str,
        job_id: str,
        speech_dur: float,
        temp_dir: str,
        resolution: str = "720p",
        scene_ranges: Optional[List[Tuple[float, float]]] = None
    ) -> str:
        """
        Bulletproof source ingestion system:
        1. Strictly downloads ONLY required scene sections (3-5s each) from YouTube.
        2. Never downloads full 1-3 hour movies, avoiding bandwidth throttling and pipe deadlocks.
        3. Validates duration against required voiceover duration.
        """
        sections_path = os.path.join(temp_dir, f"{job_id}_sections_raw.mp4")

        # For local file paths:
        if os.path.exists(url):
            return url

        # For YouTube URLs: Strictly prioritize selective 3-5s section downloading across any timeline
        if VideoEngine.is_valid_youtube_url(url):
            effective_ranges = list(scene_ranges or [])
            target_clip_dur = 4.5
            num_needed = max(8, int(math.ceil(speech_dur / target_clip_dur)))
            current_covered = sum(max(0.0, e - s) for s, e in effective_ranges)

            # If ranges empty or insufficient to cover speech_dur, generate enough 4.5s section ranges
            if len(effective_ranges) < num_needed or current_covered < speech_dur * 0.9:
                step = max(20.0, 1800.0 / max(1, num_needed))
                effective_ranges = [(i * step + 10.0, i * step + 10.0 + target_clip_dur) for i in range(num_needed)]

            selective_ok = VideoEngine.download_youtube_sections(url, effective_ranges, sections_path, temp_dir, job_id)
            if selective_ok and os.path.exists(sections_path) and os.path.getsize(sections_path) > 0:
                return sections_path

            # Attempt 2: Retry with wider padding window (+/- 1.0s) — NEVER full movie
            print(f"[FootageIntegrity] Retrying selective extraction for job '{job_id}' with padded window...")
            padded_ranges = [(max(0.0, s - 1.0), e + 1.0) for s, e in effective_ranges[:num_needed]]
            retry_ok = VideoEngine.download_youtube_sections(url, padded_ranges, sections_path, temp_dir, job_id)
            if retry_ok and os.path.exists(sections_path) and os.path.getsize(sections_path) > 0:
                return sections_path

            raise RuntimeError(
                f"SourceIntegrityError: Failed to selectively extract footage from YouTube for job '{job_id}'. "
                f"Full movie download is permanently disabled."
            )

        raise RuntimeError(f"SourceIntegrityError: Invalid video source '{url}'. Must be a valid YouTube URL or local file.")


    @staticmethod
    def detect_camera_cuts_in_window(
        video_path: str,
        start: float,
        end: float,
        threshold: float = 10.0
    ) -> List[Tuple[float, float]]:
        """
        Detects actual visual camera cuts in the video between start and end using FFmpeg's native scdet filter.
        Returns a list of shot boundaries [(s1, e1), (s2, e2), ...].
        If no cuts are detected or on error, returns [(start, end)].
        """
        dur = end - start
        if dur <= 4.5 or not os.path.exists(video_path):
            return [(start, end)]

        ffmpeg_bin = get_ffmpeg_binary()
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", str(round(start, 2)),
            "-to", str(round(end, 2)),
            "-i", video_path,
            "-vf", f"scdet=threshold={threshold}",
            "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
            cut_times = [float(m) for m in re.findall(r'lavfi\.scd\.time:\s*([\d\.]+)', res.stderr)]
            abs_cuts = [round(start + ct, 2) for ct in cut_times if 0.8 < ct < (dur - 0.8)]
            if not abs_cuts:
                return [(start, end)]

            points = [start] + sorted(list(set(abs_cuts))) + [end]
            shots = []
            for i in range(len(points) - 1):
                p_s, p_e = points[i], points[i+1]
                if p_e - p_s >= 1.2:
                    shots.append((p_s, p_e))
                elif shots:
                    shots[-1] = (shots[-1][0], p_e)
            return shots if shots else [(start, end)]
        except Exception:
            return [(start, end)]

    @staticmethod
    def verify_timeline_integrity(cuts: List[Tuple[float, float]], expected_duration: float) -> bool:
        """
        Pre-render sanity check ensuring total micro-clip cut duration matches target within tolerance.
        """
        if not cuts:
            return False
        total_dur = sum(max(0.0, e - s) for s, e in cuts)
        return abs(total_dur - expected_duration) <= max(3.0, expected_duration * 0.10)

    @staticmethod
    def slice_and_assemble_scenes(
        input_video: str,
        scene_ranges: List[Tuple[float, float]],
        target_duration: float,
        output_video: str,
        temp_dir: str,
        job_id: str,
        scene_blocks: Optional[List[Any]] = None
    ) -> str:
        """
        Slices chronological 3-4s micro-clips across the entire movie matching storyboard timestamps,
        preventing static scene boredom and Content ID match.
        """
        ffmpeg_bin = get_ffmpeg_binary()
        total_movie_dur = VideoEngine.get_duration(input_video)

        # Build strictly chronological micro-scene map
        cuts = VideoEngine.build_chronological_scene_map(
            scene_ranges=scene_ranges,
            total_movie_dur=total_movie_dur,
            target_duration=target_duration,
            micro_clip_dur=3.5,
            scene_blocks=scene_blocks
        )

        slice_paths = []
        concat_file = os.path.join(temp_dir, f"{job_id}_concat.txt")

        try:
            for idx, (s_sec, e_sec) in enumerate(cuts):
                dur = max(1.5, e_sec - s_sec)
                slice_p = os.path.join(temp_dir, f"{job_id}_sc_{idx}.mp4")
                cmd = [
                    ffmpeg_bin, "-y",
                    "-ss", str(round(s_sec, 2)),
                    "-t", str(round(dur, 2)),
                    "-i", input_video,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-an",
                    slice_p
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(slice_p) and os.path.getsize(slice_p) > 0:
                    slice_paths.append(slice_p)

            if slice_paths:
                with open(concat_file, "w", encoding="utf-8") as f:
                    for sp in slice_paths:
                        safe_p = sp.replace("\\", "/")
                        f.write(f"file '{safe_p}'\n")

                cmd_concat = [
                    ffmpeg_bin, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    output_video
                ]
                res = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 0:
                    return output_video
        except Exception as e:
            print(f"[Slice & Assemble Notice] {e}")
        finally:
            for sp in slice_paths:
                if os.path.exists(sp):
                    try: os.remove(sp)
                    except Exception: pass
            if os.path.exists(concat_file):
                try: os.remove(concat_file)
                except Exception: pass

        return VideoEngine.sample_timeline(input_video, target_duration, total_movie_dur, output_video, temp_dir, job_id)

    @staticmethod
    def sample_timeline(
        input_video: str,
        target_dur: float,
        movie_dur: float,
        output_video: str,
        temp_dir: str,
        job_id: str
    ) -> str:
        """Fallback timeline sampler: extracts 6-10 milestone clips evenly across the entire movie."""
        ffmpeg_bin = get_ffmpeg_binary()
        num_scenes = max(8, int(round(target_dur / 3.8)))
        clip_dur = target_dur / num_scenes
        interval = max(0.5, (movie_dur - clip_dur) / max(1, num_scenes - 1)) if movie_dur > clip_dur else 1.0

        slice_paths = []
        concat_file = os.path.join(temp_dir, f"{job_id}_sample_concat.txt")

        try:
            for i in range(num_scenes):
                start_t = i * interval
                slice_p = os.path.join(temp_dir, f"{job_id}_sample_{i}.mp4")
                cmd = [
                    ffmpeg_bin, "-y",
                    "-ss", str(round(start_t, 2)),
                    "-t", str(round(clip_dur, 2)),
                    "-i", input_video,
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-an",
                    "-vf", "setpts=PTS-STARTPTS",
                    slice_p
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(slice_p) and os.path.getsize(slice_p) > 0:
                    slice_paths.append(slice_p)

            if len(slice_paths) >= 2:
                with open(concat_file, "w", encoding="utf-8") as f:
                    for sp in slice_paths:
                        safe_p = sp.replace("\\", "/")
                        f.write(f"file '{safe_p}'\n")

                cmd_concat = [
                    ffmpeg_bin, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    output_video
                ]
                subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists(output_video) and os.path.getsize(output_video) > 0:
                    return output_video
        finally:
            for sp in slice_paths:
                if os.path.exists(sp):
                    try: os.remove(sp)
                    except Exception: pass
            if os.path.exists(concat_file):
                try: os.remove(concat_file)
                except Exception: pass

        return input_video

    @staticmethod
    def get_safe_story_duration(
        total_movie_dur: float,
        dialogue_timeline: Optional[List[Dict[str, Any]]] = None
    ) -> float:
        """
        Smart Transcript-Driven Climax Guard.
        If dialogue_timeline is available, sets safe boundary to min(total_movie_dur, last_dialogue_end + 15.0).
        Preserves 100% of the climax for videos without end credits, while cleanly excluding silent credits.
        """
        if dialogue_timeline and len(dialogue_timeline) > 0:
            last_end = max((float(c.get("end", 0.0)) for c in dialogue_timeline), default=0.0)
            if last_end > 60.0:
                return min(float(total_movie_dur), last_end + 15.0)

        if total_movie_dur <= 600.0:
            return float(total_movie_dur)
        credits_margin = max(120.0, min(float(total_movie_dur) * 0.065, 360.0))
        return max(300.0, float(total_movie_dur) - credits_margin)

    @staticmethod
    def clamp_safe_movie_start(movie_start: float, safe_movie_dur: float, narration_dur: float = 3.5) -> float:
        """
        Clamps movie_start strictly within safe storytelling window (leaving credits out)
        without modulo wrap-around to early movie footage.
        """
        ms = max(0.0, float(movie_start))
        if safe_movie_dur > 2.0 and ms >= safe_movie_dur - 1.0:
            ms = round(max(0.0, safe_movie_dur - narration_dur - 1.0), 2)
        return ms

    @staticmethod
    def build_audio_locked_scene_clips(
        input_video: str,
        scene_blocks: List[Any],
        temp_dir: str,
        job_id: str,
        output_video: str
    ) -> str:
        """
        Audio-Locked Scene Clip Engine (Principal Engineer Fix — Scene-Voiceover Desync).

        Produces one video clip per SceneBlock where clip.duration == block.narration_dur exactly.
        This eliminates the core desynchronization bug where video played in a continuous loop
        while audio narrated specific scenes from specific timestamps.

        Per-block strategy:
          1. Cut source movie at [movie_start .. movie_end] with PTS reset.
          2. Compute speed_ratio = movie_window / narration_dur:
             - ratio in [0.5, 2.0]: apply setpts={ratio}*PTS to match clip duration to narration.
             - ratio > 2.0 (movie much longer): trim clip to narration_dur exactly.
             - ratio < 0.5 (movie clip too short):
               * Option-C (primary): extend movie_end forward by narration_dur from movie_start,
                 capped at total movie duration — natural, seamless continuation.
               * Option-B (fallback at video end): if extending would exceed movie duration,
                 freeze the last frame using tpad + slow zoompan push-in.
          3. Concatenate all adjusted clips into output_video.
          4. Falls back to sample_timeline() on any exception.

        Args:
            input_video:  Path to the source movie file.
            scene_blocks: List[SceneBlock] — must have narration_start/end set by
                          assign_narration_timing() before this is called.
            temp_dir:     Temporary directory for intermediate clip files.
            job_id:       Unique job identifier for clip file naming.
            output_video: Final assembled output path.

        Returns:
            Path to assembled video (output_video on success, fallback path otherwise).
        """
        import math as _math
        ffmpeg_bin = get_ffmpeg_binary()

        # Guard: empty/missing blocks or input video
        if not scene_blocks or not input_video or not os.path.exists(input_video):
            print("[AudioLockedSync] No scene blocks or input video — falling back to sample_timeline")
            total_dur = sum(
                VideoEngine._get_block_narration_dur(b) for b in (scene_blocks or [])
            ) or 60.0
            if input_video and os.path.exists(input_video):
                return VideoEngine.sample_timeline(
                    input_video, total_dur, VideoEngine.get_duration(input_video),
                    output_video, temp_dir, job_id
                )
            return output_video

        try:
            meta = VideoEngine.probe_media(input_video)
            total_movie_dur = float(meta.get("duration", 0.0))
        except Exception:
            total_movie_dur = VideoEngine.get_duration(input_video)

        # Universal End-Credits Blacklist Guard: Never slice from the end credits
        safe_movie_dur = VideoEngine.get_safe_story_duration(total_movie_dur)
        clip_paths: List[str] = []
        concat_file = os.path.join(temp_dir, f"{job_id}_alc_concat.txt")

        # Check if input_video is a selective compilation (selective footage length < max movie timestamps)
        max_req_start = max(((float(b["movie_start"]) if isinstance(b, dict) else float(getattr(b, "movie_start", 0.0))) for b in scene_blocks), default=0.0)
        is_selective_compilation = total_movie_dur < max_req_start and total_movie_dur > 0.0

        try:
            for idx, block in enumerate(scene_blocks):
                narration_dur = VideoEngine._get_block_narration_dur(block)

                clip_out = os.path.join(temp_dir, f"{job_id}_alc_{idx}.mp4")

                # If input_video is a selective compilation, cut using local timeline offset (Rule 2)
                if is_selective_compilation:
                    raw_n_start = block.get("narration_start", 0.0) if isinstance(block, dict) else getattr(block, "narration_start", 0.0)
                    local_anchor = min(max(0.0, float(raw_n_start)), max(0.0, total_movie_dur - narration_dur))
                    avail = max(0.1, total_movie_dur - local_anchor)
                    cut_dur = min(narration_dur, avail)
                    gap = round(narration_dur - cut_dur, 3) if cut_dur < narration_dur else 0.0

                    vf_filter = "setpts=PTS-STARTPTS,fps=24"
                    if gap > 0.05:
                        vf_filter += f",tpad=stop_mode=clone:stop_duration={gap}"

                    cmd_cut_local = [
                        ffmpeg_bin, "-y",
                        "-ss", str(round(local_anchor, 3)),
                        "-t", str(round(cut_dur, 3)),
                        "-i", input_video,
                        "-vf", vf_filter,
                        "-t", str(round(narration_dur, 3)),
                        "-avoid_negative_ts", "make_zero",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-an",
                        clip_out
                    ]
                    res_local = subprocess.run(cmd_cut_local, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res_local.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                        clip_paths.append(clip_out)
                        continue

                # Clamp movie_start strictly within safe storytelling window (leaving credits out)
                raw_m_start = block.get("movie_start", 0.0) if isinstance(block, dict) else getattr(block, "movie_start", 0.0)
                raw_m_end = block.get("movie_end", raw_m_start + 5.0) if isinstance(block, dict) else getattr(block, "movie_end", raw_m_start + 5.0)
                movie_start = VideoEngine.clamp_safe_movie_start(raw_m_start, safe_movie_dur, narration_dur)

                movie_end = min(max(movie_start + 1.0, float(raw_m_end)), safe_movie_dur)
                movie_window = max(0.1, movie_end - movie_start)

                # ── Strategy selection ─────────────────────────────────────────
                speed_ratio = movie_window / narration_dur if narration_dur > 0 else 1.0


                # 3-5 Second Micro-Cut Rule:
                # If narration_dur > 5.0, slice 3 to 4 sequential micro-cuts (each 3.0s-5.0s)
                # centered around the anchored dialogue timestamp (movie_start).
                if narration_dur > 5.0 and safe_movie_dur > 5.0:
                    n_cuts = max(2, int(round(narration_dur / 3.8)))
                    base_dur = round(narration_dur / n_cuts, 3)
                    mc_durs = [base_dur] * n_cuts
                    mc_durs[-1] = round(narration_dur - sum(mc_durs[:-1]), 3)

                    # Center cuts around the anchored dialogue timestamp within safe movie duration
                    scene_anchor = max(0.0, min(max(0.0, safe_movie_dur - narration_dur), movie_start))
                    scene_end = min(safe_movie_dur, max(movie_end, scene_anchor + narration_dur))
                    actual_span = max(0.1, scene_end - scene_anchor)

                    if actual_span >= narration_dur:
                        max_offset = actual_span - mc_durs[0]
                        step = max_offset / max(1, n_cuts - 1) if n_cuts > 1 else 0.0
                        cut_starts = [round(max(0.0, min(safe_movie_dur - mc_durs[k], scene_anchor + k * step)), 3) for k in range(n_cuts)]
                    else:
                        cut_starts = [round(max(0.0, min(safe_movie_dur - mc_durs[k], scene_anchor + sum(mc_durs[:k]))), 3) for k in range(n_cuts)]

                    # If speed_ratio < 0.5 (extension required), record the extended -to call for Option-C
                    extended_end = min(safe_movie_dur, movie_start + narration_dur)
                    if speed_ratio < 0.5:
                        clip_scene = os.path.join(temp_dir, f"{job_id}_alc_{idx}_scene.mp4")
                        cmd_extend = [
                            ffmpeg_bin, "-y",
                            "-ss", str(round(movie_start, 3)),
                            "-to", str(round(extended_end, 3)),
                            "-i", input_video,
                            "-vf", "setpts=PTS-STARTPTS,fps=24",
                            "-t", str(round(narration_dur, 3)),
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                            "-an",
                            clip_scene
                        ]
                        subprocess.run(cmd_extend, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    mc_paths = []
                    mc_concat_file = os.path.join(temp_dir, f"{job_id}_alc_{idx}_mc_concat.txt")

                    for k in range(n_cuts):
                        this_dur = mc_durs[k]
                        cut_s = cut_starts[k]
                        mc_out = os.path.join(temp_dir, f"{job_id}_alc_{idx}_mc_{k}.mp4")
                        avail = max(0.0, total_movie_dur - cut_s)

                        if avail >= this_dur:
                            cmd_mc = [
                                ffmpeg_bin, "-y",
                                "-ss", str(round(cut_s, 3)),
                                "-t", str(round(this_dur, 3)),
                                "-i", input_video,
                                "-vf", "setpts=PTS-STARTPTS,fps=24",
                                "-t", str(round(this_dur, 3)),
                                "-avoid_negative_ts", "make_zero",
                                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                                "-an",
                                mc_out
                            ]
                        else:
                            gap = round(this_dur - avail, 3)
                            cmd_mc = [
                                ffmpeg_bin, "-y",
                                "-ss", str(round(cut_s, 3)),
                                "-t", str(round(max(0.1, avail), 3)),
                                "-i", input_video,
                                "-vf", f"setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration={gap}",
                                "-t", str(round(this_dur, 3)),
                                "-avoid_negative_ts", "make_zero",
                                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                                "-an",
                                mc_out
                            ]
                        res_mc = subprocess.run(cmd_mc, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        if res_mc.returncode == 0 and os.path.exists(mc_out) and os.path.getsize(mc_out) > 0:
                            mc_paths.append(mc_out)

                    if len(mc_paths) == n_cuts:
                        with open(mc_concat_file, "w", encoding="utf-8") as f_mc:
                            for p in mc_paths:
                                clean_p = p.replace("\\", "/")
                                f_mc.write(f"file '{clean_p}'\n")

                        cmd_mc_concat = [
                            ffmpeg_bin, "-y",
                            "-f", "concat", "-safe", "0",
                            "-i", mc_concat_file,
                            "-c", "copy",
                            clip_out
                        ]
                        res_c = subprocess.run(cmd_mc_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        for p in mc_paths:
                            if os.path.exists(p):
                                try: os.remove(p)
                                except Exception: pass
                        if os.path.exists(mc_concat_file):
                            try: os.remove(mc_concat_file)
                            except Exception: pass

                        if res_c.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                            clip_paths.append(clip_out)
                            continue

                if speed_ratio >= 0.5:
                    # ── Case A: ratio in [0.5, ∞) — cut + setpts or trim ──────
                    cut_end = movie_end
                    if speed_ratio > 2.0:
                        # Movie clip much longer than narration: trim to narration_dur
                        cut_end = min(movie_start + narration_dur, total_movie_dur)

                    orig_clip_dur = max(0.1, cut_end - movie_start)
                    # Correct PTS factor: target speech duration / original cut duration
                    pts_factor = narration_dur / orig_clip_dur

                    cmd_cut = [
                        ffmpeg_bin, "-y",
                        "-ss", str(round(movie_start, 3)),
                        "-to", str(round(cut_end, 3)),
                        "-i", input_video,
                        "-vf", f"setpts={round(pts_factor, 4)}*PTS-STARTPTS,fps=24",
                        "-t", str(round(narration_dur, 3)),
                        "-avoid_negative_ts", "make_zero",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-an",
                        clip_out
                    ]
                    res = subprocess.run(cmd_cut, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                        clip_paths.append(clip_out)
                        continue

                # ── Case B / C: ratio < 0.5 — movie clip too short ────────────
                # Option-C: extend movie_end forward to fill narration_dur
                extended_end = movie_start + narration_dur

                if extended_end <= total_movie_dur:
                    # Option-C: extend the cut — natural continuation, no loop
                    cmd_extend = [
                        ffmpeg_bin, "-y",
                        "-ss", str(round(movie_start, 3)),
                        "-to", str(round(extended_end, 3)),
                        "-i", input_video,
                        "-vf", "setpts=PTS-STARTPTS,fps=24",
                        "-t", str(round(narration_dur, 3)),
                        "-avoid_negative_ts", "make_zero",
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-an",
                        clip_out
                    ]
                    res = subprocess.run(cmd_extend, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    if res.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                        clip_paths.append(clip_out)
                        continue

                # At (or near) end of video — use Option-B: freeze + zoom push
                # Step 1: cut from movie_start to end of movie
                clip_cut = os.path.join(temp_dir, f"{job_id}_alc_{idx}_cut.mp4")
                actual_end = min(total_movie_dur, extended_end)
                gap_remaining = max(0.0, narration_dur - (actual_end - movie_start))

                cmd_cut_b = [
                    ffmpeg_bin, "-y",
                    "-ss", str(round(movie_start, 3)),
                    "-to", str(round(actual_end, 3)),
                    "-i", input_video,
                    "-vf", "setpts=PTS-STARTPTS",
                    "-avoid_negative_ts", "make_zero",
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-an",
                    clip_cut
                ]
                subprocess.run(cmd_cut_b, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                if os.path.exists(clip_cut) and os.path.getsize(clip_cut) > 0 and gap_remaining > 0.05:
                    # Step 2: Option-B — tpad freeze + zoompan subtle push-in
                    freeze_fps = 24
                    freeze_frames = int(math.ceil(gap_remaining * freeze_fps))
                    zoom_step = round(0.05 / max(1, freeze_frames), 6)

                    cmd_freeze = [
                        ffmpeg_bin, "-y",
                        "-i", clip_cut,
                        "-vf",
                        f"tpad=stop_mode=clone:stop_duration={round(gap_remaining, 3)},"
                        f"zoompan=z='min(zoom+{zoom_step},1.05)':d={freeze_frames}"
                        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=iw:sh=ih:fps={freeze_fps}",
                        "-t", str(round(narration_dur, 3)),
                        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                        "-an",
                        clip_out
                    ]
                    res_f = subprocess.run(cmd_freeze, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    if res_f.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                        pass  # success — fall through to cleanup
                    else:
                        # zoompan failed (complex filter) — simpler tpad only
                        cmd_tpad = [
                            ffmpeg_bin, "-y",
                            "-i", clip_cut,
                            "-vf", f"tpad=stop_mode=clone:stop_duration={round(gap_remaining, 3)}",
                            "-t", str(round(narration_dur, 3)),
                            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                            "-an",
                            clip_out
                        ]
                        subprocess.run(cmd_tpad, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

                    # Clean up intermediate cut
                    if os.path.exists(clip_cut):
                        try:
                            os.remove(clip_cut)
                        except Exception:
                            pass

                elif os.path.exists(clip_cut) and os.path.getsize(clip_cut) > 0:
                    # No gap needed — just use the cut directly
                    os.replace(clip_cut, clip_out)

                if os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                    clip_paths.append(clip_out)
                    continue

                # Final per-block fallback: simple -t trim from movie_start with tpad hold
                cmd_fb = [
                    ffmpeg_bin, "-y",
                    "-ss", str(round(movie_start, 3)),
                    "-t", str(round(narration_dur, 3)),
                    "-i", input_video,
                    "-vf", f"setpts=PTS-STARTPTS,fps=24,tpad=stop_mode=clone:stop_duration={round(narration_dur, 3)}",
                    "-t", str(round(narration_dur, 3)),
                    "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
                    "-an",
                    clip_out
                ]
                res_fb = subprocess.run(cmd_fb, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res_fb.returncode == 0 and os.path.exists(clip_out) and os.path.getsize(clip_out) > 0:
                    clip_paths.append(clip_out)

            # ── Concatenate all clips ──────────────────────────────────────────
            if clip_paths:
                with open(concat_file, "w", encoding="utf-8") as f:
                    for cp in clip_paths:
                        safe_p = cp.replace("\\", "/")
                        f.write(f"file '{safe_p}'\n")

                cmd_concat = [
                    ffmpeg_bin, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_file,
                    "-c", "copy",
                    output_video
                ]
                res_c = subprocess.run(cmd_concat, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res_c.returncode == 0 and os.path.exists(output_video) and os.path.getsize(output_video) > 0:
                    print(f"[AudioLockedSync] ✅ Assembled {len(clip_paths)} audio-locked clips → {output_video}")
                    return output_video

        except Exception as e:
            print(f"[AudioLockedSync] Exception during assembly: {e}")
        finally:
            for cp in clip_paths:
                if os.path.exists(cp):
                    try:
                        os.remove(cp)
                    except Exception:
                        pass
            if os.path.exists(concat_file):
                try:
                    os.remove(concat_file)
                except Exception:
                    pass
            # Deep clean any intermediate/leftover clips for this job
            if temp_dir and os.path.exists(temp_dir):
                try:
                    import glob
                    for leftover in glob.glob(os.path.join(temp_dir, f"{job_id}_alc_*")):
                        if os.path.isfile(leftover):
                            try:
                                os.remove(leftover)
                            except Exception:
                                pass
                except Exception:
                    pass

        # ── Global fallback ────────────────────────────────────────────────────
        print("[AudioLockedSync] Falling back to sample_timeline()")
        total_narration_dur = sum(
            VideoEngine._get_block_narration_dur(b) for b in scene_blocks
        )
        return VideoEngine.sample_timeline(
            input_video, total_narration_dur, total_movie_dur, output_video, temp_dir, job_id
        )

    @staticmethod
    def chunk_subtitle_cue(
        text: str,
        start_sec: float,
        end_sec: float,
        max_words: int = 8,
        max_duration: float = 5.0
    ) -> List[Tuple[float, float, str]]:
        """
        Splits long narration cues (>5s or >8 words) into short, punchy 3.0-5.0s lines
        with proportional timestamp distribution for professional readability.
        Strips technical and metadata tags automatically.
        """
        from app.services.script_engine import ScriptEngine
        clean_text = ScriptEngine.strip_production_tags(text).strip()
        if not clean_text:
            return []

        words = clean_text.split()
        total_dur = max(0.1, end_sec - start_sec)

        if len(words) <= max_words and total_dur <= max_duration:
            return [(start_sec, end_sec, clean_text)]

        chunks_by_words = max(1, int(math.ceil(len(words) / max_words)))
        chunks_by_time = max(1, int(math.ceil(total_dur / max_duration)))
        num_chunks = max(chunks_by_words, chunks_by_time)

        words_per_chunk = int(math.ceil(len(words) / num_chunks))
        text_slices = []
        for i in range(0, len(words), words_per_chunk):
            chunk_slice = " ".join(words[i:i + words_per_chunk]).strip()
            if chunk_slice:
                text_slices.append(chunk_slice)

        if not text_slices:
            return [(start_sec, end_sec, clean_text)]

        total_chars = sum(len(s) for s in text_slices)
        cues = []
        curr_t = start_sec
        for idx, s in enumerate(text_slices):
            prop = len(s) / max(1, total_chars)
            seg_dur = round(total_dur * prop, 3)
            next_t = round(curr_t + seg_dur, 3) if idx < len(text_slices) - 1 else end_sec
            if next_t > curr_t:
                cues.append((curr_t, next_t, s))
            curr_t = next_t

        return cues

    @staticmethod
    @staticmethod
    def escape_ass_text(text: str) -> str:
        """
        Escapes ASS override-block delimiters in dialogue text.
        A stray '{' would make libass swallow the rest of the cue as an
        override block; '\\{' / '\\}' are the documented literal escapes.
        No bidi controls are added, so RTL (Urdu/Arabic) shaping is untouched.
        """
        return text.replace("{", "\\{").replace("}", "\\}")

    def generate_ass_subtitle_file(
        scene_subtitles: List[str],
        total_duration: float,
        output_ass_path: str,
        aspect_ratio: str = "horizontal",
        lang: str = "en",
        timed_cues: Optional[List[Dict[str, Any]]] = None,
        speed_factor: float = 1.02,
        chunk_cues: bool = False
    ) -> bool:
        """
        Generates an Advanced SubStation Alpha (.ass) file with HarfBuzz/FriBiDi compatible
        styling, dark pillbox background, and proper margins for YouTube/TikTok safe zones.
        Uses exact Edge-TTS boundary timestamps (or character-proportional timing) scaled
        by speed_factor to match synchronized atempo/setpts drift.
        Eliminates tofu boxes ([][][]) for Urdu, Arabic, and Hindi text.
        """
        if (not scene_subtitles and not timed_cues) or total_duration <= 0:
            return False

        from app.services.script_engine import ScriptEngine

        res_x = 1080 if aspect_ratio == "vertical" else (1080 if aspect_ratio == "square" else 1920)
        res_y = 1920 if aspect_ratio == "vertical" else (1080 if aspect_ratio == "square" else 1080)

        # Language-Adaptive High-Visibility Typography Engine
        if lang in ["ur", "ar"]:
            font_name = "Noto Nastaliq Urdu"
            font_size = 64 if aspect_ratio == "vertical" else 54
            box_padding = 14 if aspect_ratio == "vertical" else 12
            margin_v = 140 if aspect_ratio == "vertical" else 85
        elif lang == "hi":
            font_name = "Nirmala UI"
            font_size = 56 if aspect_ratio == "vertical" else 48
            box_padding = 12 if aspect_ratio == "vertical" else 10
            margin_v = 140 if aspect_ratio == "vertical" else 80
        else:
            font_name = "Arial Black"
            font_size = 54 if aspect_ratio == "vertical" else 46
            box_padding = 12 if aspect_ratio == "vertical" else 10
            margin_v = 140 if aspect_ratio == "vertical" else 80

        ass_lines = [
            "[Script Info]",
            "ScriptType: v4.00+",
            f"PlayResX: {res_x}",
            f"PlayResY: {res_y}",
            "",
            "[V4+ Styles]",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
            f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HB0000000,1,0,0,0,100,100,0,0,3,{box_padding},0,2,30,30,{margin_v},1",
            "",
            "[Events]",
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
        ]

        def sec_to_ass(s_val: float) -> str:
            h = int(s_val // 3600)
            m = int((s_val % 3600) // 60)
            s = int(s_val % 60)
            cs = int(round((s_val - int(s_val)) * 100))
            if cs >= 100:
                cs = 99
            return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

        sf = max(0.01, speed_factor)
        effective_dur = total_duration / sf

        if timed_cues and len(timed_cues) > 0:
            for cue in timed_cues:
                raw_text = ScriptEngine.strip_production_tags(str(cue.get("text", ""))).strip().replace("\r", " ").replace("\n", " ")
                if not raw_text:
                    continue
                t_s = max(0.0, float(cue.get("start", 0.0))) / sf
                t_e = min(effective_dur, float(cue.get("end", t_s + 2.5)) / sf)
                if t_e <= t_s:
                    t_e = min(effective_dur, t_s + 1.5)

                if chunk_cues:
                    cues_to_add = VideoEngine.chunk_subtitle_cue(raw_text, t_s, t_e)
                else:
                    cues_to_add = [(t_s, t_e, raw_text)]

                for sub_s, sub_e, sub_text in cues_to_add:
                    start_str = sec_to_ass(sub_s)
                    end_str = sec_to_ass(sub_e)
                    ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{VideoEngine.escape_ass_text(sub_text)}")
        elif scene_subtitles:
            # Proportional duration based on string length (Syllable/Character-weighted)
            clean_subs = [ScriptEngine.strip_production_tags(s).strip().replace("\r", " ").replace("\n", " ") for s in scene_subtitles if s.strip()]
            clean_subs = [s for s in clean_subs if s]
            total_chars = sum(max(1, len(s)) for s in clean_subs)
            curr_time = 0.0
            for idx, text_snip in enumerate(clean_subs):
                prop = len(text_snip) / max(1, total_chars)
                cue_dur = max(1.8, prop * effective_dur)
                t_s = curr_time
                t_e = min(effective_dur, t_s + cue_dur)
                if idx == len(clean_subs) - 1:
                    t_e = effective_dur
                if t_e > t_s:
                    if chunk_cues:
                        cues_to_add = VideoEngine.chunk_subtitle_cue(text_snip, t_s, t_e)
                    else:
                        cues_to_add = [(t_s, t_e, text_snip)]

                    for sub_s, sub_e, sub_text in cues_to_add:
                        start_str = sec_to_ass(sub_s)
                        end_str = sec_to_ass(sub_e)
                        ass_lines.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{VideoEngine.escape_ass_text(sub_text)}")
                    curr_time = t_e

        try:
            with open(output_ass_path, "w", encoding="utf-8") as f:
                f.write("\n".join(ass_lines))
            return os.path.exists(output_ass_path) and os.path.getsize(output_ass_path) > 50
        except Exception:
            return False

    @staticmethod
    def render_final_explainer(
        video_source: str,
        audio_source: str,
        output_path: str,
        duration: float,
        aspect_ratio: str = "vertical",
        burn_subtitles: bool = True,
        scene_subtitles: Optional[List[str]] = None,
        watermark: str = "",
        part_number: int = 1,
        num_parts: int = 1,
        lang: str = "en",
        anti_copyright_drift: bool = True,
        **kwargs
    ) -> bool:
        """
        Renders complete production-ready explainer video:
        - 9:16 Vertical with 100% full-width movie and blurred top/bottom backdrop.
        - Anti-copyright color grade & synchronized micro-speed drift (PTS/1.02 & atempo=1.02).
        - Dynamic burned captions with dark pill box via libass (.ass) for flawless RTL Urdu/Arabic shaping.
        - Channel watermark & optional Part badge for multi-part series.
        """
        ffmpeg_bin = get_ffmpeg_binary()
        font_esc = VideoEngine.get_font_for_lang(lang)
        font_clause = f":fontfile='{font_esc}'" if font_esc else ""

        filter_parts = []
        if aspect_ratio == "vertical":
            filter_parts.append(
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,boxblur=24:5,eq=brightness=-0.15[bg];"
                "[0:v]scale=1080:-2,setsar=1[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[vcomp]"
            )
            v_base = "[vcomp]"
        elif aspect_ratio == "square":
            filter_parts.append(
                "[0:v]scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080,setsar=1[vcomp]"
            )
            v_base = "[vcomp]"
        else: # Horizontal 16:9
            filter_parts.append(
                "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1[vcomp]"
            )
            v_base = "[vcomp]"

        drift_enabled = bool(kwargs.get("anti_copyright_drift", anti_copyright_drift))
        speed_factor = 1.02 if drift_enabled else 1.0

        post_vf = []
        # Hold frame buffer to guarantee video stream never terminates before master soundtrack
        tpad_hold = max(60, int(duration + 30))
        post_vf.append(f"tpad=stop_mode=clone:stop_duration={tpad_hold}")

        # Anti-copyright: color grade + speed sync
        if drift_enabled:
            post_vf.append("eq=contrast=1.03:brightness=0.01:saturation=1.06")
            post_vf.append("setpts=PTS/1.02")

        # Part Badge at top (ONLY render if multi-part series mode is enabled with num_parts > 1)
        if num_parts > 1 and part_number >= 1:
            badge_y = "140" if aspect_ratio == "vertical" else "50"
            badge_text = VideoEngine.escape_ffmpeg_drawtext(f"PART {part_number}")
            post_vf.append(
                f"drawtext=text='{badge_text}'{font_clause}:x=(w-text_w)/2:y={badge_y}:fontsize=44:fontcolor=yellow:box=1:boxcolor=black@0.75:boxborderw=10"
            )

        # Watermark
        if watermark:
            clean_wm = VideoEngine.escape_ffmpeg_drawtext(re.sub(r"[^a-zA-Z0-9\s.@_-]", "", watermark))
            wm_y = "70" if aspect_ratio == "vertical" else "25"
            post_vf.append(
                f"drawtext=text='{clean_wm}'{font_clause}:x=(w-text_w)/2:y={wm_y}:fontsize=26:fontcolor=white@0.85"
            )

        # Dynamic Subtitles via libass (.ass) - eliminates tofu boxes for Urdu, Arabic, Hindi, etc.
        temp_ass_path = None
        timed_cues = kwargs.get("timed_cues")
        if burn_subtitles and (scene_subtitles or timed_cues):
            out_dir = os.path.dirname(output_path) or str(TEMP_DIR)
            temp_ass_path = os.path.join(out_dir, f"subs_{uuid.uuid4().hex[:8]}.ass")
            if VideoEngine.generate_ass_subtitle_file(
                scene_subtitles=scene_subtitles or [],
                total_duration=duration,
                output_ass_path=temp_ass_path,
                aspect_ratio=aspect_ratio,
                lang=lang,
                timed_cues=timed_cues,
                speed_factor=speed_factor,
                chunk_cues=True
            ):
                clean_ass = temp_ass_path.replace("\\", "/").replace(":", "\\:")
                fonts_dir_esc = str(FONTS_DIR.resolve()).replace("\\", "/").replace(":", "\\:")
                post_vf.append(f"subtitles='{clean_ass}':fontsdir='{fonts_dir_esc}'")

        if not post_vf:
            post_vf.append("null")
        filter_parts.append(f";{v_base}{','.join(post_vf)}[vfinal]")
        if drift_enabled:
            filter_parts.append(";[1:a]atempo=1.02[afinal]")
        else:
            filter_parts.append(";[1:a]anull[afinal]")
        final_filter = "".join(filter_parts)

        # Exact matched duration for both synchronized streams
        render_dur = round(duration / speed_factor, 2)

        cmd = [
            ffmpeg_bin, "-y",
            "-i", video_source,
            "-i", audio_source,
            "-filter_complex", final_filter,
            "-map", "[vfinal]",
            "-map", "[afinal]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ac", "2",
            "-t", str(render_dur),
            output_path
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        finally:
            if temp_ass_path and os.path.exists(temp_ass_path):
                try: os.remove(temp_ass_path)
                except Exception: pass
