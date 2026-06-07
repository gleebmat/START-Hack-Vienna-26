from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, field_validator
from typing import Optional
import psycopg
import secrets
import hashlib


app = FastAPI(title="Dental clinic system")
security = HTTPBasic()

# ── Request models ─────────────────────────────────────────────
class NewWaitlistEntry(BaseModel):
    reason_of_appointment: str
    preferred_time: str

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


# ── Auth: HTTP Basic — username=phone, password=their password ─
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


# ── Request models ─────────────────────────────────────────────
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


class NewAppointment(BaseModel):
    reason_of_appointment: str
    appointment_at: str

    @field_validator("appointment_at")
    @classmethod
    def valid_datetime(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(
                'appointment_at must be format "YYYY-MM-DD HH:MM:SS", e.g. "2026-06-10 14:00:00"'
            )
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
                INSERT INTO appointments
                    (client_id, reason_of_appointment, appointment_at, status)
                VALUES (%s, %s, %s, 'scheduled')
                RETURNING appointment_id, client_id,
                          reason_of_appointment, appointment_at, status;
                """,
                (
                    client["client_id"],
                    payload.reason_of_appointment,
                    payload.appointment_at,
                ),
            )
            row = cur.fetchone()
        conn.commit()

    return {
        "appointment_id": row[0],
        "client_id": row[1],
        "client_name": client["name"],
        "reason_of_appointment": row[2],
        "appointment_at": str(row[3]),
        "status": row[4],
        "message": "Appointment created successfully",
    }


# 3. CREATE waitlist entry — requires auth
@app.get("/appointments/mine")
def my_appointments(
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Fetch scheduled appointments
            cur.execute(
                """
                SELECT appointment_id, reason_of_appointment, appointment_at, status
                FROM appointments
                WHERE client_id = %s
                  AND status != 'cancelled'
                ORDER BY appointment_at ASC;
                """,
                (client["client_id"],),
            )
            appt_rows = cur.fetchall()

            # Fetch active waitlist entries
            cur.execute(
                """
                SELECT waitlist_id, reason_of_appointment, preferred_time
                FROM waitlist_entries
                WHERE client_id = %s
                  AND active = TRUE
                ORDER BY preferred_time ASC;
                """,
                (client["client_id"],),
            )
            wait_rows = cur.fetchall()

    # Format standard appointments
    appointments = [
        {
            "appointment_id": row[0],
            "reason_of_appointment": row[1],
            "appointment_at": str(row[2]),
            "status": row[3],
            "action": f"To cancel: POST /appointments/{row[0]}/cancel",
        }
        for row in appt_rows
    ]

    # Format waitlist entries
    waitlist = [
        {
            "waitlist_id": row[0],
            "reason_of_appointment": row[1],
            "preferred_time": str(row[2]),
            "action": f"To cancel: POST /waitlist/{row[0]}/cancel",
        }
        for row in wait_rows
    ]

    return {
        "client_name": client["name"],
        "appointments": appointments,
        "waitlist": waitlist,
        "message": "Fetched data successfully."
    }

# 4. CANCEL appointment — requires auth, only your own
@app.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int,
    payload: CancelRequest,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.appointment_id, a.client_id, a.reason_of_appointment,
                       a.appointment_at, a.status, c.name, c.phone
                FROM appointments a
                JOIN clients c ON c.client_id = a.client_id
                WHERE a.appointment_id = %s;
                """,
                (appointment_id,),
            )
            appt = cur.fetchone()

            if not appt:
                raise HTTPException(
                    status_code=404,
                    detail=f"Appointment {appointment_id} not found",
                )
            if appt[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can only cancel your own appointments",
                )
            if appt[4] == "cancelled":
                raise HTTPException(
                    status_code=400,
                    detail="Appointment is already cancelled",
                )

            cur.execute(
                "UPDATE appointments SET status = 'cancelled' WHERE appointment_id = %s;",
                (appointment_id,),
            )

            cur.execute(
                """
                SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                       w.reason_of_appointment, w.preferred_time
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.reason_of_appointment = %s
                  AND w.active = TRUE
                ORDER BY w.waitlist_id ASC;
                """,
                (appt[2],),
            )
            waitlist = cur.fetchall()

        conn.commit()

    candidates = [
        {
            "waitlist_id": row[0],
            "client_id": row[1],
            "name": row[2],
            "phone": row[3],
            "reason_of_appointment": row[4],
            "preferred_time": row[5],
        }
        for row in waitlist
    ]

    return {
        "message": "Appointment cancelled",
        "cancelled_appointment": {
            "appointment_id": appt[0],
            "client_id": appt[1],
            "client_name": appt[5],
            "reason_of_appointment": appt[2],
            "appointment_at": str(appt[3]),
        },
        "waitlist_candidates": candidates,
        "next_to_call": candidates[0] if candidates else None,
    }


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

@app.get("/schedule")
def get_daily_schedule(date: str, doctor: str = ""):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT appointment_at FROM appointments
                WHERE DATE(appointment_at) = %s
                  AND status = 'scheduled'
                  AND (%s = '' OR doctor_name = %s);
                """,
                (date, doctor, doctor)
            )
            rows = cur.fetchall()
    return {"booked_times": [row[0].strftime("%H:%M") for row in rows]}

# 5. JOIN WAITLIST — requires auth
@app.post("/waitlist", status_code=201)
def join_waitlist(
    payload: NewWaitlistEntry,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO waitlist_entries 
                    (client_id, reason_of_appointment, preferred_time, active)
                VALUES (%s, %s, %s, TRUE)
                RETURNING waitlist_id;
                """,
                (
                    client["client_id"],
                    payload.reason_of_appointment,
                    payload.preferred_time,
                ),
            )
        conn.commit()

    return {
        "message": "Successfully added to waitlist",
        "client_name": client["name"],
        "preferred_time": payload.preferred_time
    }

# 6. CANCEL WAITLIST ENTRY — requires auth, only your own
@app.post("/waitlist/{waitlist_id}/cancel")
def cancel_waitlist(
    waitlist_id: int,
    payload: CancelRequest,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT waitlist_id, client_id, active
                FROM waitlist_entries
                WHERE waitlist_id = %s;
                """,
                (waitlist_id,),
            )
            wait_entry = cur.fetchone()

            if not wait_entry:
                raise HTTPException(
                    status_code=404, 
                    detail=f"Waitlist entry {waitlist_id} not found"
                )
            if wait_entry[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403, 
                    detail="You can only cancel your own waitlist entries"
                )
            if not wait_entry[2]: # active == False
                raise HTTPException(
                    status_code=400, 
                    detail="Waitlist entry is already cancelled or inactive"
                )

            # Mark as inactive instead of deleting to keep a history
            cur.execute(
                "UPDATE waitlist_entries SET active = FALSE WHERE waitlist_id = %s;",
                (waitlist_id,)
            )
        conn.commit()

    return {"message": "Waitlist entry cancelled successfully"}