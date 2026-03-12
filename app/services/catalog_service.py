from app.db.models.service import Service
from app.repositories.services import ServiceRepository


class CatalogService:
    def __init__(self, services_repo: ServiceRepository) -> None:
        self.services_repo = services_repo

    def list_services(self, *, only_active: bool = True) -> list[Service]:
        if only_active:
            return self.services_repo.list_active()
        return self.services_repo.list_all()
