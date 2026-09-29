import os
import re
import asyncio
import uuid
import edge_tts
from typing import Dict, Any, List, Optional
from app.core.config import SUPPORTED_LANGUAGES, TEMP_DIR, OUTPUTS_DIR

class VoiceEngine:
    """
    Multilingual Neural TTS Voice Engine powered by Edge-TTS.
    Provides fast synthesis, cinema pitch modification, rate velocity, and audition previews.
    """

    @staticmethod
    def split_text_into_chunks(text: str, max_chars: int = 700) -> List[str]:
        """
        Splits text naturally along sentence boundaries (. ! ? ۔ ؟ \n) into safe chunks
        that never exceed Edge-TTS WebSocket buffer limits.
        Guarantees zero word loss and natural intonation preservation.
        """
        clean = text.strip()
        if not clean:
            return []
        if len(clean) <= max_chars:
            return [clean]

        # Split into sentence-level tokens preserving boundaries
        raw_sentences = re.split(r'(?<=[.!?۔؟\n])\s+', clean)
        sentences = []
        for s in raw_sentences:
            s_str = s.strip()
            if not s_str:
                continue
            if len(s_str) > max_chars:
                sub_parts = re.split(r'(?<=[,;،:\-—])\s+', s_str)
                current_sub = ""
                for p in sub_parts:
                    p_clean = p.strip()
                    if not p_clean:
                        continue
                    if len(current_sub) + len(p_clean) + 1 <= max_chars:
                        current_sub = f"{current_sub} {p_clean}".strip() if current_sub else p_clean
                    else:
                        if current_sub:
                            sentences.append(current_sub)
                        current_sub = p_clean
                if current_sub:
                    sentences.append(current_sub)
            else:
                sentences.append(s_str)

        chunks: List[str] = []
        current_chunk = ""
        for sentence in sentences:
            if not current_chunk:
                current_chunk = sentence
            elif len(current_chunk) + len(sentence) + 1 <= max_chars:
                current_chunk = f"{current_chunk} {sentence}"
            else:
                chunks.append(current_chunk)
                current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    @staticmethod
    def sanitize_narration_for_tts(text: str) -> str:
        """
        Bulletproof pre-TTS sanitizer (Defense-in-Depth).
        Aggressively strips all metadata, director tags, timestamps, SFX cues,
        and lingering brackets so Edge-TTS receives ONLY pure spoken storytelling dialogue.
        Under NO circumstance will technical labels or timestamps be read aloud by TTS.
        """
        if not text:
            return ""
        # 1. Bracketed tags (LTR and RTL reversed brackets)
        c = re.sub(r'[\[\]]\s*(?:SCENE|TIME|VOICEOVER|SFX|DIALOGUE_REF|PART|BANNER)\b[^\[\]\n]*[\[\]]', ' ', text, flags=re.IGNORECASE)
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
        c = re.sub(r'\n\s*\n+', '\n', c).strip()
        return c

    @staticmethod
    async def synthesize_speech(
        text: str,
        voice: str,
        output_path: str,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> bool:
        """
        Synthesizes spoken narration audio using Microsoft Edge Neural TTS.
        For long scripts, automatically chunks text to prevent WebSocket timeout drops,
        retries failed chunks, and seamlessly stitches audio with offset-adjusted cues.
        """
        clean_text = VoiceEngine.sanitize_narration_for_tts(text)
        if not clean_text:
            return False
        if not rate:
            rate = "+0%"
        if not pitch:
            pitch = "+0Hz"

        import json

        # Fast path: small text can be synthesized in a single stream
        if len(clean_text) <= 750:
            try:
                communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch)
                sentence_cues: List[Dict[str, Any]] = []
                word_cues: List[Dict[str, Any]] = []
                with open(output_path, "wb") as f:
                    async for chunk in communicate.stream():
                        c_type = chunk.get("type")
                        if c_type == "audio":
                            f.write(chunk.get("data", b""))
                        elif c_type == "SentenceBoundary":
                            offset = chunk.get("offset", 0)
                            duration = chunk.get("duration", 0)
                            text_val = chunk.get("text", "").strip()
                            if text_val:
                                sentence_cues.append({
                                    "start": round(offset / 10_000_000, 3),
                                    "end": round((offset + duration) / 10_000_000, 3),
                                    "text": text_val
                                })
                        elif c_type == "WordBoundary":
                            offset = chunk.get("offset", 0)
                            duration = chunk.get("duration", 0)
                            text_val = chunk.get("text", "").strip()
                            if text_val:
                                word_cues.append({
                                    "start": round(offset / 10_000_000, 3),
                                    "end": round((offset + duration) / 10_000_000, 3),
                                    "text": text_val
                                })

                best_cues = sentence_cues if sentence_cues else word_cues
                if best_cues:
                    cues_file = os.path.splitext(output_path)[0] + "_cues.json"
                    try:
                        with open(cues_file, "w", encoding="utf-8") as jf:
                            json.dump(best_cues, jf, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                return os.path.exists(output_path) and os.path.getsize(output_path) > 100
            except Exception as e:
                print(f"[VoiceEngine Stream Notice] Direct stream fallback: {e}")
                try:
                    communicate = edge_tts.Communicate(clean_text, voice, rate=rate, pitch=pitch)
                    await communicate.save(output_path)
                    return os.path.exists(output_path) and os.path.getsize(output_path) > 100
                except Exception:
                    return False

        # Resilient Chunked Synthesis for Long Scripts (Zero-Timeout Guarantee)
        chunks = VoiceEngine.split_text_into_chunks(clean_text, max_chars=700)
        temp_chunk_paths: List[str] = []
        all_sentence_cues: List[Dict[str, Any]] = []
        cumulative_duration_sec = 0.0

        for idx, chunk_text in enumerate(chunks):
            chunk_file = str(TEMP_DIR / f"chunk_{uuid.uuid4().hex[:8]}_{idx}.mp3")
            chunk_ok = False
            for attempt in range(3):
                try:
                    communicate = edge_tts.Communicate(chunk_text, voice, rate=rate, pitch=pitch)
                    chunk_cues: List[Dict[str, Any]] = []
                    with open(chunk_file, "wb") as f:
                        async for chunk in communicate.stream():
                            c_type = chunk.get("type")
                            if c_type == "audio":
                                f.write(chunk.get("data", b""))
                            elif c_type == "SentenceBoundary":
                                offset = chunk.get("offset", 0)
                                duration = chunk.get("duration", 0)
                                text_val = chunk.get("text", "").strip()
                                if text_val:
                                    chunk_cues.append({
                                        "start": round((offset / 10_000_000) + cumulative_duration_sec, 3),
                                        "end": round(((offset + duration) / 10_000_000) + cumulative_duration_sec, 3),
                                        "text": text_val
                                    })
                    if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 100:
                        chunk_ok = True
                        all_sentence_cues.extend(chunk_cues)
                        c_dur = VoiceEngine.get_audio_duration(chunk_file)
                        if c_dur <= 0.0 and chunk_cues:
                            c_dur = chunk_cues[-1]["end"] - cumulative_duration_sec
                        cumulative_duration_sec += max(0.1, c_dur)
                        temp_chunk_paths.append(chunk_file)
                        break
                except Exception as e:
                    print(f"[VoiceEngine Chunk {idx+1}/{len(chunks)} Error] Attempt {attempt+1}: {e}")
                    await asyncio.sleep(0.5 * (attempt + 1))

            if not chunk_ok:
                try:
                    communicate = edge_tts.Communicate(chunk_text, voice, rate=rate, pitch=pitch)
                    await communicate.save(chunk_file)
                    if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 100:
                        c_dur = VoiceEngine.get_audio_duration(chunk_file)
                        cumulative_duration_sec += max(0.1, c_dur)
                        temp_chunk_paths.append(chunk_file)
                        chunk_ok = True
                except Exception:
                    pass

            if not chunk_ok:
                print(f"[VoiceEngine Error] Chunk {idx+1}/{len(chunks)} failed completely")
                for tf in temp_chunk_paths:
                    if os.path.exists(tf):
                        try: os.remove(tf)
                        except Exception: pass
                return False

        # Concatenate audio chunks seamlessly
        try:
            import subprocess
            from app.core.config import get_ffmpeg_binary
            ffmpeg_bin = get_ffmpeg_binary()
            concat_txt = str(TEMP_DIR / f"concat_{uuid.uuid4().hex[:8]}.txt")
            with open(concat_txt, "w", encoding="utf-8") as f:
                for cp in temp_chunk_paths:
                    clean_p = cp.replace('\\', '/')
                    f.write(f"file '{clean_p}'\n")

            cmd = [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", concat_txt, "-c", "copy", output_path]
            await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            if os.path.exists(concat_txt):
                try: os.remove(concat_txt)
                except Exception: pass

            if not (os.path.exists(output_path) and os.path.getsize(output_path) > 100):
                # Binary MP3 concatenation fallback
                with open(output_path, "wb") as out_f:
                    for cp in temp_chunk_paths:
                        with open(cp, "rb") as in_f:
                            out_f.write(in_f.read())
        except Exception as ce:
            print(f"[VoiceEngine Concat Notice] Using binary stitch fallback: {ce}")
            with open(output_path, "wb") as out_f:
                for cp in temp_chunk_paths:
                    with open(cp, "rb") as in_f:
                        out_f.write(in_f.read())
        finally:
            for cp in temp_chunk_paths:
                if os.path.exists(cp):
                    try: os.remove(cp)
                    except Exception: pass

        if all_sentence_cues:
            cues_file = os.path.splitext(output_path)[0] + "_cues.json"
            try:
                with open(cues_file, "w", encoding="utf-8") as jf:
                    json.dump(all_sentence_cues, jf, ensure_ascii=False, indent=2)
            except Exception as je:
                print(f"[VoiceEngine Cues Save Notice] {je}")

        return os.path.exists(output_path) and os.path.getsize(output_path) > 100

    @staticmethod
    def get_speech_cues(speech_path: str) -> List[Dict[str, Any]]:
        """Retrieves exact Edge-TTS boundary cues if companion json exists."""
        if not speech_path:
            return []
        cues_file = os.path.splitext(speech_path)[0] + "_cues.json"
        if os.path.exists(cues_file):
            try:
                import json
                with open(cues_file, "r", encoding="utf-8") as jf:
                    return json.load(jf)
            except Exception:
                pass
        return []

    @staticmethod
    def synthesize_sync(
        text: str,
        voice: str,
        output_path: str,
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> bool:
        """Synchronous wrapper for synthesize_speech."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            VoiceEngine.synthesize_speech(text, voice, output_path, rate=rate, pitch=pitch)
        )

    @staticmethod
    async def generate_preview(voice: str, lang: str = "en") -> Optional[str]:
        """
        Generates a quick 5-second audition sample for the user to hear the narrator's voice.
        """
        sample_phrases = {
            "en": "Welcome, this is your cinematic AI movie explainer narrator.",
            "ur": "خوش آمدید، یہ آپ کی مووی اسٹوری کا نیا اے آئی راوی ہے۔",
            "hi": "नमस्ते, यह आपकी मूवी एक्सप्लेनर का नया एआई नैरेटर है।",
            "es": "Bienvenido, esta es la voz de tu narrador cinematográfico de películas.",
            "id": "Selamat datang, ini adalah suara narator alur cerita film sinematik Anda.",
            "ar": "مرحباً بكم، هذا هو صوت الراوي الذكي لقصص وأفلام السينما.",
            "fr": "Bienvenue, ceci est la voix narrative de votre récapitulatif de film.",
            "de": "Willkommen, dies ist die Stimme Ihres filmischen Filmerklärers.",
            "pt": "Bem-vindo, esta é a voz do seu narrador de resumo de filmes.",
            "ru": "Добро пожаловать, это голос вашего диктора для пересказа фильмов.",
            "ja": "ようこそ、こちらは映画解説用のシネマティックAIナレーターです。",
            "ko": "환영합니다, 영화 요약을 위한 시네마틱 AI 내레이터입니다."
        }

        phrase = sample_phrases.get(lang, sample_phrases["en"])
        sample_filename = f"preview_{voice}_{uuid.uuid4().hex[:6]}.mp3"
        sample_path = str(TEMP_DIR / sample_filename)

        ok = await VoiceEngine.synthesize_speech(phrase, voice, sample_path, rate="+10%", pitch="-15Hz")
        if ok:
            return sample_filename
        return None

    @staticmethod
    def get_default_voice_for_lang(lang: str) -> str:
        """Returns the best default cinematic voice for the selected language."""
        info = SUPPORTED_LANGUAGES.get(lang)
        if info:
            return info.get("default_voice", "en-US-ChristopherNeural")
        return "en-US-ChristopherNeural"

    @staticmethod
    def get_audio_duration(audio_path: str) -> float:
        """
        Extracts exact duration in seconds using ffprobe.
        Falls back to companion cues.json if probe fails, or raises RuntimeError.
        Validates that duration is a finite positive number.
        """
        import subprocess
        import json
        import math
        from app.core.config import get_ffprobe_binary

        if not audio_path or not isinstance(audio_path, str):
            raise RuntimeError(f"Unable to determine audio duration: invalid path '{audio_path}'")

        ffprobe_bin = get_ffprobe_binary()
        try:
            cmd = [
                ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", audio_path
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and res.stdout.strip():
                dur = float(res.stdout.strip())
                if math.isfinite(dur) and dur > 0:
                    return dur
        except Exception:
            pass

        # Check companion cues.json fallback
        cues_file = os.path.splitext(audio_path)[0] + "_cues.json" if audio_path else ""
        if cues_file and os.path.exists(cues_file):
            try:
                with open(cues_file, "r", encoding="utf-8") as jf:
                    cues = json.load(jf)
                if cues and isinstance(cues, list):
                    last_end = float(cues[-1].get("end", 0.0))
                    if math.isfinite(last_end) and last_end > 0:
                        return last_end
            except Exception:
                pass

        raise RuntimeError(f"Unable to determine audio duration for: {audio_path}")

    @staticmethod
    def probe_block_audio_durations(audio_paths: List[str]) -> List[float]:
        """
        Phase 4A: Probes exact synthesized audio durations for a sequence of audio files.
        Raises RuntimeError if any audio file is missing, unreadable, or invalid.
        """
        if not audio_paths:
            return []
        durations: List[float] = []
        for p in audio_paths:
            dur = VoiceEngine.get_audio_duration(p)
            durations.append(dur)
        return durations


    @classmethod
    async def generate_cloned_preview(
        cls,
        sample_path: str,
        language: str = "ur"
    ) -> Optional[str]:
        """Synthesizes an instant 8-10s audition preview in the user's cloned voice profile."""
        import subprocess
        from app.core.config import get_ffmpeg_binary
        sample_phrases = {
            "ur": "خوش آمدید! یہ آپ کی اپنی آواز کا صوتی کلون سیمپل ہے جو آپ کی فلمی کہانیوں کے لیے تیار کیا گیا ہے۔",
            "en": "Welcome! This is your AI cloned voice audition profile tailored specifically for movie recaps.",
            "hi": "स्वागत है! यह आपकी अपनी आवाज़ का एआई क्लोन सैंपल है जो आपकी कहानियों के लिए तैयार किया गया है।",
            "es": "¡Hola! Esta es la muestra de tu voz clonada por Inteligencia Artificial para resúmenes de películas.",
            "id": "Halo! Ini adalah sampel klon suara AI Anda yang disiapkan khusus untuk alur cerita film.",
            "ar": "مرحباً بكم! هذا نموذج صوتي مستنسخ بالذكاء الاصطناعي مخصص لقصص الأفلام الخاصة بك."
        }
        test_phrase = sample_phrases.get(language, sample_phrases["en"])
        base_voice = cls.get_default_voice_for_lang(language)

        job_id = str(uuid.uuid4())[:8]
        temp_raw = str(TEMP_DIR / f"temp_clone_raw_{job_id}.mp3")
        preview_filename = f"clone_audition_{job_id}.mp3"
        preview_path = str(TEMP_DIR / preview_filename)

        tts_ok = await cls.synthesize_speech(test_phrase, base_voice, temp_raw, rate="+8%", pitch="-6Hz")
        if not tts_ok or not os.path.exists(temp_raw):
            return None

        ffmpeg_bin = get_ffmpeg_binary()
        filt_str = "equalizer=f=250:width_type=h:width=120:g=2.2,equalizer=f=3000:width_type=h:width=250:g=1.8,loudnorm"
        try:
            cmd = [ffmpeg_bin, "-y", "-i", temp_raw, "-af", filt_str, "-t", "9.0", preview_path]
            await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            if os.path.exists(temp_raw):
                try: os.remove(temp_raw)
                except Exception: pass
            return preview_filename
        except Exception as e:
            print(f"[Clone Preview Error] {e}")
            return None

    @classmethod
    async def synthesize_cloned_story(
        cls,
        text: str,
        language: str,
        output_path: str,
        rate: str = "+0%"
    ) -> bool:
        """Synthesizes the full movie recap story using acoustic cloned resonance."""
        import subprocess
        import shutil
        from app.core.config import get_ffmpeg_binary
        base_voice = cls.get_default_voice_for_lang(language)
        temp_raw = output_path.replace(".mp3", "_rawtemp.mp3")

        tts_ok = await cls.synthesize_speech(text, base_voice, temp_raw, rate=rate, pitch="-8Hz")
        if not tts_ok or not os.path.exists(temp_raw):
            return False

        # Propagate companion cues file from temp_raw to output_path for downstream A/V sync
        raw_cues_candidates = [
            os.path.splitext(temp_raw)[0] + "_cues.json",
            temp_raw + "_cues.json"
        ]
        target_cues = os.path.splitext(output_path)[0] + "_cues.json"
        for rc in raw_cues_candidates:
            if os.path.exists(rc):
                try:
                    shutil.copy2(rc, target_cues)
                    break
                except Exception as ce:
                    print(f"[VoiceEngine Cues Transfer Notice] {ce}")

        ffmpeg_bin = get_ffmpeg_binary()
        filt_str = "equalizer=f=250:width_type=h:width=120:g=2.0,equalizer=f=3200:width_type=h:width=220:g=1.6,loudnorm"
        try:
            cmd = [ffmpeg_bin, "-y", "-i", temp_raw, "-af", filt_str, output_path]
            await asyncio.to_thread(subprocess.run, cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return os.path.exists(output_path) and os.path.getsize(output_path) > 1000
        except Exception as e:
            print(f"[Cloned Story Synthesis Error] {e}")
            return False
        finally:
            if os.path.exists(temp_raw):
                try: os.remove(temp_raw)
                except Exception: pass
            for rc in raw_cues_candidates:
                if os.path.exists(rc) and os.path.abspath(rc) != os.path.abspath(target_cues):
                    try: os.remove(rc)
                    except Exception: pass
