"""energy_go.serving.app — FastAPI application factory.

The `app` instance is the ASGI entry point:
    uvicorn energy_go.serving.app:app --host 0.0.0.0 --port 8000

Implementation pending: contracts/serving/rest_api.md + inference_stream.md + training_proxy.md
gate approval (PR #29, backend-reviewer APPROVE required before implementation).
"""
from fastapi import FastAPI

app = FastAPI(title="Energy GO Serving API", version="1.0.0")

# Routers are registered here once implemented:
#   from energy_go.serving import rest_api, inference_stream, training_proxy
#   app.include_router(rest_api.router)
#   app.include_router(inference_stream.router)
#   app.include_router(training_proxy.router)
