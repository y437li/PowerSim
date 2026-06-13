"""energy_go.serving.app — FastAPI application factory.

Programmatic launch (honours ENERGY_GO_BACKEND_PORT, default 8000):
    python -m energy_go.serving.app

Manual uvicorn launch:
    ENERGY_GO_BACKEND_PORT=9000 uvicorn energy_go.serving.app:app --host 0.0.0.0 --port 9000

Contract: contracts/serving/rest_api.md + inference_stream.md + training_proxy.md
          contracts/serving/backend_port.md (§1 __main__ block)
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from energy_go.serving import rest_api, inference_stream, training_proxy, geo_site_api

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Pre-warm JAX JIT at startup so the first env_step frame isn't delayed.

    JAX compiles (traces) jax_env.reset / jax_env.step on the first call — a
    one-time cost that can be 4-8 s on a slow runner.  Running a throwaway
    reset+step during lifespan startup amortises this before any websocket
    connection arrives, keeping test_speed_zero_delivers_frame_immediately
    within its 2 s budget and giving users a smooth first frame.

    Startup runs synchronously so the server does not accept connections until
    warmup completes.  This is acceptable: the warm-up is a one-time cost per
    process, and TestClient triggers it in __enter__ before tests run.

    Falls back silently if JAX is not importable (e.g. CPU-only CI shard that
    tests only the REST endpoints).
    """
    try:
        import jax
        import jax.numpy as jnp
        from energy_go.env import jax_env as _jax_env_mod       # type: ignore
        from energy_go.generators.synthetic import generate_year  # type: ignore

        _k = jax.random.PRNGKey(0)
        _d = generate_year(_k)
        _k, _wk = jax.random.split(_k)
        _ws, _ = _jax_env_mod.reset(_wk, _jax_env_mod.EnvParams(), _d)
        # 6-dim action: a_bat + 5 flow fractions (jax_env.py L264-269).
        # Shape+dtype must match production policy_forward output exactly so JAX
        # caches the right compiled entry. jnp.zeros(1) would IndexError at trace
        # time AND cache-miss at runtime even if it succeeded.
        _jax_env_mod.step(_ws, jnp.zeros(6, dtype=jnp.float32), _jax_env_mod.EnvParams(), _d)
        log.info("JAX JIT warmup complete (reset + step compiled)")
    except Exception as exc:  # ImportError, RuntimeError (no AVX), etc.
        log.debug("JAX JIT warmup skipped at startup: %s", exc)
    yield  # server is now ready; shutdown cleanup would go after yield


app = FastAPI(title="Energy GO Serving API", version="1.0.0", lifespan=_lifespan)

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
app.include_router(geo_site_api.router)


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


@app.exception_handler(RequestValidationError)
async def request_validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Convert Pydantic request-body validation errors to HTTP 400 for geo routes.

    Contract (geo_site_api.md §2, site_assemble.md §2):
    - Malformed JSON body (type "json_invalid") → HTTP 422 (FastAPI default semantics;
      the body was unparseable before any field-level validation could run).
    - Missing required field, unknown catalog ID, out-of-range parameter → HTTP 400
      for /api/site/, /api/tariff/, /api/devices/ geo routes.

    All other routes (training_proxy, rest_api, inference_stream) use FastAPI's
    default 422 so their approved contracts are not affected.
    """
    errors = exc.errors()

    # JSON decode error: the body was not valid JSON — return 422 for all routes
    # (this is distinct from Pydantic model validation, which returns 400 for geo routes)
    if errors and errors[0].get("type") == "json_invalid":
        return JSONResponse(
            status_code=422,
            content={
                "detail": errors[0].get("msg", "JSON decode error"),
                "code": "JSON_DECODE_ERROR",
            },
        )

    _GEO_PREFIXES = ("/api/site/", "/api/tariff/", "/api/devices/")
    if any(request.url.path.startswith(p) for p in _GEO_PREFIXES):
        first_msg = errors[0]["msg"] if errors else "invalid request"
        return JSONResponse(
            status_code=400,
            content={
                "detail": first_msg,
                "code": "REQUEST_VALIDATION_ERROR",
            },
        )
    # Non-geo routes: preserve original FastAPI 422 behaviour
    return JSONResponse(status_code=422, content={"detail": errors})


if __name__ == "__main__":
    import os
    import uvicorn

    # `os.environ.get("ENERGY_GO_BACKEND_PORT") or "8000"`:
    #   - absent key  → None  (falsy) → "8000"
    #   - empty string → ""  (falsy) → "8000"
    #   - "9000"      → "9000" (truthy) → 9000
    #   - "   "       → "   " (truthy) → int("   ") → ValueError (intentional)
    port = int(os.environ.get("ENERGY_GO_BACKEND_PORT") or "8000")
    uvicorn.run("energy_go.serving.app:app", host="0.0.0.0", port=port, reload=False)
