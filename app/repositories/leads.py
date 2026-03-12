from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import LeadStage
from app.db.models.lead import Lead


class LeadRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, *, stage: LeadStage | None = None, search: str | None = None, limit: int = 50, offset: int = 0) -> list[Lead]:
        stmt = select(Lead).order_by(Lead.created_at.desc()).limit(limit).offset(offset)
        if stage:
            stmt = stmt.where(Lead.stage == stage)
        if search:
            pattern = f"%{search.strip()}%"
            stmt = stmt.where((Lead.full_name.ilike(pattern)) | (Lead.username.ilike(pattern)))
        return list(self.db.scalars(stmt))

    def get(self, lead_id: str) -> Lead | None:
        return self.db.get(Lead, lead_id)

    def get_by_telegram_user_id(self, telegram_user_id: int) -> Lead | None:
        stmt = select(Lead).where(Lead.telegram_user_id == telegram_user_id)
        return self.db.scalar(stmt)

    def create_or_update_from_telegram(
        self,
        *,
        telegram_user_id: int,
        telegram_chat_id: int,
        username: str | None,
        full_name: str | None,
    ) -> tuple[Lead, bool]:
        lead = self.get_by_telegram_user_id(telegram_user_id)
        created = False
        if lead is None:
            lead = Lead(
                telegram_user_id=telegram_user_id,
                telegram_chat_id=telegram_chat_id,
                username=username,
                full_name=full_name,
            )
            self.db.add(lead)
            created = True
        else:
            lead.telegram_chat_id = telegram_chat_id
            if username:
                lead.username = username
            if full_name:
                lead.full_name = full_name

        self.db.flush()
        return lead, created

    def update_contact_info(self, lead: Lead, *, phone: str | None = None, email: str | None = None) -> Lead:
        if phone:
            lead.phone = phone
        if email:
            lead.email = email
        self.db.flush()
        return lead
