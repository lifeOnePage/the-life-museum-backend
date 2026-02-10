from fastapi import APIRouter

from app.api.v1 import auth, users, scraper, record, library

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(scraper.router, prefix="/scraper", tags=["scraper"])
api_router.include_router(record.router, prefix="/record", tags=["record"])
api_router.include_router(library.router, prefix="/library", tags=["library"])
