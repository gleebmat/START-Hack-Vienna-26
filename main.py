from datetime import datetime, timedelta
import os
from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, field_validator
from typing import Optional
import psycopg
import hashlib
import httpx

app = FastAPI(title="Dental clinic system")
security = HTTPBasic()


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


def trigger_fonio_call(candidate: dict, cancelled_appointment: dict):
    payload = {
        "fromNumber": "+436767563950",
        "toNumber": candidate["phone"],
        "agentId": "fa1f00ba-96fd-4a5e-afb5-4f7f4f679103",
        "context": {
            "patient_name": candidate["name"],
            "reason": cancelled_appointment["reason_of_appointment"],
            "slot_time": cancelled_appointment["appointment_at"],
        },
    }
    try:
        response = httpx.post(
            "https://app.fonio.ai/api/public/v1/outbound_call",
            json=payload,
            headers={"Authorization": "Bearer fonio_a3d622e6f5ebafbd4598e6d70c7b97f8"},
            timeout=10,
        )
        print(
            f"[FONIO] Call triggered → status {response.status_code} | {response.text}"
        )
        return response.json()
    except Exception as e:
        print(f"[FONIO] ERROR — call failed: {e}")
        return {"error": str(e)}


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
            dt = datetime.strptime(v, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            raise ValueError(
                'appointment_at must be format "YYYY-MM-DD HH:MM:SS", e.g. "2026-06-10 14:00:00"'
            )
        if dt < datetime.now() + timedelta(hours=1):
            raise ValueError("Appointment must be booked at least 1 hour from now")
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
            # check if slot is already taken
            cur.execute(
                """
                SELECT appointment_id FROM appointments
                WHERE appointment_at = %s
                  AND status = 'scheduled';
                """,
                (payload.appointment_at,),
            )
            conflict = cur.fetchone()

            if conflict:
                # slot is busy — check if already on waitlist for this treatment
                cur.execute(
                    """
                    SELECT waitlist_id FROM waitlist_entries
                    WHERE client_id = %s
                      AND reason_of_appointment = %s
                      AND active = TRUE;
                    """,
                    (client["client_id"], payload.reason_of_appointment),
                )
                already_waiting = cur.fetchone()

                if already_waiting:
                    raise HTTPException(
                        status_code=400,
                        detail="This slot is taken and you are already on the waitlist for this treatment.",
                    )

                # add to waitlist
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
                        str(
                            payload.appointment_at
                        ),  # store their preferred time as a note
                    ),
                )
                waitlist_row = cur.fetchone()
                conn.commit()

                return {
                    "status": "waitlisted",
                    "waitlist_id": waitlist_row[0],
                    "client_name": client["name"],
                    "reason_of_appointment": payload.reason_of_appointment,
                    "preferred_time": payload.appointment_at,
                    "message": (
                        f"The slot at {payload.appointment_at} is already taken. "
                        "You have been added to the waitlist. "
                        "If it opens up, you will receive a call automatically."
                    ),
                }

            # slot is free — book it normally
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
        "status": "booked",
        "appointment_id": row[0],
        "client_id": row[1],
        "client_name": client["name"],
        "reason_of_appointment": row[2],
        "appointment_at": str(row[3]),
        "appointment_status": row[4],
        "message": "Appointment created successfully",
    }


