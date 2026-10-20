import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from db import Base, engine
import r_auth, r_catalog, r_sales, r_cash, r_reports

Base.metadata.create_all(engine)
app = FastAPI(title="Stock Up")

for m in (r_auth, r_catalog, r_sales, r_cash, r_reports):
    app.include_router(m.router)


@app.middleware("http")
async def no_cache(request, call_next):
    resp = await call_next(request)
    if not request.url.path.startswith("/api"):
        resp.headers["Cache-Control"] = "no-cache"  # evita ver archivos viejos del navegador
    return resp


FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=FRONT, html=True), name="front")