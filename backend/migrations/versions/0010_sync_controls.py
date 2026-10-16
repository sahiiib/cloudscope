"""Scoped collection and cooperative cross-process cancellation."""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sync_runs", sa.Column("scope_provider", sa.Text()))
    op.add_column("sync_runs", sa.Column("scope_account_id", sa.Text()))
    op.add_column("sync_runs", sa.Column("cancel_requested_at", sa.DateTime(timezone=True)))
    op.drop_constraint(op.f("ck_sync_runs_status"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_status"),
        "sync_runs",
        "status IN ('running', 'success', 'partial', 'failed', 'cancelled')",
    )


def downgrade() -> None:
    op.execute("UPDATE sync_runs SET status = 'failed' WHERE status = 'cancelled'")
    op.drop_constraint(op.f("ck_sync_runs_status"), "sync_runs", type_="check")
    op.create_check_constraint(
        op.f("ck_sync_runs_status"),
        "sync_runs",
        "status IN ('running', 'success', 'partial', 'failed')",
    )
    for column in ("cancel_requested_at", "scope_account_id", "scope_provider"):
        op.drop_column("sync_runs", column)
