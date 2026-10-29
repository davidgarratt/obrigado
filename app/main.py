import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.database import init_db
from app.services.scheduler import start_scheduler, stop_scheduler
from app.middleware.auth import AuthMiddleware
from app.routers import notes, graph, obligations, briefings, calendar, prompts, settings_router, elicitations, people, analytics, auth, notifications

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("obrigado")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing Obrigado database...")
    init_db()
    logger.info("Starting background scheduler...")
    start_scheduler()
    logger.info(f"Obrigado initialized. Listening on {settings.host}:{settings.port}")
    yield
    # Shutdown
    logger.info("Stopping scheduler...")
    stop_scheduler()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Cognitive Load & Personal Obligation Graph Assistant with Gemini AI and Decision Models",
    lifespan=lifespan
)

# Authentication & Security Middleware
app.add_middleware(AuthMiddleware)

# CORS setup for Tailscale and local network access
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://.*$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth.router)
app.include_router(notes.router)
app.include_router(graph.router)
app.include_router(obligations.router)
app.include_router(briefings.router)
app.include_router(calendar.router)
app.include_router(prompts.router)
app.include_router(settings_router.router)
app.include_router(elicitations.router)
app.include_router(people.router)
app.include_router(analytics.router)
app.include_router(notifications.router)

# Mount Static Files
static_dir = Path(__file__).resolve().parent / "static"
static_dir.mkdir(exist_ok=True, parents=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/sw.js")
async def service_worker():
    sw_file = static_dir / "sw.js"
    if sw_file.exists():
        return FileResponse(
            sw_file,
            media_type="application/javascript",
            headers={"Service-Worker-Allowed": "/"}
        )
    return Response(status_code=404)

@app.get("/manifest.json")
async def web_manifest():
    mf_file = static_dir / "manifest.json"
    if mf_file.exists():
        return FileResponse(
            mf_file,
            media_type="application/manifest+json"
        )
    return Response(status_code=404)

@app.get("/login")
async def login_page():
    login_file = static_dir / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    return {"message": "Login page not found."}

@app.get("/")
async def root():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "Obrigado backend is running. Web UI not found in static folder."}
