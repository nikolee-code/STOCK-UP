import os
from functools import lru_cache
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from db import Base, engine
import r_auth, r_catalog, r_sales, r_cash, r_reports

Base.metadata.create_all(engine)
app = FastAPI(title="Stock Up")

for m in (r_auth, r_catalog, r_sales, r_cash, r_reports):
    app.include_router(m.router)


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