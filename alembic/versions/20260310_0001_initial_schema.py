"""initial schema

Revision ID: 20260310_0001
Revises:
Create Date: 2026-03-10 18:20:00.000000
"""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260310_0001"
down_revision = None
branch_labels = None
depends_on = None


intent_enum = sa.Enum(
    "greeting",
    "service_question",
    "price_question",
    "objection",
    "ready_to_buy",
    "booking_intent",
    "contact_sharing",
    "unclear",
    name="intenttype",
    native_enum=False,
)

stage_enum = sa.Enum(
    "new",
    "engaged",
    "qualified",
    "interested",
    "booking_pending",
    "booked",
    "lost",
    name="leadstage",
    native_enum=False,
)

source_enum = sa.Enum("user", "assistant", "system", name="messagesource", native_enum=False)
channel_enum = sa.Enum("telegram", "api_simulation", name="messagechannel", native_enum=False)
delivery_enum = sa.Enum("pending", "sent", "failed", name="deliverystatus", native_enum=False)
ai_status_enum = sa.Enum("success", "error", name="airunstatus", native_enum=False)


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=True),
        sa.Column("full_name", sa.String(length=256), nullable=True),
        sa.Column("phone", sa.String(length=64), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("stage", stage_enum, nullable=False, server_default="new"),
        sa.Column("last_intent", intent_enum, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_user_id"),
    )
    op.create_index("ix_leads_telegram_user_id", "leads", ["telegram_user_id"])
    op.create_index("ix_leads_telegram_chat_id", "leads", ["telegram_chat_id"])
    op.create_index("ix_leads_stage", "leads", ["stage"])

    op.create_table(
        "services",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("price_from", sa.Numeric(10, 2), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("source", source_enum, nullable=False),
        sa.Column("channel", channel_enum, nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_update_id", sa.BigInteger(), nullable=True),
        sa.Column("delivery_status", delivery_enum, nullable=False, server_default="pending"),
        sa.Column("delivery_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_lead_id", "messages", ["lead_id"])
    op.create_index("ix_messages_lead_created", "messages", ["lead_id", "created_at"])
    op.create_index("ix_messages_telegram_update_unique", "messages", ["telegram_update_id"], unique=True)

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("input_message_id", sa.String(length=36), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("intent", intent_enum, nullable=True),
        sa.Column("predicted_stage", stage_enum, nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reply_text", sa.Text(), nullable=True),
        sa.Column("raw_response", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", ai_status_enum, nullable=False, server_default="success"),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["input_message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_runs_lead_id", "ai_runs", ["lead_id"])

    services_table = sa.table(
        "services",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("price_from", sa.Numeric),
        sa.column("currency", sa.String),
        sa.column("is_active", sa.Boolean),
    )

    op.bulk_insert(
        services_table,
        [
            {
                "id": str(uuid4()),
                "name": "AI-бот для Telegram",
                "description": "Автоматизация первичных продаж и поддержки клиентов в Telegram: ответы, квалификация лидов, передача менеджеру.",
                "price_from": 50000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "AI-ассистент для базы знаний",
                "description": "Интеллектуальный ассистент для внутренних регламентов, FAQ и документации компании.",
                "price_from": 70000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "AI-обработка заявок",
                "description": "Классификация и маршрутизация входящих заявок из разных каналов с приоритизацией.",
                "price_from": 90000,
                "currency": "RUB",
                "is_active": True,
            },
            {
                "id": str(uuid4()),
                "name": "AI-автоматизация поддержки",
                "description": "AI-помощник первой линии поддержки с контекстными ответами и сокращением времени обработки тикетов.",
                "price_from": 85000,
                "currency": "RUB",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_runs_lead_id", table_name="ai_runs")
    op.drop_table("ai_runs")

    op.drop_index("ix_messages_telegram_update_unique", table_name="messages")
    op.drop_index("ix_messages_lead_created", table_name="messages")
    op.drop_index("ix_messages_lead_id", table_name="messages")
    op.drop_table("messages")

    op.drop_table("services")

    op.drop_index("ix_leads_stage", table_name="leads")
    op.drop_index("ix_leads_telegram_chat_id", table_name="leads")
    op.drop_index("ix_leads_telegram_user_id", table_name="leads")
    op.drop_table("leads")
