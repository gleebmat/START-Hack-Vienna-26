import reflex as rx
import requests
from datetime import datetime
import os

from dotenv import load_dotenv
load_dotenv()

from typing import TypedDict

API_URL = "http://127.0.0.1:8080"

PALETTE_DARK = "#354f36"
PALETTE_MID = "#6a8569"
PALETTE_LIGHT = "#b8ceb7"
PALETTE_PALEST = "#dae6d9"
TEXT_DARK = "#182418"


class AppointmentItem(TypedDict):
    appointment_id: int
    name: str
    phone: str
    reason: str
    appointment_at: str
    doctor: str
    status: str


class WaitlistItem(TypedDict):
    waitlist_id: int
    name: str
    phone: str
    reason: str
    doctor: str
    preferred_time: str
    priority: int


class CallLogItem(TypedDict):
    log_id: int
    name: str
    phone: str
    doctor: str
    reason: str
    slot_time: str
    outcome: str
    logged_at: str


class ByReasonItem(TypedDict):
    reason: str
    total_calls: int
    accepted: int
    accept_rate: float


class ByDoctorItem(TypedDict):
    doctor: str
    total_calls: int
    accepted: int
    accept_rate: float


class AdminState(rx.State):
    is_logged_in: bool = False
    admin_input_phone: str = ""
    admin_input_password: str = ""
    recovered: int = 0
    rebooking_rate_pct: float = 0.0
    revenue_recovered_eur: int = 0
    avg_attempts_per_slot: float = 0.0
    total_appointments: int = 0
    cancelled: int = 0
    period: str = ""

    # Live data
    active_waitlist: list[WaitlistItem] = []
    recent_calls: list[CallLogItem] = []
    todays_appointments: list[AppointmentItem] = []
    by_reason: list[ByReasonItem] = []
    by_doctor: list[ByDoctorItem] = []

    last_refreshed: str = ""

    def set_admin_phone(self, v: str):
        self.admin_input_phone = v

    def set_admin_password(self, v: str):
        self.admin_input_password = v

    def login(self):
        if (
            self.admin_input_phone == os.getenv("ADMIN_PHONE")
            and self.admin_input_password == os.getenv("ADMIN_PASSWORD")
        ):
            self.is_logged_in = True
            self.refresh()
        else:
            return rx.window_alert("Invalid admin credentials.")

    def logout(self):
        self.is_logged_in = False

    def refresh(self):
        try:
            live = requests.get(
                f"{API_URL}/admin/live",
                auth=(os.getenv("ADMIN_PHONE"), os.getenv("ADMIN_PASSWORD")),
                timeout=5,
            ).json()
            self.active_waitlist = live.get("active_waitlist", [])
            self.recent_calls = live.get("recent_calls", [])
            self.todays_appointments = live.get("todays_appointments", [])

            m = requests.get(
                f"{API_URL}/admin/metrics",
                auth=(os.getenv("ADMIN_PHONE"), os.getenv("ADMIN_PASSWORD")),
                timeout=5,
            ).json()
            self.recovered = m.get("recovered", 0)
            self.rebooking_rate_pct = m.get("rebooking_rate_pct", 0.0)
            self.revenue_recovered_eur = m.get("revenue_recovered_eur", 0)
            self.avg_attempts_per_slot = m.get("avg_attempts_per_slot", 0.0)
            self.total_appointments = m.get("total_appointments", 0)
            self.cancelled = m.get("cancelled", 0)
            self.period = m.get("period", "")
            self.by_reason = m.get("by_reason", [])
            self.by_doctor = m.get("by_doctor", [])
            self.last_refreshed = datetime.now().strftime("%H:%M:%S")
        except Exception as e:
            return rx.window_alert(f"Error loading data: {e}")


