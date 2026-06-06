import psycopg


def get_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="fonio_hackathon",
        user="postgres",
        password="7007",
    )


def seed():
    with get_connection() as conn:
        with conn.cursor() as cur:
            # ── 1. Insert clients ──────────────────────────────────────
            cur.execute("""
                INSERT INTO clients (name, phone)
                VALUES
                    ('Anna Müller',   '+436601111111'),
                    ('Lukas Weber',   '+436601111112'),
                    ('Sofia Gruber',  '+436601111113'),
                    ('David Steiner', '+436601111114'),
                    ('Mia Novak',     '+436601111115')
                ON CONFLICT (phone) DO NOTHING;
            """)

            # ── 2. Fetch IDs by phone so we don't assume order ─────────
            cur.execute("SELECT client_id, name FROM clients ORDER BY client_id;")
            rows = cur.fetchall()
            id_of = {name: cid for cid, name in rows}

            print("Clients inserted:")
            for name, cid in id_of.items():
                print(f"  {cid} → {name}")

            # ── 3. Insert appointments (scheduled, real booked slots) ──
            cur.execute(
                """
                INSERT INTO appointments
                    (client_id, reason_of_appointment, appointment_at, status)
                VALUES
                    (%s, 'Dental cleaning', '2026-06-08 10:00:00', 'scheduled'),
                    (%s, 'Tooth filling',   '2026-06-08 11:00:00', 'scheduled'),
                    (%s, 'Check-up',        '2026-06-09 09:00:00', 'scheduled')
            """,
                (
                    id_of["Anna Müller"],
                    id_of["Lukas Weber"],
                    id_of["David Steiner"],
                ),
            )

            print("Appointments inserted.")

            # ── 4. Insert waitlist entries (people waiting) ────────────
            cur.execute(
                """
                INSERT INTO waitlist_entries
                    (client_id, reason_of_appointment, preferred_time, active)
                VALUES
                    (%s, 'Dental cleaning', 'afternoon', TRUE),
                    (%s, 'Dental cleaning', 'morning',   TRUE),
                    (%s, 'Check-up',        'any',       TRUE)
            """,
                (
                    id_of["Sofia Gruber"],
                    id_of["Mia Novak"],
                    id_of["Lukas Weber"],
                ),
            )

            print("Waitlist entries inserted.")

        conn.commit()

    print("\nAll draft data inserted successfully.")


if __name__ == "__main__":
    seed()
