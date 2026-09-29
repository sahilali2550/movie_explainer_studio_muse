import os
import random
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any
from app.core.config import MUSIC_DIR, SFX_DIR, get_ffmpeg_binary

class AudioMixer:
    """
    Universal Audio Mixing & Soundscape Engine.
    Handles background mood music selection, procedural synth fallbacks,
    dynamic sidechain ducking, non-attenuated amix mixing, and master track normalization.
    """

    @staticmethod
    def get_mood_music_track(mood: str = "suspense") -> Optional[str]:
        """
        Retrieves a random copyright-free track from the curated mood directory
        with intelligent fallback across mood aliases.
        """
        mood_fallbacks = {
            "suspense": ["suspense", "dark", "tense"],
            "tense": ["tense", "action", "dark"],
            "action": ["action", "tense", "dark"],
            "emotional": ["emotional", "chill"],
            "upbeat": ["upbeat", "chill"],
            "horror": ["horror", "dark", "tense"],
            "dark": ["dark", "suspense", "tense"],
            "chill": ["chill", "emotional"]
        }
        folders_to_try = mood_fallbacks.get(mood, [mood, "dark", "suspense", "tense"])
        for folder_name in folders_to_try:
            mood_folder = MUSIC_DIR / folder_name
            if mood_folder.exists() and mood_folder.is_dir():
                tracks = [str(f) for f in mood_folder.iterdir() if f.suffix.lower() in [".mp3", ".wav", ".aac", ".m4a"]]
                if tracks:
                    return random.choice(tracks)
        return None

    @staticmethod
    def generate_procedural_synth(output_path: str, duration: float, mood: str = "suspense") -> bool:
        """
        Generates clean, royalty-free procedural ambient soundtrack via FFmpeg lavfi filters.
        Creates a warm, lowpass-filtered cinematic drone/pad rather than a raw sine beep.
        """
        ffmpeg_bin = get_ffmpeg_binary()
        dur = max(2.0, duration)

        if mood in ["suspense", "dark", "horror"]:
            filt = (
                f"[0:a]volume=0.08,lowpass=f=220[d1];"
                f"[1:a]volume=0.06,lowpass=f=260[d2];"
                f"[2:a]volume=0.02,lowpass=f=180[noise];"
                f"[d1][d2][noise]amix=inputs=3:dropout_transition=2:normalize=0,afade=t=in:ss=0:d=1.5,afade=t=out:st={max(0.1, dur-1.5)}:d=1.5[a]"
            )
            inputs = [
                "-f", "lavfi", "-i", f"sine=frequency=55:duration={dur}",
                "-f", "lavfi", "-i", f"sine=frequency=82.41:duration={dur}",
                "-f", "lavfi", "-i", f"anoisesrc=c=pink:r=44100:a=0.05:duration={dur}"
            ]
        elif mood in ["emotional", "chill"]:
            filt = (
                f"[0:a]volume=0.07,lowpass=f=340[p1];"
                f"[1:a]volume=0.06,lowpass=f=380[p2];"
                f"[p1][p2]amix=inputs=2:dropout_transition=2:normalize=0,afade=t=in:ss=0:d=2,afade=t=out:st={max(0.1, dur-2)}:d=2[a]"
            )
            inputs = [
                "-f", "lavfi", "-i", f"sine=frequency=110:duration={dur}",
                "-f", "lavfi", "-i", f"sine=frequency=146.83:duration={dur}"
            ]
        else: # action, tense, upbeat
            filt = (
                f"[0:a]volume=0.08,lowpass=f=280[t1];"
                f"[1:a]volume=0.07,lowpass=f=320[t2];"
                f"[2:a]volume=0.03,lowpass=f=200[noise];"
                f"[t1][t2][noise]amix=inputs=3:dropout_transition=1:normalize=0,afade=t=in:ss=0:d=1,afade=t=out:st={max(0.1, dur-1)}:d=1[a]"
            )
            inputs = [
                "-f", "lavfi", "-i", f"sine=frequency=65.41:duration={dur}",
                "-f", "lavfi", "-i", f"sine=frequency=98.00:duration={dur}",
                "-f", "lavfi", "-i", f"anoisesrc=c=pink:r=44100:a=0.04:duration={dur}"
            ]

        cmd = [
            ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", filt,
            "-map", "[a]",
            "-c:a", "libmp3lame", "-b:a", "192k",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0

    @staticmethod
    def mix_voiceover_and_bgm(
        voice_path: str,
        bgm_path: str,
        output_path: str,
        voice_duration: float,
        bgm_volume: float = 0.16
    ) -> bool:
        """
        Combines voiceover and background score with true dynamic sidechain ducking:
        - Voiceover splits into master audio and sidechain trigger.
        - BGM ducks automatically when speech is active (threshold 0.125, ratio 4:1).
        - amix uses normalize=0 to prevent 1/N voice attenuation.
        """
        ffmpeg_bin = get_ffmpeg_binary()
        dur = max(1.0, round(voice_duration, 2))

        filter_str = (
            f"[0:a]volume=1.0,apad=whole_dur={dur},asplit=2[vox_main][vox_sc];"
            f"[1:a]volume={bgm_volume}[bg_in];"
            f"[bg_in][vox_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=300[bg_ducked];"
            f"[vox_main][bg_ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,atrim=0:{dur},loudnorm=I=-14:TP=-1.5:LRA=11[a]"
        )

        cmd = [
            ffmpeg_bin, "-y",
            "-i", voice_path,
            "-stream_loop", "-1", "-i", bgm_path,
            "-filter_complex", filter_str,
            "-map", "[a]",
            "-c:a", "aac", "-b:a", "192k",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0

    @staticmethod
    def create_isolated_dub_track(
        voice_path: str,
        bgm_path: Optional[str],
        output_path: str,
        target_duration: float,
        bgm_volume: float = 0.16
    ) -> bool:
        """
        Creates a YouTube Studio-ready multi-language audio track (.mp3):
        - Matches master video duration exactly.
        - Dynamic sidechain ducked background score with normalize=0.
        - Standardized loudness normalization to -14 LUFS (TP=-1.5 dB, LRA=11).
        """
        ffmpeg_bin = get_ffmpeg_binary()
        dur = max(1.0, round(target_duration, 2))

        if not bgm_path or not os.path.exists(bgm_path):
            cmd = [
                ffmpeg_bin, "-y",
                "-i", voice_path,
                "-af", f"apad=whole_dur={dur},atrim=0:{dur},loudnorm=I=-14:TP=-1.5:LRA=11",
                "-c:a", "libmp3lame", "-b:a", "192k",
                output_path
            ]
        else:
            filter_str = (
                f"[0:a]volume=1.0,apad=whole_dur={dur},asplit=2[vox_main][vox_sc];"
                f"[1:a]volume={bgm_volume}[bg_in];"
                f"[bg_in][vox_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=300[bg_ducked];"
                f"[vox_main][bg_ducked]amix=inputs=2:duration=first:dropout_transition=2:normalize=0,atrim=0:{dur},"
                f"loudnorm=I=-14:TP=-1.5:LRA=11[a]"
            )
            cmd = [
                ffmpeg_bin, "-y",
                "-i", voice_path,
                "-stream_loop", "-1", "-i", bgm_path,
                "-filter_complex", filter_str,
                "-map", "[a]",
                "-c:a", "libmp3lame", "-b:a", "192k",
                output_path
            ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0

    @staticmethod
    def get_sfx_path(sfx_name: str) -> Optional[str]:
        """Returns path to requested sound effect file."""
        clean_name = Path(sfx_name).stem.lower()
        cand_wav = SFX_DIR / f"{clean_name}.wav"
        cand_mp3 = SFX_DIR / f"{clean_name}.mp3"
        if cand_wav.exists():
            return str(cand_wav.resolve())
        if cand_mp3.exists():
            return str(cand_mp3.resolve())
        return None

    @staticmethod
    def build_sfx_cue_points(
        total_duration: float,
        scene_starts: Optional[List[float]] = None,
        genre: str = "movie_recap",
        explicit_sfx_cues: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Calculates strategic sound effect trigger points across the video timeline:
        - Incorporates explicit AI-directed SFX cues [SFX: ...] at exact narrative moments.
        - Opening Hook: sub_boom
        - Scene transitions: whoosh
        - Midpoint / turning point: genre specific
        - Climax: cinematic sub_boom
        """
        cues: List[Dict[str, Any]] = []
        dur = max(5.0, total_duration)

        # 1. Explicit AI Director / Sound Designer cues
        if explicit_sfx_cues:
            for ec in explicit_sfx_cues:
                t = float(ec.get("time", 0.0))
                if 0.0 <= t <= dur:
                    cues.append({
                        "time": round(t, 2),
                        "sfx": ec.get("sfx", "whoosh"),
                        "volume": float(ec.get("volume", 0.45))
                    })

        # 2. Opening Hook Impact (0.2s) if not already present
        if not any(c["time"] <= 1.5 and c["sfx"] == "sub_boom" for c in cues):
            cues.append({"time": 0.2, "sfx": "sub_boom", "volume": 0.50})

        # 3. Scene Transitions (whooshes at scene cuts)
        if not explicit_sfx_cues or len(explicit_sfx_cues) < 2:
            if scene_starts:
                for s in scene_starts:
                    if 2.0 <= s <= dur - 3.0:
                        cues.append({"time": round(s, 2), "sfx": "whoosh", "volume": 0.40})
            else:
                step = 15.0
                t = step
                while t < dur - 5.0:
                    cues.append({"time": round(t, 2), "sfx": "whoosh", "volume": 0.40})
                    t += step

            # Genre Specific Accent
            if genre == "documentary":
                cues.append({"time": round(dur * 0.40, 2), "sfx": "heartbeat", "volume": 0.45})
                cues.append({"time": round(dur * 0.42, 2), "sfx": "heartbeat", "volume": 0.45})
            elif genre == "video_essay":
                cues.append({"time": round(dur * 0.50, 2), "sfx": "cash_chime", "volume": 0.40})
            elif genre == "biography":
                cues.append({"time": round(dur * 0.35, 2), "sfx": "clock_tick", "volume": 0.35})

            # Climax Impact
            if dur >= 15.0:
                cues.append({"time": round(dur * 0.82, 2), "sfx": "sub_boom", "volume": 0.55})

        cues.sort(key=lambda x: x["time"])
        return cues

    @staticmethod
    def mix_soundtrack(
        voice_path: str,
        bgm_path: Optional[str],
        output_path: str,
        voice_duration: float,
        audio_mode: str = "hybrid",
        scene_starts: Optional[List[float]] = None,
        genre: str = "movie_recap",
        bgm_volume: float = 0.14,
        explicit_sfx_cues: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """
        Universal Master Soundtrack Mixer supporting 3 modes:
        1. 'hybrid': Voiceover + Ducked BGM + Strategic SFX cues (All amix calls use normalize=0).
        2. 'sfx_only': Voiceover + Strategic SFX cues (No Music, 0% copyright risk).
        3. 'music_only': Classic Voiceover + Dynamic Ducked BGM.
        """
        dur = max(1.0, round(voice_duration, 2))

        if audio_mode == "music_only":
            if bgm_path and os.path.exists(bgm_path):
                return AudioMixer.mix_voiceover_and_bgm(voice_path, bgm_path, output_path, dur, bgm_volume)
            else:
                synth_p = output_path + ".synth.mp3"
                if AudioMixer.generate_procedural_synth(synth_p, dur):
                    res = AudioMixer.mix_voiceover_and_bgm(voice_path, synth_p, output_path, dur, bgm_volume)
                    try: os.remove(synth_p)
                    except Exception: pass
                    return res
                return False

        # Build SFX cues for hybrid and sfx_only
        cues = AudioMixer.build_sfx_cue_points(dur, scene_starts, genre, explicit_sfx_cues=explicit_sfx_cues)
        valid_cues = []
        for c in cues:
            s_path = AudioMixer.get_sfx_path(c["sfx"])
            if s_path and os.path.exists(s_path):
                valid_cues.append((s_path, c["time"], c["volume"]))

        if not valid_cues:
            if bgm_path and os.path.exists(bgm_path) and audio_mode != "sfx_only":
                return AudioMixer.mix_voiceover_and_bgm(voice_path, bgm_path, output_path, dur, bgm_volume)
            else:
                return AudioMixer.create_isolated_dub_track(voice_path, None, output_path, dur)

        ffmpeg_bin = get_ffmpeg_binary()
        inputs = ["-i", voice_path]
        filter_parts = []
        mix_inputs = []

        has_bgm = (audio_mode == "hybrid" and bgm_path and os.path.exists(bgm_path))

        if has_bgm:
            # Voiceover split: [vox_main] for output mix, [vox_sc] as sidechain compressor trigger
            inputs.extend(["-stream_loop", "-1", "-i", bgm_path])
            filter_parts.append(
                f"[0:a]volume=1.0,apad=whole_dur={dur},asplit=2[vox_main][vox_sc];"
                f"[1:a]volume={bgm_volume}[bg_in];"
                f"[bg_in][vox_sc]sidechaincompress=threshold=0.08:ratio=4:attack=50:release=300[bg_ducked]"
            )
            mix_inputs.append("[vox_main]")
            mix_inputs.append("[bg_ducked]")
            curr_idx = 2
        else:
            filter_parts.append(f"[0:a]volume=1.0,apad=whole_dur={dur}[vox_main]")
            mix_inputs.append("[vox_main]")
            curr_idx = 1

        selected_cues = valid_cues[:12]
        for s_path, t_sec, vol in selected_cues:
            delay_ms = int(t_sec * 1000)
            inputs.extend(["-i", s_path])
            filter_parts.append(f"[{curr_idx}:a]volume={vol},adelay={delay_ms}|{delay_ms}[sfx{curr_idx}]")
            mix_inputs.append(f"[sfx{curr_idx}]")
            curr_idx += 1

        # Enforce normalize=0 to preserve voiceover level, then normalize to -14 LUFS
        amix_chain = (
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=2:normalize=0,"
            f"atrim=0:{dur},loudnorm=I=-14:LRA=11:TP=-1.5[a]"
        )
        filter_parts.append(amix_chain)
        full_filter = ";".join(filter_parts)

        cmd = [
            ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", "[a]",
            "-c:a", "libmp3lame", "-b:a", "192k",
            output_path
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            return True

        if bgm_path and os.path.exists(bgm_path) and audio_mode != "sfx_only":
            return AudioMixer.mix_voiceover_and_bgm(voice_path, bgm_path, output_path, dur, bgm_volume)
        else:
            return AudioMixer.create_isolated_dub_track(voice_path, None, output_path, dur)
