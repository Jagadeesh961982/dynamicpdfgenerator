from fastapi import APIRouter

from app.api.api_v1.endpoints import admin, auth, chat, jobs, keys, users

router = APIRouter(prefix="/v1")
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(keys.router)
router.include_router(jobs.router)
router.include_router(chat.router)
router.include_router(admin.router)
