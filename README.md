# 🎬 AutoExplainer AI — Viral Movie & Drama Explainer SaaS

**AutoExplainer AI** is a commercial-grade, full-auto AI Video Explainer and Movie Recap generation platform. It automatically transforms long-form movies, dramas, and video URLs into high-retention viral storytelling videos for YouTube, TikTok, Facebook, and Instagram Reels.

---

## 🌟 Key Features

### 1. Global Multilingual Narrative Engine (16+ Languages)
- **Tier 1 (Viral Recaps)**: Spanish (`es`), Indonesian (`id`), Portuguese (`pt`), Urdu (`ur`), Hindi (`hi`), English (`en`).
- **Tier 2 (High CPM)**: Arabic (`ar`), German (`de`), French (`fr`), Russian (`ru`), Italian (`it`), Turkish (`tr`).
- **Tier 3 (Asian Markets)**: Vietnamese (`vi`), Thai (`th`), Japanese (`ja`), Korean (`ko`).
- **Native Narrator Personas**: Hollywood Trailer, Viral Fast-Paced, Sarcastic Roaster, and Crime Documentary.
- **Spoiler Shield**: Choose between *Full Recap with Climax* or *Cliffhanger Teaser*.

### 2. Hybrid 3-Option Viral Thumbnail Generator (Option 3)
- Automatically extracts 3 high-clarity movie milestone frames (Action, Emotional Climax, Suspense Mystery).
- Applies cinematic contrast grading and edge vignette.
- Renders high-impact clickbait typography hooks with RTL Arabic/Urdu support.
- Gives creators 3 A/B test-ready thumbnails with 1-click download.

### 3. Studio Audio & Curated Mood Music
- 400+ Microsoft Neural TTS voices via Edge-TTS.
- Cinema Trailer pitch modification (-12Hz bass boost) and speech velocity controls.
- Royalty-free human mood music library (`dark`, `tense`, `chill`, `upbeat`).
- Automated intelligent audio ducking (music volume drops to 16% under voiceover).

### 4. Advanced Anti-Copyright Armor
- 100% full-width movie display with cinematic blurred top/bottom reflection backdrop (9:16).
- Micro-speed variance (`PTS/1.03`) and frame drift.
- Subtle contrast/saturation color grading for Content ID bypass.
- Dynamic burned subtitles and custom channel watermark.

### 5. Click-to-Copy YouTube & TikTok SEO Suite
- 3 High-CTR Clickbait Titles.
- Full SEO Description with Fair Use legal disclaimer.
- 15 Ranked Search Tags and Viral Hashtags.
- High-Engagement Pinned Comment.

---

## 🚀 Quick Start

### 1. Launch with One Click (Windows)
Simply double-click:
```bash
START_SAAS.bat
```

### 2. Access the Studio Dashboard
Open your browser and navigate to:
- **Studio Dashboard**: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- **Interactive API Docs (Swagger UI)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## 📁 Directory Structure

```
autoexplainer-saas/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # REST API endpoints (explainer routes)
│   │   ├── core/            # Config, paths, language mappings
│   │   ├── schemas/         # Pydantic models for type safety
│   │   ├── services/        # ScriptEngine, VoiceEngine, VideoEngine, ThumbnailEngine, AudioMixer
│   │   └── main.py          # FastAPI application
│   ├── assets/
│   │   ├── fonts/           # Multilingual typography fonts
│   │   └── music/           # Curated mood music tracks (dark, tense, chill, upbeat)
│   ├── storage/
│   │   ├── uploads/         # Ingested raw video files
│   │   ├── outputs/         # Exported MP4 videos & thumbnails
│   │   └── temp/            # Ephemeral audio slices and candidate frames
│   ├── requirements.txt
│   └── run_server.py
├── frontend/
│   ├── css/styles.css       # Modern dark-glassmorphism SaaS UI
│   ├── js/app.js            # Studio interactive application logic
│   └── index.html           # Creator studio dashboard
├── venv/                    # Dedicated Python virtual environment
├── START_SAAS.bat           # One-click Windows runner
└── README.md
```

---

## 🛡️ License & Fair Use
Designed for automated fair-use critical commentary, film analysis, and recap storytelling under Section 107 of the Copyright Act.
