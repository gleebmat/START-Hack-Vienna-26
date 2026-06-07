from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, field_validator
from typing import Optional
import psycopg
import hashlib
import os
import httpx
from dotenv import load_dotenv


load_dotenv()
app = FastAPI(title="Dental clinic system")
security = HTTPBasic()


# ── Configuration ──────────────────────────────────────────────
FONIO_API_KEY = os.environ.get("FONIO_API_KEY")


# ── DB connection ──────────────────────────────────────────────
def get_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="fonio_hackathon",
        user="postgres",
        password="7007",
    )


# ── Password hashing ───────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Auth ───────────────────────────────────────────────────────
def require_client(
    credentials: HTTPBasicCredentials = Depends(security),
) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT client_id, name, phone
                FROM clients
                WHERE phone = %s AND password_hash = %s;
                """,
                (credentials.username, hash_password(credentials.password)),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return {"client_id": row[0], "name": row[1], "phone": row[2]}


# ── Fonio call ─────────────────────────────────────────────────
def trigger_fonio_call(candidate: dict, cancelled_appointment: dict):
    raw_time = cancelled_appointment["appointment_at"]
    try:
        human_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S").strftime(
            "%B %d at %I:%M %p"
        )
    except ValueError:
        human_time = raw_time

    payload = {
        "fromNumber": "+436767563950",
        "toNumber": candidate["phone"],
        "agentId": "fa1f00ba-96fd-4a5e-afb5-4f7f4f679103",
        "context": {
            "patient_name": candidate["name"],
            "reason": cancelled_appointment["reason_of_appointment"],
            "doctor": cancelled_appointment.get("doctor_name", "TBD"),
            "slot_time": human_time,
            "slot_time_db": raw_time,
        },
    }
    try:  # ← payload IS used here
        response = httpx.post(
            "https://app.fonio.ai/api/public/v1/outbound_call",
            json=payload,  # ← right here
            headers={"Authorization": f"Bearer {FONIO_API_KEY}"},
            timeout=10,
        )
        print(
            f"[FONIO] Call triggered → status {response.status_code} | {response.text}"
        )
        return response.json()
    except Exception as e:
        print(f"[FONIO] ERROR — call failed: {e}")
        return {
            "error": str(e)
        }  # ── Request models ─────────────────────────────────────────────


class NewClient(BaseModel):
    name: str
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def phone_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("phone cannot be empty")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 4:
            raise ValueError("password must be at least 4 characters")
        return v


# priority removed — waitlist-only, always defaulted to 1 by DB
VALID_DOCTORS = {"Dr. J Pork", "Dr. James", "Dr. Mike"}


class NewAppointment(BaseModel):
    reason_of_appointment: str
    appointment_at: str
    doctor_name: str

    @field_validator("doctor_name")
    @classmethod
    def doctor_must_be_valid(cls, v: str) -> str:
        if v not in VALID_DOCTORS:
            raise ValueError(f"doctor_name must be one of: {', '.join(VALID_DOCTORS)}")
        return v


class CancelRequest(BaseModel):
    reason: Optional[str] = "Cancelled by client"


# ── Endpoints ──────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "Dental clinic API is running"}


# 1. REGISTER — open, no auth
@app.post("/clients", status_code=201)
def create_client(payload: NewClient):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT client_id FROM clients WHERE phone = %s;",
                (payload.phone,),
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"Phone {payload.phone} is already registered",
                )
            cur.execute(
                """
                INSERT INTO clients (name, phone, password_hash)
                VALUES (%s, %s, %s)
                RETURNING client_id, name, phone;
                """,
                (payload.name, payload.phone, hash_password(payload.password)),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "client_id": row[0],
        "name": row[1],
        "phone": row[2],
        "message": "Client created. Use your phone and password to authorize.",
    }


# 2. CREATE appointment — requires auth
@app.post("/appointments", status_code=201)
def create_appointment(
    payload: NewAppointment,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT appointment_id FROM appointments
                WHERE appointment_at = %s
                  AND doctor_name = %s
                  AND status = 'scheduled';
                """,
                (payload.appointment_at, payload.doctor_name),
            )
            conflict = cur.fetchone()

            if conflict:
                cur.execute(
                    """
                    SELECT waitlist_id FROM waitlist_entries
                    WHERE client_id = %s
                      AND reason_of_appointment = %s
                      AND doctor_name = %s
                      AND active = TRUE;
                    """,
                    (
                        client["client_id"],
                        payload.reason_of_appointment,
                        payload.doctor_name,
                    ),
                )
                already_waiting = cur.fetchone()

                if already_waiting:
                    raise HTTPException(
                        status_code=400,
                        detail="This slot is taken and you are already on the waitlist for this treatment with this doctor.",
                    )

                # FIX: pass 1 (DB default) — column is NOT NULL, cannot insert NULL
                cur.execute(
                    """
                    INSERT INTO waitlist_entries
                        (client_id, reason_of_appointment, doctor_name, preferred_time, priority, active)
                    VALUES (%s, %s, %s, %s, %s, TRUE)
                    RETURNING waitlist_id;
                    """,
                    (
                        client["client_id"],
                        payload.reason_of_appointment,
                        payload.doctor_name,
                        payload.appointment_at,
                        1,
                    ),
                )
                waitlist_row = cur.fetchone()
                conn.commit()

                return {
                    "status": "waitlisted",
                    "waitlist_id": waitlist_row[0],
                    "client_name": client["name"],
                    "reason_of_appointment": payload.reason_of_appointment,
                    "doctor_name": payload.doctor_name,
                    "preferred_time": payload.appointment_at,
                    "message": (
                        f"The slot at {payload.appointment_at} is already taken. "
                        "You have been added to the waitlist. "
                        "If it opens up, you will receive a call automatically."
                    ),
                }

            cur.execute(
                """
                INSERT INTO appointments
                    (client_id, reason_of_appointment, appointment_at, doctor_name, status)
                VALUES (%s, %s, %s, %s, 'scheduled')
                RETURNING appointment_id, client_id,
                          reason_of_appointment, appointment_at, doctor_name, status;
                """,
                (
                    client["client_id"],
                    payload.reason_of_appointment,
                    payload.appointment_at,
                    payload.doctor_name,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "status": "booked",
        "appointment_id": row[0],
        "client_id": row[1],
        "client_name": client["name"],
        "reason_of_appointment": row[2],
        "appointment_at": str(row[3]),
        "doctor_name": row[4],
        "appointment_status": row[5],
        "message": "Appointment created successfully",
    }


@app.get("/doctors")
def get_doctors():
    # Convert the set to a list so it can be sent as JSON
    return {"doctors": list(VALID_DOCTORS)}


# 3. LIST my active appointments — requires auth
@app.get("/appointments/mine")
def my_appointments(
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT appointment_id, reason_of_appointment, appointment_at, doctor_name, status
                FROM appointments
                WHERE client_id = %s
                  AND status != 'cancelled'
                ORDER BY appointment_at ASC;
                """,
                (client["client_id"],),
            )
            appointments = cur.fetchall()

            cur.execute(
                """
                SELECT waitlist_id, reason_of_appointment, doctor_name, preferred_time, priority
                FROM waitlist_entries
                WHERE client_id = %s
                  AND active = TRUE
                ORDER BY preferred_time ASC;
                """,
                (client["client_id"],),
            )
            waitlist = cur.fetchall()

    return {
        "client_name": client["name"],
        "appointments": [
            {
                "appointment_id": row[0],
                "reason_of_appointment": row[1],
                "appointment_at": str(row[2]),
                "doctor_name": row[3],
                "status": row[4],
                "action": f"To cancel: POST /appointments/{row[0]}/cancel",
            }
            for row in appointments
        ],
        "waitlist": [
            {
                "waitlist_id": row[0],
                "reason_of_appointment": row[1],
                "doctor_name": row[2],
                "preferred_time": str(row[3]),
                "priority": row[4],
                "status": "waiting",
                "action": f"To cancel: POST /waitlist/{row[0]}/cancel",
            }
            for row in waitlist
        ],
        "message": (
            "No appointments or waitlist entries"
            if not appointments and not waitlist
            else "OK"
        ),
    }


# 4. CANCEL appointment — requires auth, triggers fonio if waitlist exists
@app.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    payload: CancelRequest,
    client: dict = Depends(require_client),
):
    top_candidate = None  # safe initialization

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.appointment_id, a.client_id, a.reason_of_appointment,
                       a.appointment_at, a.doctor_name, a.status, c.name, c.phone
                FROM appointments a
                JOIN clients c ON c.client_id = a.client_id
                WHERE a.appointment_id = %s;
                """,
                (appointment_id,),
            )
            appt = cur.fetchone()

            if not appt:
                raise HTTPException(
                    status_code=404, detail=f"Appointment {appointment_id} not found"
                )
            if appt[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403, detail="You can only cancel your own appointments"
                )
            if appt[5] == "cancelled":
                raise HTTPException(
                    status_code=400, detail="Appointment is already cancelled"
                )

            cur.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE appointment_id = %s;",
                (appointment_id,),
            )

            cur.execute(
                """
                SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                       w.reason_of_appointment, w.doctor_name, w.preferred_time
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE
                  AND w.doctor_name = %s
                  AND w.reason_of_appointment = %s
                ORDER BY w.priority DESC NULLS LAST, w.preferred_time ASC
                LIMIT 1;
                """,
                (appt[4], appt[2]),
            )
            top_candidate = cur.fetchone()

            if top_candidate:
                cur.execute(
                    "UPDATE waitlist_entries SET active = FALSE WHERE waitlist_id = %s;",
                    (top_candidate[0],),
                )

        conn.commit()

    if top_candidate:
        fonio_result = trigger_fonio_call(
            candidate={"name": top_candidate[2], "phone": top_candidate[3]},
            cancelled_appointment={
                "reason_of_appointment": appt[2],
                "appointment_at": str(appt[3]),
                "doctor_name": appt[4],
            },
        )
        if "error" in fonio_result:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE waitlist_entries SET active = TRUE WHERE waitlist_id = %s;",
                        (top_candidate[0],),
                    )
                conn.commit()

    return {
        "message": "Appointment cancelled successfully",
        "cancelled_appointment": {
            "appointment_id": appt[0],
            "reason_of_appointment": appt[2],
            "appointment_at": str(appt[3]),
            "doctor_name": appt[4],
        },
        "fonio_called": top_candidate is not None,
    }


