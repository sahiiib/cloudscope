"""Persist MFA replay protection and half-session failure counts.

Revision ID: 0003
Revises: 0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_last_used_step", sa.BigInteger(), nullable=True))
    op.add_column(
        "sessions",
        sa.Column("mfa_failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint("ck_sessions_mfa_failures", "sessions", "mfa_failures >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_sessions_mfa_failures", "sessions", type_="check")
    op.drop_column("sessions", "mfa_failures")
    op.drop_column("users", "totp_last_used_step")
