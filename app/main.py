import uvicorn
from fastapi import FastAPI
from .api import router
from .services.fix_gateway import fix_gateway
# Fase 2.2 — WS router
from .ws import ws_router

app = FastAPI(title="OMS Backend (MVP)")

# Start FIX worker properly when FastAPI starts — THIS IS CRITICAL
@app.on_event("startup")
async def startup_event():
    fix_gateway.start()

# Add API routes
app.include_router(router)
app.include_router(ws_router)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
