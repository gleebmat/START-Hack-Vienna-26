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

FONIO_API_KEY = os.environ.get("FONIO_API_KEY")
if not FONIO_API_KEY:
    raise RuntimeError("FONIO_API_KEY is not set — check your .env file")

VALID_DOCTORS = ["Dr. J Pork", "Dr. James", "Dr. Mike"]


# ── DB ─────────────────────────────────────────────────────────
def get_connection():
    return psycopg.connect(
        host="localhost",
        port=5432,
        dbname="fonio_hackathon",
        user="postgres",
        password="7007",
    )


# ── Auth helpers ───────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def require_client(credentials: HTTPBasicCredentials = Depends(security)) -> dict:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT client_id, name, phone FROM clients WHERE phone = %s AND password_hash = %s;",
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


# ── Fonio outbound call ────────────────────────────────────────
def trigger_fonio_call(candidate: dict, cancelled_appointment: dict):
    raw_time = cancelled_appointment["appointment_at"]
    try:
        human_time = datetime.strptime(
            raw_time.split(".")[0], "%Y-%m-%d %H:%M:%S"
        ).strftime("%B %d at %I:%M %p")
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
    try:
        response = httpx.post(
            "https://app.fonio.ai/api/public/v1/outbound_call",
            json=payload,
            headers={"Authorization": f"Bearer {FONIO_API_KEY}"},
            timeout=10,
        )
        print(
            f"[FONIO] Call triggered -> status {response.status_code} | {response.text}"
        )
        return response.json()
    except Exception as e:
        print(f"[FONIO] ERROR — call failed: {e}")
        return {"error": str(e)}


# ── Call log ───────────────────────────────────────────────────
def _log_call(phone: str, doctor: str, reason: str, slot_time: str, outcome: str):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT client_id FROM clients WHERE phone = %s;", (phone,))
                row = cur.fetchone()
                cur.execute(
                    "INSERT INTO call_log (client_id, phone, doctor_name, reason, slot_time, outcome) VALUES (%s, %s, %s, %s, %s, %s);",
                    (
                        row[0] if row else None,
                        phone,
                        doctor,
                        reason,
                        slot_time,
                        outcome,
                    ),
                )
            conn.commit()
    except Exception as e:
        print(f"[LOG] Failed to log call: {e}")


