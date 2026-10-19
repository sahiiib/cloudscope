"""OIDC identities and single-use, browser-bound authorization state.

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("oidc_issuer", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("oidc_subject", sa.Text(), nullable=True))
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=True)
    op.create_unique_constraint("uq_users_oidc_identity", "users", ["oidc_issuer", "oidc_subject"])
    op.create_table(
        "oidc_login_states",
        sa.Column("id_hash", sa.Text(), primary_key=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("nonce", sa.Text(), nullable=False),
        sa.Column("code_verifier", sa.Text(), nullable=False),
        sa.Column("next_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # Preserve identities as inactive users with an unverifiable hash, not local logins.
    op.execute(
        "UPDATE users SET is_active = false, password_hash = '' WHERE oidc_issuer IS NOT NULL"
    )
    op.execute("UPDATE users SET password_hash = '' WHERE password_hash IS NULL")
    op.drop_table("oidc_login_states")
    op.drop_constraint("uq_users_oidc_identity", "users", type_="unique")
    op.drop_column("users", "oidc_subject")
    op.drop_column("users", "oidc_issuer")
    op.alter_column("users", "password_hash", existing_type=sa.Text(), nullable=False)
