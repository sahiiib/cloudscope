"""Non-secret account connection references and optimistic configuration versions."""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "accounts",
        sa.Column("connection_mode", sa.Text(), nullable=False, server_default="runtime"),
    )
    op.add_column("accounts", sa.Column("credential_reference", sa.Text(), nullable=True))
    op.add_column(
        "accounts",
        sa.Column("configuration_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_check_constraint(
        op.f("ck_accounts_connection"),
        "accounts",
        "(connection_mode = 'runtime' AND credential_reference IS NULL) OR "
        "(connection_mode = 'dedicated' AND credential_reference IS NOT NULL "
        "AND source = 'ui' AND role_arn IS NULL AND external_id IS NULL)",
    )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.scalar(
        sa.text("SELECT count(*) FROM accounts WHERE connection_mode = 'dedicated'")
    ):
        raise RuntimeError(
            "Move Dedicated connections to Runtime before downgrade; "
            "never discard active credential references"
        )
    op.drop_constraint(op.f("ck_accounts_connection"), "accounts", type_="check")
    for name in ("configuration_version", "credential_reference", "connection_mode"):
        op.drop_column("accounts", name)
