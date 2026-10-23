import os
from functools import lru_cache
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from db import Base, engine
import r_auth, r_catalog, r_sales, r_cash, r_reports

if os.getenv("APP_ENV", "").lower() in ("prod", "production") and len(os.getenv("STOCKUP_SECRET", "")) < 32:
    raise RuntimeError("En producción configura STOCKUP_SECRET con al menos 32 caracteres aleatorios.")

Base.metadata.create_all(engine)
app = FastAPI(title="Stock Up")
origins = [x.strip() for x in os.getenv("STOCKUP_FRONTEND_ORIGINS", "https://nikolee-code.github.io").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"])

for m in (r_auth, r_catalog, r_sales, r_cash, r_reports):
    app.include_router(m.router)


@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    return {"status": "ok"}


@lru_cache(maxsize=None)
def png_icon(size):
    """Devuelve el logo oficial de la app para los accesos PWA."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "brand.png")
    with open(path, "rb") as image:
        return image.read()

@app.get("/icon-{size}.png")
def icon_png(size: int):
    if size not in (180, 192, 512):
        raise HTTPException(404, "Ícono no encontrado")
    return Response(png_icon(size), media_type="image/png")


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"  # evita ver archivos viejos del navegador
    return resp


FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONT, html=True), name="front")
