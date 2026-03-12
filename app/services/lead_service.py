from app.core.enums import LeadStage
from app.db.models.lead import Lead
from app.repositories.leads import LeadRepository


class LeadService:
    def __init__(self, leads_repo: LeadRepository) -> None:
        self.leads_repo = leads_repo

    def list_leads(self, *, stage: LeadStage | None, search: str | None, limit: int, offset: int) -> list[Lead]:
        return self.leads_repo.list(stage=stage, search=search, limit=limit, offset=offset)

    def get_lead(self, lead_id: str) -> Lead | None:
        return self.leads_repo.get(lead_id)
