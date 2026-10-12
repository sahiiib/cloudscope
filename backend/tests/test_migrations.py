from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import Engine, inspect, text

from cloudscope.db.models import Base


def test_migration_schema_and_round_trip(migrated_engine: Engine, alembic_config: Config) -> None:
    with migrated_engine.connect() as connection:
        assert (
            compare_metadata(
                MigrationContext.configure(connection, opts={"compare_server_default": True}),
                Base.metadata,
            )
            == []
        )
        assert set(inspect(connection).get_table_names()) == {
            *Base.metadata.tables,
            "alembic_version",
        }
        assert (
            connection.scalar(text("SELECT extname FROM pg_extension WHERE extname = 'pg_trgm'"))
            == "pg_trgm"
        )
        indexes = dict(
            connection.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'instances'")
            ).all()
        )
        assert "USING gin (search_text gin_trgm_ops)" in indexes["ix_instances_search_text"]
        assert "USING gin (tags)" in indexes["ix_instances_tags"]
        for column in ["provider", "account_id", "region", "state", "present"]:
            assert f"USING btree ({column})" in indexes[f"ix_instances_{column}"]
        search_column = next(
            c for c in inspect(connection).get_columns("instances") if c["name"] == "search_text"
        )
        assert search_column["computed"]["persisted"] is True
        connection.rollback()
        alembic_config.attributes["connection"] = connection
        try:
            session_indexes = inspect(connection).get_indexes("sessions")
            assert any(
                index["name"] == "ix_sessions_user_id" and index["column_names"] == ["user_id"]
                for index in session_indexes
            )
            assert (
                inspect(connection).get_foreign_keys("sessions")[0]["options"]["ondelete"]
                == "CASCADE"
            )
            connection.commit()
            command.downgrade(alembic_config, "0002")
            assert "totp_last_used_step" not in {
                column["name"] for column in inspect(connection).get_columns("users")
            }
            assert "mfa_failures" not in {
                column["name"] for column in inspect(connection).get_columns("sessions")
            }
            connection.commit()
            command.upgrade(alembic_config, "head")
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            connection.commit()
            command.downgrade(alembic_config, "0001")
            assert not any(
                index["name"] == "ix_sessions_user_id"
                for index in inspect(connection).get_indexes("sessions")
            )
            assert "ondelete" not in inspect(connection).get_foreign_keys("sessions")[0]["options"]
            connection.commit()
            command.upgrade(alembic_config, "head")
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
            connection.commit()
            command.downgrade(alembic_config, "base")
            assert inspect(connection).get_table_names() == ["alembic_version"]
            assert (
                connection.scalar(
                    text(
                        "SELECT count(*) FROM pg_proc "
                        "WHERE proname = 'cloudscope_instance_search_text'"
                    )
                )
                == 0
            )
            # Inspection starts a transaction; finish it before Alembic manages the upgrade.
            connection.commit()
            command.upgrade(alembic_config, "head")
            assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        finally:
            connection.rollback()
            command.upgrade(alembic_config, "head")
            alembic_config.attributes.pop("connection", None)


def test_existing_accounts_gain_file_source_and_default_regions(
    migrated_engine: Engine, alembic_config: Config
) -> None:
    with migrated_engine.connect() as connection:
        alembic_config.attributes["connection"] = connection
        try:
            command.downgrade(alembic_config, "0003")
            connection.execute(
                text(
                    "INSERT INTO accounts (provider, account_id, name) "
                    "VALUES ('aws', '111111111111', 'existing')"
                )
            )
            connection.commit()
            command.upgrade(alembic_config, "head")
            row = connection.execute(
                text(
                    "SELECT source, regions, role_arn, external_id, created_at, updated_at "
                    "FROM accounts WHERE account_id = '111111111111'"
                )
            ).one()
            assert row[:4] == ("file", "all", None, None)
            assert row.created_at is not None and row.updated_at is not None
            connection.execute(text("DELETE FROM accounts WHERE account_id = '111111111111'"))
            connection.commit()
        finally:
            command.upgrade(alembic_config, "head")
            alembic_config.attributes.pop("connection", None)


def test_alias_migration_preserves_existing_accounts(migrated_engine, alembic_config):
    with migrated_engine.connect() as connection:
        alembic_config.attributes["connection"] = connection
        try:
            command.downgrade(alembic_config, "0004")
            connection.execute(
                text(
                    "INSERT INTO accounts (provider, account_id, name) "
                    "VALUES ('aws', '111111111111', 'existing')"
                )
            )
            connection.commit()
            command.upgrade(alembic_config, "head")
            row = connection.execute(
                text(
                    "SELECT name, cloud_alias, cloud_alias_checked_at "
                    "FROM accounts WHERE account_id = '111111111111'"
                )
            ).one()
            assert row == ("existing", None, None)
            connection.execute(text("DELETE FROM accounts WHERE account_id = '111111111111'"))
            connection.commit()
        finally:
            command.upgrade(alembic_config, "head")
            alembic_config.attributes.pop("connection", None)
