from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from app.config import settings

pool = ConnectionPool(
    settings.database_url,
    min_size=1,
    max_size=5,
    open=False,
    kwargs={"row_factory": dict_row},
)

def get_conn():
    with pool.connection() as conn:
        yield conn
