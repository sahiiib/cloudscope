"""Recoverable account deletion without deleting cloud resources or inventory history."""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts", sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_check_constraint(
        op.f("ck_accounts_deleted"), "accounts", "NOT deleted OR (NOT enabled AND source = 'ui')"
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM accounts WHERE deleted")):
        raise RuntimeError(
            "Restore deleted accounts before downgrade; do not expose removed accounts"
        )
    op.drop_constraint(op.f("ck_accounts_deleted"), "accounts", type_="check")
    op.drop_column("accounts", "deleted")
