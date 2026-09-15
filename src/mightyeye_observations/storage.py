"""Portable SQL repository: PostgreSQL deployment, SQLite local demo."""

from pathlib import Path

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    func,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.pool import StaticPool

metadata = MetaData()
settings = Table(
    "schema_settings",
    metadata,
    Column("key", String, primary_key=True),
    Column("value", JSON, nullable=False),
)
cameras = Table(
    "cameras",
    metadata,
    Column("camera_id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)
observations = Table(
    "observations",
    metadata,
    Column("sequence", Integer, primary_key=True, autoincrement=True),
    Column("observation_id", String, unique=True, nullable=False),
    Column("camera_id", String, nullable=False),
    Column("payload", JSON, nullable=False),
)
entities = Table(
    "entities",
    metadata,
    Column("entity_id", String, primary_key=True),
    Column("payload", JSON, nullable=False),
)
incidents = Table(
    "incidents",
    metadata,
    Column("incident_id", String, primary_key=True),
    Column("event_type", String, nullable=False),
    Column("camera_id", String, nullable=False),
    Column("start_time", String, nullable=False),
    Column("trigger_time_us", BigInteger, nullable=False),
    Column("payload", JSON, nullable=False),
)
Index(
    "incidents_filter",
    incidents.c.event_type,
    incidents.c.camera_id,
    incidents.c.start_time,
)
evidence = Table(
    "evidence",
    metadata,
    Column("evidence_id", String, primary_key=True),
    Column("incident_id", String, ForeignKey("incidents.incident_id"), nullable=False),
    Column("payload", JSON, nullable=False),
)
reviews = Table(
    "reviews",
    metadata,
    Column("review_id", String, primary_key=True),
    Column("incident_id", String, ForeignKey("incidents.incident_id"), nullable=False),
    Column("payload", JSON, nullable=False),
)


class Repository:
    def __init__(self, url: str):
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
            if url.endswith(":memory:"):
                kwargs["poolclass"] = StaticPool
            elif url.startswith("sqlite:///"):
                Path(url.removeprefix("sqlite:///")).parent.mkdir(
                    parents=True, exist_ok=True
                )
        self.engine = create_engine(url, **kwargs)
        if url.startswith("sqlite"):

            @event.listens_for(self.engine, "connect")
            def sqlite_pragmas(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

        metadata.create_all(self.engine)
        self.dialect = self.engine.dialect.name
        with self.engine.begin() as conn:
            version = conn.execute(
                select(settings.c.value).where(settings.c.key == "schema_version")
            ).scalar_one_or_none()
            if version not in (None, 1, 2):
                raise ValueError("Unsupported database schema version")
            # Idempotent v1 -> v2 migration: sort alerts by trigger time, not window start.
            columns = {
                column["name"] for column in inspect(conn).get_columns("incidents")
            }
            if "trigger_time_us" not in columns:
                conn.execute(
                    text("ALTER TABLE incidents ADD COLUMN trigger_time_us BIGINT")
                )
                from datetime import datetime

                for incident_id, payload in conn.execute(
                    select(incidents.c.incident_id, incidents.c.payload)
                ).all():
                    timestamp = datetime.fromisoformat(
                        payload["end_time"] or payload["start_time"]
                    )
                    conn.execute(
                        update(incidents)
                        .where(incidents.c.incident_id == incident_id)
                        .values(trigger_time_us=int(timestamp.timestamp() * 1_000_000))
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS incidents_trigger ON incidents(trigger_time_us)"
                )
            )
            if version is None:
                conn.execute(insert(settings).values(key="schema_version", value=2))
            elif version == 1:
                conn.execute(
                    update(settings)
                    .where(settings.c.key == "schema_version")
                    .values(value=2)
                )

    @staticmethod
    def put(conn, table, key, value, **columns):
        primary = list(table.primary_key.columns)[0]
        exists = conn.execute(select(primary).where(primary == key)).first()
        values = {"payload": value, **columns}
        if exists:
            conn.execute(update(table).where(primary == key).values(**values))
        else:
            conn.execute(insert(table).values(**{primary.name: key}, **values))

    def get(self, table, key):
        primary = list(table.primary_key.columns)[0]
        with self.engine.connect() as conn:
            return conn.execute(
                select(table.c.payload).where(primary == key)
            ).scalar_one_or_none()

    def all(self, table):
        with self.engine.connect() as conn:
            return list(conn.execute(select(table.c.payload)).scalars())

    def observation_stream(self):
        with self.engine.connect() as conn:
            for payload in conn.execute(
                select(observations.c.payload).order_by(observations.c.sequence)
            ).scalars():
                yield payload

    def list_incidents(self, *, event_type=None, camera_id=None, limit=100, offset=0):
        query = select(incidents.c.payload)
        if event_type:
            query = query.where(incidents.c.event_type == event_type)
        if camera_id:
            query = query.where(incidents.c.camera_id == camera_id)
        query = (
            query.order_by(incidents.c.trigger_time_us.desc(), incidents.c.incident_id)
            .limit(limit)
            .offset(offset)
        )
        with self.engine.connect() as conn:
            return list(conn.execute(query).scalars())

    def incident_count(self):
        with self.engine.connect() as conn:
            return conn.execute(
                select(func.count()).select_from(incidents)
            ).scalar_one()
