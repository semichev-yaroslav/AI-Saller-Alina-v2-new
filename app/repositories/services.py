from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.service import Service


class ServiceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_active(self) -> list[Service]:
        stmt = select(Service).where(Service.is_active.is_(True)).order_by(Service.name.asc())
        return list(self.db.scalars(stmt))

    def list_all(self) -> list[Service]:
        stmt = select(Service).order_by(Service.name.asc())
        return list(self.db.scalars(stmt))
