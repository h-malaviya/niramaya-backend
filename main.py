from fastapi import FastAPI
from contextlib import asynccontextmanager
from database.postgres import init_postgres, close_postgres
import uvicorn
from api.v1.endpoints.auth import router as auth_router
from api.v1.endpoints.file_upload import router as file_apload_router
from api.v1.endpoints.profile import router as profile_router
from fastapi.middleware.cors import CORSMiddleware
from core.config import FRONTEND_URL
origins = [
    "http://127.0.0.1:3000",
    FRONTEND_URL
]
from core.middleware import AuthMiddleware
from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="Your API",
        version="1.0",
        description="Secure API with JWT",
        routes=app.routes,
    )

    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT"
        }
    }

    openapi_schema["security"] = [
        {"BearerAuth": []}
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres()
    yield
    await close_postgres()


app: FastAPI = FastAPI(lifespan=lifespan, title="Niramaya ")
app.include_router(auth_router)
app.include_router(file_apload_router)
app.include_router(profile_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # type: ignore
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthMiddleware)
app.openapi=custom_openapi
@app.get('/')
def hello():
    return 'hello'

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
