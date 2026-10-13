"""Short transactions; no Session shared across worker threads."""
from contextlib import contextmanager
from pathlib import Path
from sqlalchemy import create_engine, event, URL
from sqlalchemy.orm import Session
from .models import Base


class Database:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(URL.create('sqlite', database=str(path)),
                                    connect_args={'timeout': 10, 'check_same_thread': False})
        @event.listens_for(self.engine, 'connect')
        def configure(connection, record):
            cursor = connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA busy_timeout=10000')
            cursor.close()
        with self.engine.connect() as connection:
            connection.exec_driver_sql('PRAGMA journal_mode=WAL')
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with Session(self.engine, expire_on_commit=False) as session:
            with session.begin():
                yield session

    def close(self):
        self.engine.dispose()