# 3. LIST my active appointments — requires auth
@app.get("/appointments/mine")
def my_appointments(
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Regular appointments
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
            appointments = cur.fetchall()

            # Waitlist entries
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
            waitlist = cur.fetchall()

    return {
        "client_name": client["name"],
        "appointments": [
            {
                "appointment_id": row[0],
                "reason_of_appointment": row[1],
                "appointment_at": str(row[2]),
                "status": row[3],
                "action": f"To cancel: POST /appointments/{row[0]}/cancel",
            }
            for row in appointments
        ],
        "waitlist": [
            {
                "waitlist_id": row[0],
                "reason_of_appointment": row[1],
                "preferred_time": str(row[2]),
                "status": "waiting",
                "action": f"To cancel: POST /waitlist/{row[0]}/cancel",  # ← add this
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
                    status_code=404, detail=f"Appointment {appointment_id} not found"
                )
            if appt[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403, detail="You can only cancel your own appointments"
                )
            if appt[4] == "cancelled":
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
                    w.reason_of_appointment, w.preferred_time
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE
                ORDER BY w.preferred_time ASC
                LIMIT 1;
                """,
            )
            top_candidate = cur.fetchone()

        conn.commit()

    if top_candidate:
        trigger_fonio_call(
            candidate={"name": top_candidate[2], "phone": top_candidate[3]},
            cancelled_appointment={
                "reason_of_appointment": appt[2],
                "appointment_at": str(appt[3]),
            },
        )

    return {
        "message": "Appointment cancelled successfully",
        "cancelled_appointment": {
            "appointment_id": appt[0],
            "reason_of_appointment": appt[2],
            "appointment_at": str(appt[3]),
        },
    }


@app.post("/waitlist/{waitlist_id}/cancel")
def cancel_waitlist_entry(
    waitlist_id: int,
    client: dict = Depends(require_client),
):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT waitlist_id, client_id, reason_of_appointment, preferred_time, active
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
            if not entry[4]:
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
            "preferred_time": str(entry[3]),
        },
    }


# 5. DELETE my account — removes client + all data via CASCADE
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


@app.post("/webhooks/fonio", include_in_schema=False)
async def fonio_webhook(request: Request):
    data = await request.json()

    # extract what fonio found from the conversation
    outcome = data.get("extractionData", {}).get("accepted", "unknown")
    to_number = data.get("toNumber", "")
    context = data.get("context", {})

    reason = context.get("reason", "")
    slot_time = context.get("slot_time", "")

    print(f"[FONIO] Call ended. Number: {to_number} | Outcome: {outcome}")

    if outcome == "yes":
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT w.client_id, w.reason_of_appointment, w.preferred_time
                    FROM waitlist_entries w
                    JOIN clients c ON c.client_id = w.client_id
                    WHERE c.phone = %s AND w.active = TRUE
                    ORDER BY w.preferred_time ASC
                    LIMIT 1;
                    """,
                    (to_number,),
                )
                entry = cur.fetchone()

                if entry:
                    cur.execute(
                        "UPDATE waitlist_entries SET active = FALSE WHERE client_id = %s AND active = TRUE;",
                        (entry[0],),
                    )
                    cur.execute(
                        """
                        INSERT INTO appointments (client_id, reason_of_appointment, appointment_at, status)
                        VALUES (%s, %s, %s, 'scheduled');
                        """,
                        (entry[0], entry[1], entry[2]),
                    )
            conn.commit()  # ← outside the cursor block, inside the connection block

        print(
            f"[FONIO] Slot accepted by {to_number} — waitlist entry deactivated and appointment booked"
        )
        return {
            "status": "booked",
            "phone": to_number,
        }  # ← outside the connection block entirely

    elif outcome == "no":
        # patient declined — find next active candidate and call them
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                    w.reason_of_appointment, w.preferred_time
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE
                AND c.phone != %s
                ORDER BY w.preferred_time ASC
                LIMIT 1;
                """,
                    (to_number,),
                )
                next_candidate = cur.fetchone()

        if next_candidate:
            next_person = {
                "phone": next_candidate[3],
                "name": next_candidate[2],
            }
            trigger_fonio_call(
                candidate=next_person,
                cancelled_appointment={
                    "reason_of_appointment": reason,
                    "appointment_at": slot_time,
                },
            )
            print(
                f"[FONIO] Moving to next candidate: {next_person['name']} {next_person['phone']}"
            )
            return {"status": "calling_next", "next": next_person["phone"]}
        else:
            print("[FONIO] No more candidates on waitlist — slot remains open")
            return {"status": "no_more_candidates"}

    elif outcome == "voicemail":
        print(f"[FONIO] Reached voicemail for {to_number} — moving to next")
        # same logic as "no" — call next person
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                    w.reason_of_appointment, w.preferred_time
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE
                AND c.phone != %s
                ORDER BY w.preferred_time ASC
                LIMIT 1;
                """,
                    (to_number,),
                )
                next_candidate = cur.fetchone()

        if next_candidate:
            next_person = {
                "phone": next_candidate[3],
                "name": next_candidate[2],
            }
            trigger_fonio_call(
                candidate=next_person,
                cancelled_appointment={
                    "reason_of_appointment": reason,
                    "appointment_at": slot_time,
                },
            )
            return {
                "status": "calling_next_after_voicemail",
                "next": next_person["phone"],
            }
        else:
            return {"status": "no_more_candidates"}

    else:
        print(f"[FONIO] Unknown outcome: {outcome}")
        return {"status": "unknown_outcome", "raw": data}