# ── Intelligent Dispatcher ─────────────────────────────────────
def _score_and_pick_next(
    reason: str, doctor: str, slot_time_db: str, skip_phone: str
) -> tuple:
    """
    Scores waitlist candidates and calls the best one.
    Uses only existing DB columns — no schema changes to waitlist_entries.
    Factors: priority(30) + time_match(25) + treatment_baseline(20) + contact_history(15) + fairness_by_id(10)
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT w.waitlist_id, c.client_id, c.name, c.phone,
                       w.reason_of_appointment, w.doctor_name, w.preferred_time, w.priority
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE AND c.phone != %s
                  AND w.doctor_name = %s AND w.reason_of_appointment = %s;
                """,
                (skip_phone, doctor, reason),
            )
            candidates = cur.fetchall()

            if not candidates:
                print("[FONIO] No more candidates — slot remains open")
                return "no_more_candidates", None

            phones = [c[3] for c in candidates]
            placeholders = ",".join(["%s"] * len(phones))
            cur.execute(
                f"SELECT phone, COUNT(*) FROM call_log WHERE phone IN ({placeholders}) AND doctor_name = %s AND reason = %s AND outcome != 'yes' GROUP BY phone;",
                (*phones, doctor, reason),
            )
            attempt_counts = {row[0]: row[1] for row in cur.fetchall()}
            min_wid = min(c[0] for c in candidates)
            max_wid = max(c[0] for c in candidates)

    try:
        slot_dt = datetime.strptime(slot_time_db.split(".")[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        slot_dt = None

    scored = []
    for c in candidates:
        (
            waitlist_id,
            client_id,
            name,
            phone,
            appt_reason,
            appt_doctor,
            preferred_time,
            priority,
        ) = c
        score = 0

        # Priority
        score += (priority / 3) * 30

        # Time preference match
        time_score = 0
        if slot_dt and preferred_time:
            try:
                pref_dt = (
                    preferred_time
                    if isinstance(preferred_time, datetime)
                    else datetime.strptime(
                        str(preferred_time).split(".")[0], "%Y-%m-%d %H:%M:%S"
                    )
                )
                diff_hours = abs((slot_dt - pref_dt).total_seconds()) / 3600
                if diff_hours == 0:
                    time_score = 25
                elif diff_hours <= 2:
                    time_score = 12
                elif diff_hours <= 8:
                    time_score = 6
                elif slot_dt.date() == pref_dt.date():
                    time_score = 3
            except (ValueError, TypeError):
                pass
        score += time_score

        # Treatment match baseline
        score += 20

        # Contact history
        attempts = attempt_counts.get(phone, 0)
        score += max(0, 15 - (attempts * 5))

        # Fairness via waitlist_id proxy
        id_range = max_wid - min_wid if max_wid != min_wid else 1
        score += ((max_wid - waitlist_id) / id_range) * 10

        scored.append((score, waitlist_id, name, phone))
        print(f"[SCORE] {name} ({phone}): {score:.1f} pts")

    scored.sort(key=lambda x: (-x[0], x[1]))
    best_score, best_wid, best_name, best_phone = scored[0]
    print(f"[DISPATCHER] -> {best_name} ({best_phone}) score={best_score:.1f}")

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE waitlist_entries SET active = FALSE WHERE waitlist_id = %s;",
                (best_wid,),
            )
        conn.commit()

    fonio_result = trigger_fonio_call(
        candidate={"phone": best_phone, "name": best_name},
        cancelled_appointment={
            "reason_of_appointment": reason,
            "appointment_at": slot_time_db,
            "doctor_name": doctor,
        },
    )

    if "error" in fonio_result:
        print(f"[FONIO] Call failed — re-activating {best_wid}")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE waitlist_entries SET active = TRUE WHERE waitlist_id = %s;",
                    (best_wid,),
                )
            conn.commit()
        return "fonio_error", None

    return "calling_next", best_phone


# ── Models ─────────────────────────────────────────────────────
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


