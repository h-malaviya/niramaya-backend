from fastapi import FastAPI
from contextlib import asynccontextmanager
from database.postgres import init_postgres, close_postgres
import uvicorn
from api.v1.endpoints.auth import router
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres()
    yield
    await close_postgres()


app: FastAPI = FastAPI(lifespan=lifespan, title="Async FastAPI PostgreSQL Inventory Manager")
app.include_router(router)

@app.get('/')
def hello():
    return 'hello'

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
