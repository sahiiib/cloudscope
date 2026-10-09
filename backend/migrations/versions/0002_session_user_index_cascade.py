"""Index session users and cascade user deletion.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.drop_constraint("fk_sessions_user_id_users", "sessions", type_="foreignkey")
    op.create_foreign_key(
        "fk_sessions_user_id_users", "sessions", "users", ["user_id"], ["id"], ondelete="CASCADE"
    )


def downgrade() -> None:
    op.drop_constraint("fk_sessions_user_id_users", "sessions", type_="foreignkey")
    op.create_foreign_key("fk_sessions_user_id_users", "sessions", "users", ["user_id"], ["id"])
    op.drop_index("ix_sessions_user_id", table_name="sessions")
