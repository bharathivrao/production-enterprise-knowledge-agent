import psycopg
from dotenv import load_dotenv
from app.core.config import get_settings

settings = get_settings()
load_dotenv()

with psycopg.connect(
    host=settings.postgres_host,
    port=settings.postgres_port,
    dbname=settings.postgres_db,
    user=settings.postgres_user,
    password=settings.postgres_password.get_secret_value(),
    connect_timeout=5,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), current_user")
        print(cursor.fetchone())