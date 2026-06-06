import psycopg


def get_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="fonio_hackathon",
        user="postgres",
        password="7007",
    )


def create_tables():
    create_clients = """
    CREATE TABLE IF NOT EXISTS clients (
        client_id     SERIAL       PRIMARY KEY,
        name          VARCHAR(255) NOT NULL,
        phone         VARCHAR(50)  NOT NULL UNIQUE,
        password_hash VARCHAR(255)
    );
    """

    create_appointments = """
    CREATE TABLE IF NOT EXISTS appointments (
        appointment_id        SERIAL       PRIMARY KEY,
        client_id             INTEGER      NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
        reason_of_appointment VARCHAR(255) NOT NULL,
        appointment_at        TIMESTAMP    NOT NULL,
        doctor_name           VARCHAR(255) NOT NULL,
        status                VARCHAR(50)  NOT NULL DEFAULT 'scheduled'
    );
    """

    create_waitlist = """
    CREATE TABLE IF NOT EXISTS waitlist_entries (
        waitlist_id           SERIAL       PRIMARY KEY,
        client_id             INTEGER      NOT NULL REFERENCES clients(client_id) ON DELETE CASCADE,
        reason_of_appointment VARCHAR(255) NOT NULL,
        doctor_name           VARCHAR(255) NOT NULL,
        preferred_time        TIMESTAMP,
        priority              INTEGER      NOT NULL DEFAULT 1,
        active                BOOLEAN      NOT NULL DEFAULT TRUE
    );
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_clients)
            cur.execute(create_appointments)
            cur.execute(create_waitlist)
        conn.commit()

    print("Tables created successfully.")


if __name__ == "__main__":
    create_tables()