@app.post("/clients", status_code=201)
def create_client(payload: NewClient):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT client_id FROM clients WHERE phone = %s;", (payload.phone,)
            )
            if cur.fetchone():
                raise HTTPException(
                    status_code=400,
                    detail=f"Phone {payload.phone} is already registered",
                )
            cur.execute(
                "INSERT INTO clients (name, phone, password_hash) VALUES (%s, %s, %s) RETURNING client_id, name, phone;",
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


@app.post("/appointments", status_code=201)
def create_appointment(payload: NewAppointment, client: dict = Depends(require_client)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT appointment_id FROM appointments WHERE appointment_at = %s AND doctor_name = %s AND status = 'scheduled';",
                (payload.appointment_at, payload.doctor_name),
            )
            conflict = cur.fetchone()

            if conflict:
                cur.execute(
                    "SELECT waitlist_id FROM waitlist_entries WHERE client_id = %s AND reason_of_appointment = %s AND doctor_name = %s AND active = TRUE;",
                    (
                        client["client_id"],
                        payload.reason_of_appointment,
                        payload.doctor_name,
                    ),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=400,
                        detail="This slot is taken and you are already on the waitlist for this treatment with this doctor.",
                    )
                cur.execute(
                    "INSERT INTO waitlist_entries (client_id, reason_of_appointment, doctor_name, preferred_time, priority, active) VALUES (%s, %s, %s, %s, %s, TRUE) RETURNING waitlist_id;",
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
                    "message": f"The slot at {payload.appointment_at} is already taken. You have been added to the waitlist. If it opens up, you will receive a call automatically.",
                }

            cur.execute(
                "INSERT INTO appointments (client_id, reason_of_appointment, appointment_at, doctor_name, status) VALUES (%s, %s, %s, %s, 'scheduled') RETURNING appointment_id, client_id, reason_of_appointment, appointment_at, doctor_name, status;",
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


@app.get("/schedule")
def get_schedule(date: str, doctor: str):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT appointment_at::text FROM appointments WHERE appointment_at::text LIKE %s AND doctor_name = %s AND status = 'scheduled';",
                (f"{date}%", doctor),
            )
            booked_times = [str(row[0]).split()[1][:5] for row in cur.fetchall()]
    return {"booked_times": booked_times}


@app.get("/doctors")
def get_doctors():
    return {"doctors": VALID_DOCTORS}


@app.get("/priorities")
def get_priorities():
    return {"priorities": [1, 2, 3]}


@app.get("/appointments/mine")
def my_appointments(client: dict = Depends(require_client)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT appointment_id, reason_of_appointment, appointment_at, doctor_name, status FROM appointments WHERE client_id = %s AND status != 'cancelled' ORDER BY appointment_at ASC;",
                (client["client_id"],),
            )
            appointments = cur.fetchall()
            cur.execute(
                "SELECT waitlist_id, reason_of_appointment, doctor_name, preferred_time, priority FROM waitlist_entries WHERE client_id = %s AND active = TRUE ORDER BY preferred_time ASC;",
                (client["client_id"],),
            )
            waitlist = cur.fetchall()
    return {
        "client_name": client["name"],
        "appointments": [
            {
                "appointment_id": r[0],
                "reason_of_appointment": r[1],
                "appointment_at": str(r[2]),
                "doctor_name": r[3],
                "status": r[4],
                "action": f"To cancel: POST /appointments/{r[0]}/cancel",
            }
            for r in appointments
        ],
        "waitlist": [
            {
                "waitlist_id": r[0],
                "reason_of_appointment": r[1],
                "doctor_name": r[2],
                "preferred_time": str(r[3]),
                "priority": r[4],
                "status": "waiting",
                "action": f"To cancel: POST /waitlist/{r[0]}/cancel",
            }
            for r in waitlist
        ],
        "message": "No appointments or waitlist entries"
        if not appointments and not waitlist
        else "OK",
    }


@app.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: int, payload: CancelRequest, client: dict = Depends(require_client)
):
    fonio_success = False

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT a.appointment_id, a.client_id, a.reason_of_appointment, a.appointment_at, a.doctor_name, a.status FROM appointments a WHERE a.appointment_id = %s;",
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
                "SELECT 1 FROM waitlist_entries WHERE active = TRUE AND doctor_name = %s AND reason_of_appointment = %s LIMIT 1;",
                (appt[4], appt[2]),
            )
            has_waitlist = cur.fetchone() is not None
        conn.commit()

    if has_waitlist:
        status_str, called_phone = _score_and_pick_next(
            reason=appt[2],
            doctor=appt[4],
            slot_time_db=str(appt[3]),
            skip_phone="__none__",
        )
        fonio_success = called_phone is not None

    return {
        "message": "Appointment cancelled successfully",
        "cancelled_appointment": {
            "appointment_id": appt[0],
            "reason_of_appointment": appt[2],
            "appointment_at": str(appt[3]),
            "doctor_name": appt[4],
        },
        "fonio_called": fonio_success,
    }


