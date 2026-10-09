from sqlalchemy import Engine, text


def test_postgres_round_trip_in_throwaway_database(db_engine: Engine) -> None:
    with db_engine.begin() as connection:
        database_name = connection.scalar(text("SELECT current_database()"))
        assert database_name.startswith("cloudscope_test_")
        assert database_name != "cloudscope"
        assert int(connection.scalar(text("SHOW server_version_num"))) >= 160000
        connection.execute(text("CREATE TABLE fixture_smoke (id integer PRIMARY KEY, name text)"))
        connection.execute(
            text("INSERT INTO fixture_smoke (id, name) VALUES (:id, :name)"),
            {"id": 1, "name": "test-instance"},
        )

    # A new connection sees committed data in the isolated test database.
    with db_engine.connect() as connection:
        assert connection.scalar(text("SELECT name FROM fixture_smoke WHERE id = 1")) == (
            "test-instance"
        )
    with db_engine.begin() as connection:
        connection.execute(text("DROP TABLE fixture_smoke"))
