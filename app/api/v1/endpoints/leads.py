from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.enums import LeadStage
from app.repositories.leads import LeadRepository
from app.repositories.messages import MessageRepository
from app.schemas.lead import LeadRead
from app.schemas.message import MessageRead
from app.services.lead_service import LeadService

router = APIRouter()


@router.get("/leads", response_model=list[LeadRead], tags=["leads"])
def list_leads(
    stage: LeadStage | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[LeadRead]:
    service = LeadService(LeadRepository(db))
    return service.list_leads(stage=stage, search=search, limit=limit, offset=offset)


@router.get("/leads/{lead_id}", response_model=LeadRead, tags=["leads"])
def get_lead(lead_id: str, db: Session = Depends(get_db)) -> LeadRead:
    service = LeadService(LeadRepository(db))
    lead = service.get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


@router.get("/leads/{lead_id}/messages", response_model=list[MessageRead], tags=["leads"])
def list_messages(
    lead_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[MessageRead]:
    lead = LeadRepository(db).get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")

    messages_repo = MessageRepository(db)
    return messages_repo.list_by_lead(lead_id, limit=limit, offset=offset)
