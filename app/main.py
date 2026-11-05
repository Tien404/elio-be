from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.routes import ROUTERS
from app.core.config import Settings
from app.core.errors import install_error_handlers
from app.infrastructure.db.connection import PyodbcDatabase


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.database = PyodbcDatabase(settings)
        yield

    app = FastAPI(
        title="ELIO API",
        version="0.1.0",
        lifespan=lifespan,
    )
    install_error_handlers(app)
    app.include_router(health_router)
    for router in ROUTERS:
        app.include_router(router, prefix="/api/v1")
    return app


app = create_app()