# ── UI helpers ─────────────────────────────────────────────────
def kpi_card(label: str, value) -> rx.Component:
    return rx.box(
        rx.text(
            label,
            font_size="0.75rem",
            color=PALETTE_MID,
            font_weight="600",
            text_transform="uppercase",
            letter_spacing="0.08em",
        ),
        rx.text(
            value,
            font_size="2rem",
            font_weight="800",
            color=PALETTE_DARK,
            margin_top="0.25em",
        ),
        bg="white",
        border_radius="16px",
        padding="1.5em",
        box_shadow="0 4px 20px rgba(53,79,54,0.12)",
        flex="1",
        min_width="160px",
    )


def outcome_badge(outcome: str) -> rx.Component:
    color_map = {
        "yes": ("#e6f4ea", "#2d7a3a"),
        "no": ("#fdecea", "#c0392b"),
        "voicemail": ("#fff8e1", "#a0740a"),
        "no_answer": ("#f3f3f3", "#555"),
        "busy": ("#fff0e6", "#c05a00"),
        "failed": ("#fdecea", "#c0392b"),
        "callback": ("#e8eaf6", "#3949ab"),
    }
    bg, fg = color_map.get(outcome, ("#f3f3f3", "#555"))
    return rx.box(
        rx.text(outcome, font_size="0.7rem", font_weight="700", color=fg),
        bg=bg,
        border_radius="999px",
        padding="0.2em 0.7em",
        display="inline-block",
    )


def section_title(text: str) -> rx.Component:
    return rx.text(
        text,
        font_size="1rem",
        font_weight="700",
        color=PALETTE_DARK,
        margin_bottom="0.75em",
        margin_top="1.5em",
    )


# ── Login page ─────────────────────────────────────────────────
def admin_login() -> rx.Component:
    return rx.center(
        rx.box(
            rx.text(
                "🦷 Clinic Admin",
                font_size="1.5rem",
                font_weight="800",
                color=PALETTE_DARK,
                text_align="center",
                margin_bottom="1.5em",
            ),
            rx.input(
                placeholder="Admin username",
                on_change=AdminState.set_admin_phone,
                margin_bottom="0.75em",
                width="100%",
            ),
            rx.input(
                placeholder="Password",
                type_="password",
                on_change=AdminState.set_admin_password,
                margin_bottom="1em",
                width="100%",
            ),
            rx.button(
                "Login",
                on_click=AdminState.login,
                width="100%",
                bg=PALETTE_DARK,
                color="white",
                border_radius="10px",
                padding="0.75em",
                font_weight="700",
            ),
            bg="white",
            border_radius="20px",
            padding="2.5em",
            box_shadow="0 8px 40px rgba(53,79,54,0.18)",
            width="360px",
        ),
        height="100vh",
        bg=PALETTE_PALEST,
    )