@app.post("/waitlist/{waitlist_id}/cancel")
def cancel_waitlist_entry(waitlist_id: int, client: dict = Depends(require_client)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT waitlist_id, client_id, reason_of_appointment, doctor_name, preferred_time, active FROM waitlist_entries WHERE waitlist_id = %s;",
                (waitlist_id,),
            )
            entry = cur.fetchone()
            if not entry:
                raise HTTPException(
                    status_code=404, detail=f"Waitlist entry {waitlist_id} not found"
                )
            if entry[1] != client["client_id"]:
                raise HTTPException(
                    status_code=403,
                    detail="You can only cancel your own waitlist entries",
                )
            if not entry[5]:
                raise HTTPException(
                    status_code=400, detail="This waitlist entry is already inactive"
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


@app.delete("/clients/me", status_code=200)
def delete_client(client: dict = Depends(require_client)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM clients WHERE client_id = %s;", (client["client_id"],)
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
    to_number = data.get("toNumber", "")
    context = data.get("context", {})
    reason = context.get("reason", "")
    slot_time_db = context.get("slot_time_db", "")
    doctor = context.get("doctor", "")

    outcome = data.get("extractionData", {}).get("accepted")
    if outcome is None:
        disconnect = data.get("disconnectReason", "unknown")
        outcome = {
            "dial_busy": "busy",
            "dial_no_answer": "no_answer",
            "dial_failed": "failed",
            "voicemail": "voicemail",
            "dial_cancel": "no_answer",
            "error": "failed",
            "fonio_error": "failed",
        }.get(disconnect, "unknown")
        print(f"[FONIO] accepted=None — mapped '{disconnect}' -> '{outcome}'")

    print(f"[FONIO] Call ended. Number: {to_number} | Outcome: {outcome}")
    _log_call(to_number, doctor, reason, slot_time_db, outcome)

    if outcome == "yes":
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT w.waitlist_id, w.client_id FROM waitlist_entries w JOIN clients c ON c.client_id = w.client_id WHERE c.phone = %s AND w.active = FALSE AND w.doctor_name = %s AND w.reason_of_appointment = %s ORDER BY w.waitlist_id DESC LIMIT 1;",
                    (to_number, doctor, reason),
                )
                entry = cur.fetchone()
                if entry:
                    cur.execute(
                        "INSERT INTO appointments (client_id, reason_of_appointment, appointment_at, doctor_name, status) VALUES (%s, %s, %s, %s, 'scheduled');",
                        (entry[1], reason, slot_time_db, doctor),
                    )
                else:
                    print(
                        f"[FONIO] YES but no waitlist entry for {to_number}/{doctor}/{reason} — REVIEW NEEDED"
                    )
            conn.commit()
        print(f"[FONIO] Slot accepted by {to_number} — appointment booked")
        return {"status": "booked", "phone": to_number}

    elif outcome in ("no", "voicemail"):
        status_str, next_phone = _score_and_pick_next(
            reason, doctor, slot_time_db, to_number
        )
        if next_phone:
            return {
                "status": "calling_next_after_voicemail"
                if outcome == "voicemail"
                else "calling_next",
                "next": next_phone,
            }
        return {"status": status_str}

    elif outcome == "callback":
        print(
            f"[FONIO] {to_number} requested callback — keeping in queue, calling next"
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE waitlist_entries SET active = TRUE FROM clients c WHERE waitlist_entries.client_id = c.client_id AND c.phone = %s AND waitlist_entries.doctor_name = %s AND waitlist_entries.reason_of_appointment = %s AND waitlist_entries.active = FALSE;",
                    (to_number, doctor, reason),
                )
            conn.commit()
        status_str, next_phone = _score_and_pick_next(
            reason, doctor, slot_time_db, to_number
        )
        return {
            "status": "callback_requested_calling_next",
            "callback_for": to_number,
            "next_called": next_phone,
        }

    elif outcome in ("no_answer", "busy", "failed"):
        print(f"[FONIO] '{outcome}' for {to_number} — moving to next candidate")
        status_str, next_phone = _score_and_pick_next(
            reason, doctor, slot_time_db, to_number
        )
        if next_phone:
            return {"status": f"calling_next_after_{outcome}", "next": next_phone}
        return {"status": status_str}

    else:
        print(f"[FONIO] UNKNOWN outcome: '{outcome}' — HUMAN REVIEW NEEDED\n{data}")
        return {
            "status": "unknown_outcome_needs_review",
            "outcome_received": outcome,
            "slot": slot_time_db,
            "doctor": doctor,
            "reason": reason,
            "phone": to_number,
        }


# ── Admin Auth ─────────────────────────────────────────────────
ADMIN_PHONE = os.environ.get("ADMIN_PHONE")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_PHONE or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin access only",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


# ── Admin: Live call status ────────────────────────────────────
@app.get("/admin/live")
def admin_live(admin=Depends(require_admin)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            # Active waitlist entries right now
            cur.execute(
                """
                SELECT w.waitlist_id, c.name, c.phone,
                       w.reason_of_appointment, w.doctor_name,
                       w.preferred_time, w.priority
                FROM waitlist_entries w
                JOIN clients c ON c.client_id = w.client_id
                WHERE w.active = TRUE
                ORDER BY w.priority DESC, w.preferred_time ASC;
                """
            )
            waitlist = cur.fetchall()

            # Last 20 call log entries
            cur.execute(
                """
                SELECT cl.log_id, c.name, cl.phone, cl.doctor_name,
                       cl.reason, cl.slot_time, cl.outcome, cl.logged_at
                FROM call_log cl
                LEFT JOIN clients c ON c.client_id = cl.client_id
                ORDER BY cl.logged_at DESC
                LIMIT 20;
                """
            )
            recent_calls = cur.fetchall()

            # Scheduled appointments today
            today = datetime.now().date()
            cur.execute(
                """
                SELECT a.appointment_id, c.name, c.phone,
                       a.reason_of_appointment, a.appointment_at,
                       a.doctor_name, a.status
                FROM appointments a
                JOIN clients c ON c.client_id = a.client_id
                WHERE DATE(a.appointment_at) = %s
                ORDER BY a.appointment_at ASC;
                """,
                (today,),
            )
            todays_appointments = cur.fetchall()

    return {
        "active_waitlist": [
            {
                "waitlist_id": r[0],
                "name": r[1],
                "phone": r[2],
                "reason": r[3],
                "doctor": r[4],
                "preferred_time": str(r[5]),
                "priority": r[6],
            }
            for r in waitlist
        ],
        "recent_calls": [
            {
                "log_id": r[0],
                "name": r[1] or "Unknown",
                "phone": r[2],
                "doctor": r[3],
                "reason": r[4],
                "slot_time": str(r[5]),
                "outcome": r[6],
                "logged_at": str(r[7]),
            }
            for r in recent_calls
        ],
        "todays_appointments": [
            {
                "appointment_id": r[0],
                "name": r[1],
                "phone": r[2],
                "reason": r[3],
                "appointment_at": str(r[4]),
                "doctor": r[5],
                "status": r[6],
            }
            for r in todays_appointments
        ],
    }


# ── Admin: Weekly metrics ──────────────────────────────────────
@app.get("/admin/metrics")
def admin_metrics(admin=Depends(require_admin)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            week_ago = datetime.now().date() - timedelta(days=7)

            # Total appointments this week
            cur.execute(
                "SELECT COUNT(*) FROM appointments WHERE appointment_at >= %s;",
                (week_ago,),
            )
            total_appointments = cur.fetchone()[0]

            # Recovered (waitlisted → booked via fonio)
            cur.execute(
                "SELECT COUNT(*) FROM call_log WHERE outcome = 'yes' AND logged_at >= %s;",
                (week_ago,),
            )
            recovered = cur.fetchone()[0]

            # Rebooking rate = recovered / total cancelled this week
            cur.execute(
                "SELECT COUNT(*) FROM appointments WHERE status = 'cancelled' AND appointment_at >= %s;",
                (week_ago,),
            )
            cancelled = cur.fetchone()[0]
            rebooking_rate = (
                round((recovered / cancelled * 100), 1) if cancelled > 0 else 0.0
            )

            # Revenue recovered (assume €80 per recovered appointment)
            revenue_per_slot = 80
            revenue_recovered = recovered * revenue_per_slot

            # Avg attempts per slot = total calls / unique slots called
            cur.execute(
                """
                SELECT slot_time, doctor_name, reason, COUNT(*) as attempts
                FROM call_log
                WHERE logged_at >= %s
                GROUP BY slot_time, doctor_name, reason;
                """,
                (week_ago,),
            )
            slot_rows = cur.fetchall()
            total_calls = sum(r[3] for r in slot_rows)
            avg_attempts = round(total_calls / len(slot_rows), 2) if slot_rows else 0.0

            # Outcomes breakdown
            cur.execute(
                """
                SELECT outcome, COUNT(*) FROM call_log
                WHERE logged_at >= %s
                GROUP BY outcome ORDER BY COUNT(*) DESC;
                """,
                (week_ago,),
            )
            outcomes = {r[0]: r[1] for r in cur.fetchall()}

            # Results by reason (top reasons + their accept rate)
            cur.execute(
                """
                SELECT reason,
                       COUNT(*) as total_calls,
                       SUM(CASE WHEN outcome = 'yes' THEN 1 ELSE 0 END) as accepted
                FROM call_log
                WHERE logged_at >= %s
                GROUP BY reason
                ORDER BY total_calls DESC;
                """,
                (week_ago,),
            )
            by_reason = [
                {
                    "reason": r[0],
                    "total_calls": r[1],
                    "accepted": r[2],
                    "accept_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0.0,
                }
                for r in cur.fetchall()
            ]

            # Results by doctor
            cur.execute(
                """
                SELECT doctor_name,
                       COUNT(*) as total_calls,
                       SUM(CASE WHEN outcome = 'yes' THEN 1 ELSE 0 END) as accepted
                FROM call_log
                WHERE logged_at >= %s
                GROUP BY doctor_name
                ORDER BY total_calls DESC;
                """,
                (week_ago,),
            )
            by_doctor = [
                {
                    "doctor": r[0],
                    "total_calls": r[1],
                    "accepted": r[2],
                    "accept_rate": round(r[2] / r[1] * 100, 1) if r[1] > 0 else 0.0,
                }
                for r in cur.fetchall()
            ]

    return {
        "period": f"{week_ago} to {datetime.now().date()}",
        "total_appointments": total_appointments,
        "cancelled": cancelled,
        "recovered": recovered,
        "rebooking_rate_pct": rebooking_rate,
        "revenue_recovered_eur": revenue_recovered,
        "avg_attempts_per_slot": avg_attempts,
        "outcomes_breakdown": outcomes,
        "by_reason": by_reason,
        "by_doctor": by_doctor,
    }


# ── Admin: Override — manually trigger call for a slot ─────────
@app.post("/admin/override/call")
def admin_override_call(
    doctor_name: str,
    reason_of_appointment: str,
    appointment_at: str,
    admin=Depends(require_admin),
):
    status_str, called_phone = _score_and_pick_next(
        reason=reason_of_appointment,
        doctor=doctor_name,
        slot_time_db=appointment_at,
        skip_phone="__none__",
    )
    return {"status": status_str, "called": called_phone}


# ── Admin: List all appointments (any status) ──────────────────
@app.get("/admin/appointments")
def admin_all_appointments(admin=Depends(require_admin)):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.appointment_id, c.name, c.phone,
                       a.reason_of_appointment, a.appointment_at,
                       a.doctor_name, a.status
                FROM appointments a
                JOIN clients c ON c.client_id = a.client_id
                ORDER BY a.appointment_at DESC
                LIMIT 100;
                """
            )
            rows = cur.fetchall()
    return {
        "appointments": [
            {
                "appointment_id": r[0],
                "name": r[1],
                "phone": r[2],
                "reason": r[3],
                "appointment_at": str(r[4]),
                "doctor": r[5],
                "status": r[6],
            }
            for r in rows
        ]
    }
