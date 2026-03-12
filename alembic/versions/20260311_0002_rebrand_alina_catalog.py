"""rebrand catalog for AI Saller Alina

Revision ID: 20260311_0002
Revises: 20260310_0001
Create Date: 2026-03-11 21:10:00.000000
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260311_0002"
down_revision = "20260310_0001"
branch_labels = None
depends_on = None


NEW_SERVICE_NAMES = [
    "AI Saller Alina — AI-менеджер по продажам",
    "Интеграция с корпоративными документами и прайсами",
    "Интеграция с CRM (amoCRM / Bitrix24 / HubSpot)",
    "Полная замена первой линии продаж AI-агентом",
]

OLD_SERVICE_NAMES = [
    "AI-бот для Telegram",
    "AI-ассистент для базы знаний",
    "AI-обработка заявок",
    "AI-автоматизация поддержки",
]


def upgrade() -> None:
    services_table = sa.table(
        "services",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("price_from", sa.Numeric),
        sa.column("currency", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    op.execute(sa.text("UPDATE services SET is_active = false"))

    op.bulk_insert(
        services_table,
        [
            {
                "id": str(uuid4()),
                "name": "AI Saller Alina — AI-менеджер по продажам",
                "description": "Персональный AI-менеджер по продажам: обрабатывает входящие заявки, сохраняет статистику, ведет воронку продаж, прогревает лидов и выводит их к сделке.",
                "price_from": 120000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "Интеграция с корпоративными документами и прайсами",
                "description": "Подключение корпоративных документов и актуальных прайсов для точных ответов без выдуманных данных.",
                "price_from": 60000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "Интеграция с CRM (amoCRM / Bitrix24 / HubSpot)",
                "description": "Синхронизация лидов, этапов воронки, событий и задач с CRM-системой для полной автоматизации процесса продаж.",
                "price_from": 80000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "Полная замена первой линии продаж AI-агентом",
                "description": "Внедрение AI-агента, который закрывает первую линию коммуникации с клиентами и передает менеджеру только квалифицированные сделки.",
                "price_from": 180000,
                "currency": "RUB",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    for name in NEW_SERVICE_NAMES:
        op.execute(sa.text("DELETE FROM services WHERE name = :name").bindparams(name=name))

    for name in OLD_SERVICE_NAMES:
        op.execute(sa.text("UPDATE services SET is_active = true WHERE name = :name").bindparams(name=name))
