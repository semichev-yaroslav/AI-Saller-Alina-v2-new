from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.repositories.services import ServiceRepository
from app.schemas.service import ServiceRead
from app.services.catalog_service import CatalogService

router = APIRouter()


@router.get("/services", response_model=list[ServiceRead], tags=["services"])
def list_services(db: Session = Depends(get_db)) -> list[ServiceRead]:
    service = CatalogService(ServiceRepository(db))
    return service.list_services(only_active=True)
