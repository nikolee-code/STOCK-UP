import os, zlib, struct
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
    """Dibuja el ícono de Stock Up (fondo verde oscuro y tres barras) como PNG."""
    s = size / 64.0
    bg = (15, 61, 46)
    bars = [(14, 36, 23, 50, (255, 255, 255)), (27, 26, 36, 50, (227, 239, 233)),
            (40, 14, 49, 50, (255, 255, 255))]
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        yy = y / s
        for x in range(size):
            xx = x / s
            color = bg
            for x0, y0, x1, y1, c in bars:
                if x0 <= xx <= x1 and y0 <= yy <= y1:
                    color = c
                    break
            rows.extend(color)

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + chunk(b"IEND", b""))


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