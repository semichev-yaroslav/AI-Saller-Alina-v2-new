"""add lead state for follow-up, stop mode and booking

Revision ID: 20260312_0003
Revises: 20260311_0002
Create Date: 2026-03-12 16:55:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260312_0003"
down_revision = "20260311_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("leads", sa.Column("qualification_data", sa.JSON(), nullable=True))
    op.add_column("leads", sa.Column("follow_up_step", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("leads", sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("leads", sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("last_user_message_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("last_bot_message_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("booking_slot_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("handoff_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")))

    op.execute(sa.text("UPDATE leads SET qualification_data = '{}' WHERE qualification_data IS NULL"))
    op.alter_column("leads", "qualification_data", nullable=False)

    op.create_index("ix_leads_next_follow_up_at", "leads", ["next_follow_up_at"])


def downgrade() -> None:
    op.drop_index("ix_leads_next_follow_up_at", table_name="leads")
    op.drop_column("leads", "handoff_requested")
    op.drop_column("leads", "booking_slot_at")
    op.drop_column("leads", "last_bot_message_at")
    op.drop_column("leads", "last_user_message_at")
    op.drop_column("leads", "stopped_at")
    op.drop_column("leads", "do_not_contact")
    op.drop_column("leads", "next_follow_up_at")
    op.drop_column("leads", "follow_up_step")
    op.drop_column("leads", "qualification_data")
