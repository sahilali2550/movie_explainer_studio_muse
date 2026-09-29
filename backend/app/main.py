from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from app.core.config import (
    BASE_DIR, OUTPUTS_DIR, THUMBNAILS_DIR, TEMP_DIR,
    API_TOKEN, purge_stale_temp_files,
)
import secrets as _secrets
from app.api.v1.explainer import router as explainer_router
from app.api.v1.youtube_api import router as youtube_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Replaces deprecated @app.on_event("startup"): purge stale temp files.
    removed = purge_stale_temp_files(max_age_hours=24.0)
    if removed:
        print(f"🧹 Startup cleanup: removed {removed} stale temp file(s).")
    yield


app = FastAPI(
    title="AutoExplainer AI SaaS API",
    description="Full-Auto AI Movie & Drama Explainer Video Engine with 15+ Languages, Hybrid Thumbnails, and Viral Social Suites.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration for Frontend Dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static file serving for generated media
app.mount("/outputs/thumbnails", StaticFiles(directory=str(THUMBNAILS_DIR)), name="thumbnails")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")

# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# SECURITY: token-guard every /api/* route AND /outputs/* media paths. The
# dashboard served by this same server receives the token automatically
# (injected into index.html); external clients must send it as the
# X-API-Token header or ?token= query parameter. The dashboard appends
# ?token= to /outputs/* media URLs via apiUrlWithToken() (frontend).
# The OAuth callback is exempt: it is a browser redirect from Google and
# cannot carry a custom header (it is protected by the OAuth `state` token).
# ---------------------------------------------------------------------------
_API_PUBLIC_PATHS = ("/api/v1/youtube/oauth-callback",)
_API_PROTECTED_PREFIXES = ("/api/", "/outputs/")

@app.middleware("http")
async def api_token_guard(request, call_next):
    path = request.url.path
    if path.startswith(_API_PROTECTED_PREFIXES) and not path.startswith(_API_PUBLIC_PATHS):
        provided = request.headers.get("x-api-token") or request.query_params.get("token")
        if not provided or not _secrets.compare_digest(provided, API_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized: missing or invalid API token."},
            )
    return await call_next(request)


# Frontend Directory Mounting
FRONTEND_DIR = BASE_DIR.parent / "frontend"
if (FRONTEND_DIR / "css").exists():
    app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
if (FRONTEND_DIR / "js").exists():
    app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")

# Include API Routers
app.include_router(explainer_router, prefix="/api/v1")
app.include_router(youtube_router, prefix="/api/v1")

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

@app.get("/")
def serve_frontend(request: Request):
    index_file = FRONTEND_DIR / "index.html"
    if index_file.exists():
        from fastapi.responses import HTMLResponse
        page = index_file.read_text(encoding="utf-8")
        # Inject the API token ONLY for loopback clients. The token is a
        # bearer secret: serving it to any remote (LAN) client that loads "/"
        # would hand them full access to every protected /api/* and /outputs/*
        # route. Local desktop use (pywebview / localhost browser) is
        # unaffected. API_TOKEN is urlsafe (letters, digits, '-' and '_').
        client_host = request.client.host if request.client else ""
        if client_host in _LOOPBACK_HOSTS:
            injected = (
                f'<script>window.__API_TOKEN__="{API_TOKEN}";</script></head>'
            )
            if "</head>" in page:
                page = page.replace("</head>", injected, 1)
            else:
                page = injected.replace("</head>", "") + page
        return HTMLResponse(content=page)
    return {
        "status": "online",
        "service": "AutoExplainer AI SaaS Engine",
        "version": "1.0.0",
        "docs_url": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
