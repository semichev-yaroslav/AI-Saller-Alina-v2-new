from fastapi import APIRouter

from app.api.v1.endpoints.health import router as health_router
from app.api.v1.endpoints.leads import router as leads_router
from app.api.v1.endpoints.services import router as services_router
from app.api.v1.endpoints.simulate import router as simulate_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(leads_router)
api_router.include_router(services_router)
api_router.include_router(simulate_router)