# 5. CANCEL waitlist entry — requires auth
@app.post("/waitlist/{waitlist_id}/cancel")
def cancel_waitlist_entry(
    waitlist_id: int,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT waitlist_id, client_id, reason_of_appointment, doctor_name, preferred_time, active
                FROM waitlist_entries
                WHERE waitlist_id = %s;
                """,
                (waitlist_id,),
            )
            entry = cur.fetchone()

            if not entry:
                raise HTTPException(
                    status_code=404,
                    detail=f"Waitlist entry {waitlist_id} not found",
                )
            if entry[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can only cancel your own waitlist entries",
                )
            if not entry[5]:
                raise HTTPException(
                    status_code=400,
                    detail="This waitlist entry is already inactive",
                )

            cur.execute(
                "UPDATE waitlist_entries SET active = FALSE WHERE waitlist_id = %s;",
                (waitlist_id,),
            )
        conn.commit()

    return {
        "message": "Waitlist entry cancelled successfully",
        "cancelled_waitlist": {
            "waitlist_id": entry[0],
            "reason_of_appointment": entry[2],
            "doctor_name": entry[3],
            "preferred_time": str(entry[4]),
        },
    }


# 6. DELETE my account — removes client + all data via CASCADE
@app.delete("/clients/me", status_code=200)
def delete_client(
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM clients WHERE client_id = %s;",
                (client["client_id"],),
            )
        conn.commit()

    return {
        "message": f"Client '{client['name']}' and all their data deleted successfully",
        "deleted": {
            "client_id": client["client_id"],
            "name": client["name"],
            "phone": client["phone"],
        },
    }


# 7. FONIO WEBHOOK
@app.post("/webhooks/fonio", include_in_schema=False)
async def fonio_webhook(request: Request):
    data = await request.json()

    outcome = data.get("extractionData", {}).get("accepted", "unknown")
    to_number = data.get("toNumber", "")
    context = data.get("context", {})
    reason = context.get("reason", "")
    slot_time_db = context.get("slot_time_db", "")
    doctor = context.get("doctor", "")

    print(f"[FONIO] Call ended. Number: {to_number} | Outcome: {outcome}")

    if outcome == "yes":
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.waitlist_id, w.client_id, w.reason_of_appointment,
                           w.doctor_name, w.preferred_time
                    FROM waitlist_entries w
                    JOIN clients c ON c.client_id = w.client_id
                    WHERE c.phone = %s
                      AND w.active = FALSE
                      AND w.doctor_name = %s
                      AND w.reason_of_appointment = %s
                    ORDER BY w.waitlist_id DESC
                    LIMIT 1;
                    """,
                    (to_number, doctor, reason),
                )
                entry = cur.fetchone()

                if entry:
                    cur.execute(
                        """
                        INSERT INTO appointments
                            (client_id, reason_of_appointment, appointment_at, doctor_name, status)
                        VALUES (%s, %s, %s, %s, 'scheduled');
                        """,
                        (entry[1], reason, slot_time_db, doctor),
                    )
            conn.commit()

        print(f"[FONIO] Slot accepted by {to_number} — appointment booked")
        return {"status": "booked", "phone": to_number}

    elif outcome in ("no", "voicemail"):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                           w.reason_of_appointment, w.doctor_name, w.preferred_time
                    FROM waitlist_entries w
                    JOIN clients c ON c.client_id = w.client_id
                    WHERE w.active = TRUE
                      AND c.phone != %s
                      AND w.doctor_name = %s
                      AND w.reason_of_appointment = %s
                    ORDER BY w.priority DESC NULLS LAST, w.preferred_time ASC
                    LIMIT 1;
                    """,
                    (to_number, doctor, reason),
                )
                next_candidate = cur.fetchone()

                if next_candidate:
                    cur.execute(
                        "UPDATE waitlist_entries SET active = FALSE WHERE waitlist_id = %s;",
                        (next_candidate[0],),
                    )
            if next_candidate:
                conn.commit()

        if next_candidate:
            next_person = {"phone": next_candidate[3], "name": next_candidate[2]}
            fonio_result = trigger_fonio_call(
                candidate=next_person,
                cancelled_appointment={
                    "reason_of_appointment": reason,
                    "appointment_at": slot_time_db,
                    "doctor_name": doctor,
                },
            )
            if "error" in fonio_result:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE waitlist_entries SET active = TRUE WHERE waitlist_id = %s;",
                            (next_candidate[0],),
                        )
                    conn.commit()

            print(
                f"[FONIO] Moving to next: {next_person['name']} {next_person['phone']}"
            )
            return {
                "status": "calling_next_after_voicemail"
                if outcome == "voicemail"
                else "calling_next",
                "next": next_person["phone"],
            }
        else:
            print("[FONIO] No more candidates — slot remains open")
            return {"status": "no_more_candidates"}

    else:
        print(f"[FONIO] Unknown outcome: {outcome}")
        return {"status": "unknown_outcome", "raw": data}
