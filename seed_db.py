import psycopg
import hashlib


def get_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="fonio_hackathon",
        user="postgres",
        password="7007",
    )


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def seed():
    with get_connection() as conn:
        with conn.cursor() as cur:

            # ── 1. Insert clients ──────────────────────────────────────
            password = hash_password("test1234")
            cur.execute(
                """
                INSERT INTO clients (name, phone, password_hash)
                VALUES
                    ('Anna Müller',   '+436601111111', %s),
                    ('Lukas Weber',   '+436601111112', %s),
                    ('Sofia Gruber',  '+436601111113', %s),
                    ('David Steiner', '+436601111114', %s),
                    ('Mia Novak',     '+436601111115', %s)
                ON CONFLICT (phone) DO NOTHING;
                """,
                [password] * 5,
            )

            # ── 2. Fetch IDs by name ───────────────────────────────────
            cur.execute(
                "SELECT client_id, name FROM clients WHERE phone LIKE '+4366011111%';"
            )
            rows = cur.fetchall()
            id_of = {name: cid for cid, name in rows}

            print("Clients:")
            for name, cid in id_of.items():
                print(f"  {cid} → {name}")

            # ── 3. Insert appointments ─────────────────────────────────
            cur.execute(
                """
                INSERT INTO appointments
                    (client_id, reason_of_appointment, appointment_at, doctor_name, status)
                VALUES
                    (%s, 'Dental cleaning', '2026-06-10 10:00:00', 'Dr. Mike',   'scheduled'),
                    (%s, 'Tooth filling',   '2026-06-10 11:00:00', 'Dr. James',  'scheduled'),
                    (%s, 'Check-up',        '2026-06-11 09:00:00', 'Dr. J Pork', 'scheduled'),
                    (%s, 'Root canal',      '2026-06-11 14:00:00', 'Dr. James',  'scheduled'),
                    (%s, 'Teeth whitening', '2026-06-12 10:30:00', 'Dr. Mike',   'scheduled');
                """,
                (
                    id_of["Anna Müller"],
                    id_of["Lukas Weber"],
                    id_of["David Steiner"],
                    id_of["Anna Müller"],
                    id_of["Mia Novak"],
                ),
            )
            print("Appointments inserted.")

            # ── 4. Insert waitlist entries ─────────────────────────────
            # Sofia (priority 2) gets called first when Anna cancels.
            # If Sofia declines, Mia (priority 1) gets called next.
            cur.execute(
                """
                INSERT INTO waitlist_entries
                    (client_id, reason_of_appointment, doctor_name, preferred_time, priority, active)
                VALUES
                    (%s, 'Dental cleaning', 'Dr. Mike',   '2026-06-10 10:00:00', 2, TRUE),
                    (%s, 'Dental cleaning', 'Dr. Mike',   '2026-06-10 10:00:00', 1, TRUE),
                    (%s, 'Check-up',        'Dr. J Pork', '2026-06-11 09:00:00', 1, TRUE),
                    (%s, 'Tooth filling',   'Dr. James',  '2026-06-10 11:00:00', 1, TRUE);
                """,
                (
                    id_of["Sofia Gruber"],
                    id_of["Mia Novak"],
                    id_of["Lukas Weber"],
                    id_of["David Steiner"],
                ),
            )
            print("Waitlist entries inserted.")

        conn.commit()
    print("\n✅ All seed data inserted successfully.")
    print("\nTest credentials (all passwords: test1234):")
    print("  Anna Müller   → phone: +436601111111")
    print("  Lukas Weber   → phone: +436601111112")
    print("  Sofia Gruber  → phone: +436601111113")
    print("  David Steiner → phone: +436601111114")
    print("  Mia Novak     → phone: +436601111115")
    print("\nTest scenario: Cancel Anna's Dental cleaning with Dr. Mike")
    print("  → Sofia Gruber (priority 2) gets called first")
    print("  → if she declines, Mia Novak (priority 1) gets called next")


if __name__ == "__main__":
    seed()