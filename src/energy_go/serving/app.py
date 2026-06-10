"""energy_go.serving.app — FastAPI application factory.

The `app` instance is the ASGI entry point:
    uvicorn energy_go.serving.app:app --host 0.0.0.0 --port 8000

Contract: contracts/serving/rest_api.md + inference_stream.md + training_proxy.md
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from energy_go.serving import rest_api, inference_stream, training_proxy

app = FastAPI(title="Energy GO Serving API", version="1.0.0")

# CORS: allow all origins (dashboard served separately during dev; restricted at
# reverse-proxy level in production — out of scope here per contract).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rest_api.router)
app.include_router(inference_stream.router)
app.include_router(training_proxy.router)


# ---------------------------------------------------------------------------
# Override FastAPI's default 404 to emit the contract error schema
# ---------------------------------------------------------------------------

@app.exception_handler(404)
async def not_found_handler(request: Request, exc) -> JSONResponse:
    # FastAPI HTTPException detail may be a dict or string
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=404, content=detail)
    return JSONResponse(
        status_code=404,
        content={"error": str(detail) if detail else "not found", "detail": None},
    )


@app.exception_handler(422)
async def validation_error_handler(request: Request, exc) -> JSONResponse:
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=422, content=detail)
    return JSONResponse(
        status_code=422,
        content={"error": "validation error", "detail": str(detail) if detail else None},
    )