# ── Dashboard ──────────────────────────────────────────────────
def admin_dashboard() -> rx.Component:
    return rx.box(
        # Header
        rx.flex(
            rx.text(
                "🦷 Operator's Cockpit",
                font_size="1.4rem",
                font_weight="800",
                color=PALETTE_DARK,
            ),
            rx.flex(
                rx.text(f"Refreshed: ", font_size="0.8rem", color=PALETTE_MID),
                rx.text(
                    AdminState.last_refreshed, font_size="0.8rem", color=PALETTE_MID
                ),
                rx.button(
                    "↻ Refresh",
                    on_click=AdminState.refresh,
                    bg=PALETTE_MID,
                    color="white",
                    border_radius="8px",
                    padding="0.4em 1em",
                    font_size="0.8rem",
                    margin_left="1em",
                ),
                rx.button(
                    "Logout",
                    on_click=AdminState.logout,
                    bg="white",
                    color=PALETTE_DARK,
                    border="1px solid #ccc",
                    border_radius="8px",
                    padding="0.4em 1em",
                    font_size="0.8rem",
                    margin_left="0.5em",
                ),
                align="center",
            ),
            justify="between",
            align="center",
            padding="1em 2em",
            bg="white",
            box_shadow="0 2px 12px rgba(53,79,54,0.08)",
            position="sticky",
            top="0",
            z_index="100",
        ),
        rx.box(
            # KPI Row
            section_title("Weekly Metrics"),
            rx.flex(
                kpi_card("Recovered Slots", AdminState.recovered),
                kpi_card("Rebooking Rate %", AdminState.rebooking_rate_pct),
                kpi_card("Revenue Recovered €", AdminState.revenue_recovered_eur),
                kpi_card("Avg Attempts / Slot", AdminState.avg_attempts_per_slot),
                kpi_card("Total Appointments", AdminState.total_appointments),
                kpi_card("Cancelled", AdminState.cancelled),
                gap="1em",
                flex_wrap="wrap",
            ),
            # Today's appointments
            section_title("Today's Appointments"),
            rx.box(
                rx.foreach(
                    AdminState.todays_appointments,
                    lambda r: rx.flex(
                        rx.text(
                            r["appointment_at"],
                            font_weight="700",
                            color=PALETTE_DARK,
                            width="60px",
                            font_size="0.85rem",
                        ),
                        rx.text(
                            r["name"],
                            font_size="0.85rem",
                            color=TEXT_DARK,
                            width="140px",
                        ),
                        rx.text(
                            r["reason"], font_size="0.8rem", color=PALETTE_MID, flex="1"
                        ),
                        rx.text(
                            r["doctor"],
                            font_size="0.8rem",
                            color=PALETTE_MID,
                            width="120px",
                        ),
                        rx.box(
                            rx.text(
                                r["status"],
                                font_size="0.7rem",
                                font_weight="700",
                                color=rx.cond(
                                    r["status"] == "scheduled", "#2d7a3a", "#c0392b"
                                ),
                            ),
                            bg=rx.cond(
                                r["status"] == "scheduled", "#e6f4ea", "#fdecea"
                            ),
                            border_radius="999px",
                            padding="0.2em 0.6em",
                        ),
                        gap="1em",
                        align="center",
                        padding="0.6em 1em",
                        border_bottom="1px solid #eee",
                        _hover={"bg": "#f8fdf8"},
                    ),
                ),
                bg="white",
                border_radius="16px",
                box_shadow="0 4px 20px rgba(53,79,54,0.08)",
                overflow="hidden",
            ),
            # Active Waitlist
            section_title("Active Waitlist"),
            rx.box(
                rx.foreach(
                    AdminState.active_waitlist,
                    lambda r: rx.flex(
                        rx.box(
                            rx.text(
                                f"P{r['priority']}",
                                font_size="0.7rem",
                                font_weight="800",
                                color=rx.cond(
                                    r["priority"] == 3,
                                    "#c0392b",
                                    rx.cond(r["priority"] == 2, "#a0740a", PALETTE_MID),
                                ),
                            ),
                            bg=rx.cond(
                                r["priority"] == 3,
                                "#fdecea",
                                rx.cond(r["priority"] == 2, "#fff8e1", PALETTE_PALEST),
                            ),
                            border_radius="999px",
                            padding="0.2em 0.6em",
                            width="36px",
                            text_align="center",
                        ),
                        rx.text(
                            r["name"],
                            font_size="0.85rem",
                            color=TEXT_DARK,
                            width="140px",
                            font_weight="600",
                        ),
                        rx.text(
                            r["reason"], font_size="0.8rem", color=PALETTE_MID, flex="1"
                        ),
                        rx.text(
                            r["doctor"],
                            font_size="0.8rem",
                            color=PALETTE_MID,
                            width="120px",
                        ),
                        rx.text(
                            r["preferred_time"],
                            font_size="0.75rem",
                            color=PALETTE_MID,
                            width="140px",
                        ),
                        gap="1em",
                        align="center",
                        padding="0.6em 1em",
                        border_bottom="1px solid #eee",
                        _hover={"bg": "#f8fdf8"},
                    ),
                ),
                bg="white",
                border_radius="16px",
                box_shadow="0 4px 20px rgba(53,79,54,0.08)",
                overflow="hidden",
            ),
            # Recent Calls
            section_title("Recent Call Log"),
            rx.box(
                rx.foreach(
                    AdminState.recent_calls,
                    lambda r: rx.flex(
                        rx.text(
                            r["logged_at"][11:19],
                            font_size="0.75rem",
                            color=PALETTE_MID,
                            width="70px",
                        ),
                        rx.text(
                            r["name"],
                            font_size="0.85rem",
                            color=TEXT_DARK,
                            width="130px",
                        ),
                        rx.text(
                            r["reason"], font_size="0.8rem", color=PALETTE_MID, flex="1"
                        ),
                        rx.text(
                            r["doctor"],
                            font_size="0.8rem",
                            color=PALETTE_MID,
                            width="120px",
                        ),
                        outcome_badge(r["outcome"]),
                        gap="1em",
                        align="center",
                        padding="0.6em 1em",
                        border_bottom="1px solid #eee",
                        _hover={"bg": "#f8fdf8"},
                    ),
                ),
                bg="white",
                border_radius="16px",
                box_shadow="0 4px 20px rgba(53,79,54,0.08)",
                overflow="hidden",
            ),
            # By Reason & By Doctor
            rx.flex(
                rx.box(
                    section_title("Results by Reason"),
                    rx.box(
                        rx.foreach(
                            AdminState.by_reason,
                            lambda r: rx.flex(
                                rx.text(
                                    r["reason"],
                                    font_size="0.8rem",
                                    color=TEXT_DARK,
                                    flex="1",
                                ),
                                rx.text(
                                    r["total_calls"].to_string() + " calls",
                                    font_size="0.75rem",
                                    color=PALETTE_MID,
                                    width="70px",
                                ),
                                rx.text(
                                    r["accept_rate"].to_string() + "%",
                                    font_size="0.8rem",
                                    font_weight="700",
                                    color=rx.cond(
                                        r["accept_rate"] >= 50, "#2d7a3a", "#c0392b"
                                    ),
                                    width="50px",
                                ),
                                gap="0.5em",
                                align="center",
                                padding="0.5em 1em",
                                border_bottom="1px solid #eee",
                            ),
                        ),
                        bg="white",
                        border_radius="16px",
                        box_shadow="0 4px 20px rgba(53,79,54,0.08)",
                        overflow="hidden",
                    ),
                    flex="1",
                ),
                rx.box(
                    section_title("Results by Doctor"),
                    rx.box(
                        rx.foreach(
                            AdminState.by_doctor,
                            lambda r: rx.flex(
                                rx.text(
                                    r["doctor"],
                                    font_size="0.8rem",
                                    color=TEXT_DARK,
                                    flex="1",
                                ),
                                rx.text(
                                    r["total_calls"].to_string() + " calls",
                                    font_size="0.75rem",
                                    color=PALETTE_MID,
                                    width="70px",
                                ),
                                rx.text(
                                    r["accept_rate"].to_string() + "%",
                                    font_size="0.8rem",
                                    font_weight="700",
                                    color=rx.cond(
                                        r["accept_rate"] >= 50, "#2d7a3a", "#c0392b"
                                    ),
                                    width="50px",
                                ),
                                gap="0.5em",
                                align="center",
                                padding="0.5em 1em",
                                border_bottom="1px solid #eee",
                            ),
                        ),
                        bg="white",
                        border_radius="16px",
                        box_shadow="0 4px 20px rgba(53,79,54,0.08)",
                        overflow="hidden",
                    ),
                    flex="1",
                ),
                gap="1.5em",
                flex_wrap="wrap",
            ),
            padding="1.5em 2em",
            max_width="1400px",
            margin="0 auto",
        ),
        bg=PALETTE_PALEST,
        min_height="100vh",
    )


def admin_page() -> rx.Component:
    return rx.cond(
        AdminState.is_logged_in,
        admin_dashboard(),
        admin_login(),
    )
