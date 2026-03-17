from fastapi import APIRouter

from app.api.v1.endpoints import ai, auth, data, focus, health, notes, schedule, tasks, user

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(user.router)
api_router.include_router(notes.router)
api_router.include_router(tasks.router)
api_router.include_router(schedule.router)
api_router.include_router(ai.router)
api_router.include_router(focus.router)
api_router.include_router(data.router)
