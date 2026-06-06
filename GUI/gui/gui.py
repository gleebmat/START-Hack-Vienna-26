import reflex as rx
import requests
import calendar
from datetime import datetime, timedelta

# API URL
API_URL = "http://127.0.0.1:8080"

# --- Green Color Palette ---
PALETTE_DARK = "#354f36"       
PALETTE_MID_DARK = "#526b51"
PALETTE_MID = "#6a8569"
PALETTE_MID_LIGHT = "#94b093"  
PALETTE_LIGHT = "#b8ceb7"
PALETTE_PALEST = "#dae6d9"

# Styling variables 
SOFT_SHADOW = "0 10px 25px -5px rgba(53, 79, 54, 0.15), 0 8px 10px -6px rgba(53, 79, 54, 0.1)"
HOVER_SHADOW = "0 25px 30px -5px rgba(53, 79, 54, 0.25), 0 15px 15px -5px rgba(53, 79, 54, 0.15)"
CARD_SHADOW = "0 30px 60px -15px rgba(20, 30, 20, 0.5)" 

ACTIVE_GREEN = PALETTE_MID_LIGHT
ACTIVE_TEXT = PALETTE_DARK
INPUT_BG = "rgba(255, 255, 255, 0.6)" 
TEXT_DARK = "#182418"          
TEXT_LIGHT = PALETTE_MID_DARK
SOFT_YELLOW = "#e6d783"        
DARK_YELLOW = "#8f6b00"

# --- Animation & Interactive Styles ---
# --- Animation & Interactive Styles ---
GLOBAL_STYLE = {
    "input::placeholder": {
        "color": f"{PALETTE_MID_DARK} !important",
        "opacity": "0.7 !important",
    },
    "@keyframes fadeUp": {
        "0%": {"opacity": "0", "transform": "translateY(30px)"},
        "100%": {"opacity": "1", "transform": "translateY(0)"},
    },
    "@keyframes fadeIn": {
        "0%": {"opacity": "0"},
        "100%": {"opacity": "1"},
    },
    # New CSS for the Doctor Hover Effect
    ".doc-btn .doc-desc": {
        "max_height": "0",
        "opacity": "0",
        "overflow": "hidden",
        "transition": "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
    },
    ".doc-btn:hover .doc-desc": {
        "max_height": "50px",
        "opacity": "0.8",
        "margin_top": "0.5em"
    }
}

# (Keep your existing FADE_UP_ANIMATION, FADE_IN_ANIMATION, BTN_STYLE, and INPUT_STYLE here)

# --- New Glassmorphism Styles ---
GLASS_DESK_STYLE = {
    "bg": "rgba(218, 230, 217, 0.35)", # Uses a transparent version of your PALETTE_PALEST
    "backdrop_filter": "blur(16px)",
    "border": "1px solid rgba(255, 255, 255, 0.4)",
    "box_shadow": "0 8px 32px 0 rgba(53, 79, 54, 0.2)",
    "border_radius": "24px",
    "padding": "3.5em",
    "width": "100%",
}

INNER_GLASS_STYLE = {
    "bg": "rgba(255, 255, 255, 0.5)",
    "border_radius": "16px",
    "padding": "1.5em",
    "border": "1px solid rgba(255, 255, 255, 0.6)",
    "box_shadow": SOFT_SHADOW,
}

FADE_UP_ANIMATION = "fadeUp 0.7s cubic-bezier(0.16, 1, 0.3, 1) forwards"
FADE_IN_ANIMATION = "fadeIn 0.5s ease-out forwards"

BTN_STYLE = {
    "transition": "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
    "_hover": {"transform": "translateY(-3px)", "box_shadow": HOVER_SHADOW},
    "_active": {"transform": "scale(0.97)", "box_shadow": SOFT_SHADOW}
}

INPUT_STYLE = {
    "transition": "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
    "border": "2px solid transparent",
    "color": TEXT_DARK,
    "_focus": {
        "border": f"2px solid {ACTIVE_GREEN}", 
        "transform": "translateY(-2px)", 
        "box_shadow": SOFT_SHADOW,
        "background": "white"
    }
}

# --- State Management ---
class ClinicState(rx.State):
    
    # Auth State
    is_logged_in: bool = False
    auth_mode: str = "login" 
    phone: str = ""      
    password: str = ""
    client_name: str = ""
    register_name: str = ""

    # Booking Flow State
    step: int = 0  
    selected_doctor: str = ""
    selected_reason: str = ""
    selected_year: str = "2026"
    selected_month: str = "June"
    selected_day: str = ""
    selected_time: str = ""
    booking_type: str = "" 

    # UI Mock Data (Updated with Burmal Dentist info)
    doctors: list[dict[str, str]] = [
        {"name": "Dr. J Pork", "specialty": "General & Emergency Pain"},
        {"name": "Dr. James", "specialty": "Restorative, Fillings & Crowns"},
        {"name": "Dr. Mike", "specialty": "Preventive, Cleaning & Cosmetic"}
    ]
    years: list[str] = ["2026", "2027"]
    months: list[str] = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    calendar_days: list[dict] = [] 

    # Backend Data Arrays
    daily_schedule: list[list[str]] = [] 
    my_appointments: list[dict] = []
    my_waitlist: list[dict] = [] 

    # --- Dynamic Calendar Logic ---
    def update_calendar(self):
        month_num = datetime.strptime(self.selected_month, '%B').month
        year_num = int(self.selected_year)
        num_days = calendar.monthrange(year_num, month_num)[1]
        first_weekday = calendar.monthrange(year_num, month_num)[0] 
        
        days_list = []
        for _ in range(first_weekday):
            days_list.append({"day": "", "disabled": True})
            
        for d in range(1, num_days + 1):
            weekday = calendar.weekday(year_num, month_num, d)
            is_sunday = (weekday == 6) # Sundays are closed
            days_list.append({"day": str(d), "disabled": is_sunday})
            
        self.calendar_days = days_list

    # --- Manual Setters ---
    def set_register_name(self, name: str): self.register_name = name
    def set_phone(self, phone: str): self.phone = phone
    def set_password(self, password: str): self.password = password
    def set_selected_reason(self, reason: str): self.selected_reason = reason
    
    def set_selected_year(self, year: str): 
        self.selected_year = year
        self.update_calendar()
        
    def set_selected_month(self, month: str): 
        self.selected_month = month
        self.update_calendar()

    # --- Authentication Methods ---
    def toggle_auth_mode(self):
        self.auth_mode = "register" if self.auth_mode == "login" else "login"

    def register_client(self):
        try:
            payload = {"name": self.register_name, "phone": self.phone, "password": self.password}
            response = requests.post(f"{API_URL}/clients", json=payload, timeout=3)
            if response.status_code == 201:
                self.client_name = self.register_name
                self.is_logged_in = True
                self.update_calendar()
                return rx.window_alert("Registration successful!")
            return rx.window_alert(response.json().get("detail", "Error registering"))
        except Exception:
            return rx.window_alert("An unexpected error occurred.")
    
    def login(self):
        try:
            response = requests.get(f"{API_URL}/appointments/mine", auth=(self.phone, self.password), timeout=3)
            if response.status_code == 200:
                self.is_logged_in = True
                self.client_name = response.json().get("client_name", "")
                self.my_appointments = response.json().get("appointments", [])
                self.my_waitlist = response.json().get("waitlist", []) 
                self.update_calendar() 
            else:
                return rx.window_alert("Invalid phone or password.")
        except Exception:
            return rx.window_alert("An unexpected error occurred.")
    
    def logout(self):
        self.is_logged_in = False
        self.phone = ""
        self.password = ""
        self.my_appointments = []
        self.my_waitlist = []

    # --- Booking Flow Methods ---
    def start_booking(self):
        self.step = 1
    
    def select_doctor(self, doctor: str):
        self.selected_doctor = doctor
        self.step = 2
    
    def confirm_reason(self):
        if self.selected_reason.strip() != "":
            self.step = 3

    def select_day(self, day: str):
        self.selected_day = day
        self.step = 4
        
        month_num = datetime.strptime(self.selected_month, '%B').month
        date_str = f"{self.selected_year}-{month_num:02d}-{int(day):02d}"
        
        booked_times = []
        try:
            response = requests.get(f"{API_URL}/schedule?date={date_str}&doctor={self.selected_doctor}",timeout=3)
            if response.status_code == 200:
                booked_times = response.json().get("booked_times", [])
        except Exception:
            pass

        times = []
        curr = datetime.strptime("08:00", "%H:%M")
        end = datetime.strptime("17:00", "%H:%M")
        while curr <= end:
            t_str = curr.strftime("%H:%M")
            status = "booked" if t_str in booked_times else "available"
            times.append([t_str, status])
            curr += timedelta(minutes=30)
            
        self.daily_schedule = times
    
    def handle_time_selection(self, time: str, status: str):
        self.selected_time = time
        self.booking_type = "standard" if status == "available" else "waitlist"
        self.step = 5 

    def _format_datetime(self) -> str:
        month_num = datetime.strptime(self.selected_month, '%B').month
        return f"{self.selected_year}-{month_num:02d}-{int(self.selected_day):02d} {self.selected_time}:00"
    
    def submit_appointment(self):
        formatted_datetime = self._format_datetime()
        endpoint = "/appointments" if self.booking_type == "standard" else "/waitlist"
        payload_key = "appointment_at" if self.booking_type == "standard" else "preferred_time"
        
        payload = {"reason_of_appointment": self.selected_reason, "doctor_name": self.selected_doctor, payload_key: formatted_datetime}
        response = requests.post(f"{API_URL}{endpoint}", json=payload, auth=(self.phone, self.password))
        
        if response.status_code == 201:
            msg = "Appointment booked successfully!" if self.booking_type == "standard" else f"Added to waitlist for {formatted_datetime}."
            rx.window_alert(msg)
        else:
            return rx.window_alert(response.json().get("detail", "Request failed"))
    
        self.cancel_booking()
        self.login() 
    
    def cancel_booking(self):
        self.step = 0
        self.selected_doctor = ""
        self.selected_reason = ""
        self.selected_day = ""
        self.selected_time = ""
    
    def cancel_existing_appointment(self, id: int, is_waitlist: bool):
        endpoint = f"/waitlist/{id}/cancel" if is_waitlist else f"/appointments/{id}/cancel"
        response = requests.post(f"{API_URL}{endpoint}", json={"reason": "UI Cancel"}, auth=(self.phone, self.password))
        if response.status_code == 200:
            rx.window_alert("Cancelled successfully.")
            self.login() 
        else:
            rx.window_alert("Could not cancel.")
    
    def handle_auth_submit(self):
        if self.auth_mode == "login":
            return self.login()
        return self.register_client()
    
# --- UI Components ---
def animated_container(content: rx.Component, is_visible: bool) -> rx.Component:
    return rx.box(
        content,
        opacity=rx.cond(is_visible, "1", "0"),
        transform=rx.cond(is_visible, "translateY(0) scale(1)", "translateY(-15px) scale(0.98)"),
        max_height=rx.cond(is_visible, "800px", "0px"), 
        overflow="hidden", 
        transition="all 0.6s cubic-bezier(0.16, 1, 0.3, 1)", 
        width="100%", transform_origin="top"
    )

def frosted_header(text: str, size: str = "6") -> rx.Component:
    return rx.box(
        rx.heading(text, size=size, color=PALETTE_PALEST),
        bg="rgba(24, 36, 24, 0.4)", 
        padding="0.8em 1.5em",
        border_radius="16px",
        backdrop_filter="blur(10px)",
        box_shadow="0 4px 15px rgba(0,0,0,0.1)",
        display="inline-block"
    )

# --- Auth Screen ---
def auth_screen() -> rx.Component:
    return rx.vstack(
        frosted_header("Burmal Dentist", size="8"),
        rx.text("General Care, Cosmetic & Emergency Dentistry", color="white", opacity="0.8", margin_bottom="1.5em", font_size="1.1em"),
        rx.box(
            rx.vstack(
                rx.cond(
                    ClinicState.auth_mode == "register",
                    rx.input(placeholder="Full Name", value=ClinicState.register_name, on_change=ClinicState.set_register_name, border_radius="12px", size="3", bg="white", width="100%", **INPUT_STYLE)
                ),
                rx.input(placeholder="Phone Number", value=ClinicState.phone, on_change=ClinicState.set_phone, border_radius="12px", size="3", bg="white", width="100%", **INPUT_STYLE),
                rx.input(placeholder="Password", type="password", value=ClinicState.password, on_change=ClinicState.set_password, border_radius="12px", size="3", bg="white", width="100%", **INPUT_STYLE),
                
                rx.button(
                    rx.cond(ClinicState.auth_mode == "login", "Log In", "Register"),
                    on_click=ClinicState.handle_auth_submit,
                    border_radius="12px", size="3", padding_x="2em", bg=PALETTE_DARK, color="white", width="100%", margin_top="1em",
                    **BTN_STYLE
                ),
                rx.button(
                    rx.cond(ClinicState.auth_mode == "login", "Need an account? Register", "Have an account? Log in"),
                    on_click=ClinicState.toggle_auth_mode, bg="transparent", color=TEXT_LIGHT, width="100%",
                    transition="all 0.3s ease", _hover={"color": PALETTE_DARK}
                ),
                width="100%", spacing="4"
            ),
            # Applied the new glassy desk style here
            **GLASS_DESK_STYLE, 
            max_width="400px", margin_top="1em", animation=FADE_UP_ANIMATION 
        ),
        align_items="center", justify_content="center", width="100%", min_height="80vh"
    )

# --- Dashboard & Booking Screens ---
def time_slot_card(time_val: str, status: str) -> rx.Component:
    is_available = (status == "available")
    is_selected = (ClinicState.selected_time == time_val)
    bg_color = rx.cond(is_available, ACTIVE_GREEN, SOFT_YELLOW)
    text_color = rx.cond(is_available, ACTIVE_TEXT, DARK_YELLOW)

    return rx.button(
        rx.text(time_val, font_size="1.2em", font_weight="600"),
        on_click=ClinicState.handle_time_selection(time_val, status),
        width="100%", padding="1.5em", border_radius="12px",
        bg=rx.cond(is_selected, PALETTE_DARK, bg_color), color=rx.cond(is_selected, "white", text_color),
        **BTN_STYLE 
    )

def entry_card(item: dict, is_waitlist: bool) -> rx.Component:
    time_key = "preferred_time" if is_waitlist else "appointment_at"
    id_key = "waitlist_id" if is_waitlist else "appointment_id"
    
    return rx.hstack(
        rx.vstack(
            rx.text(item[time_key], font_weight="600", color=TEXT_DARK, font_size="1.1em"),
            rx.text(item["reason_of_appointment"], color=TEXT_LIGHT, font_size="0.95em"),
            align_items="flex-start"
        ),
        rx.spacer(),
        rx.button("Cancel", on_click=lambda: ClinicState.cancel_existing_appointment(item[id_key], is_waitlist), bg="#fca5a5", color="#7f1d1d", border_radius="8px", padding="1em 1.5em", **BTN_STYLE),
        width="100%", bg=PALETTE_PALEST, padding="1.5em 2em", border_radius="16px", box_shadow=SOFT_SHADOW,
        animation=FADE_UP_ANIMATION
    )

def booking_widget() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ClinicState.step == 0,
            rx.button(
                "Create Appointment", on_click=ClinicState.start_booking,
                border_radius="999px", padding="1.5em 3em", bg=PALETTE_DARK, color="white", box_shadow=SOFT_SHADOW,
                **BTN_STYLE
            )
        ),
        rx.cond(
            ClinicState.step > 0,
            rx.vstack(
                # Emergency Banner
                rx.box(
                    rx.hstack(
                        rx.text("🚨", font_size="1.2em"),
                        rx.text("Emergency? For severe pain, swelling, bleeding, or trauma, please bypass this app and visit the clinic immediately.", color="#7f1d1d", font_size="0.9em", font_weight="500"),
                    ),
                    bg="#fee2e2", padding="1em 1.5em", border_radius="12px", width="100%", margin_bottom="1em"
                ),

                rx.hstack(
                    rx.heading("New Appointment", size="6", color=TEXT_DARK),
                    rx.spacer(),
                    rx.button(
                        "Cancel", on_click=ClinicState.cancel_booking, bg="transparent", color=TEXT_LIGHT,
                        transition="all 0.2s ease", _hover={"color": TEXT_DARK, "background": INPUT_BG}
                    ),
                    width="100%"
                ),
                rx.divider(margin_y="1em", border_color="rgba(0,0,0,0.1)"),
                
                # Step 1: Doctor Selection with Fixed Height to stop layout shifting
                animated_container(
                    rx.vstack(
                        rx.text("Who would you like to see?", font_weight="500", color=TEXT_DARK),
                        rx.grid(
                            rx.foreach(
                                ClinicState.doctors, 
                                lambda doc: rx.button(
                                    rx.vstack(
                                        rx.text(doc["name"], font_weight="600"),
                                        rx.text(doc["specialty"], class_name="doc-desc", font_size="0.8em"),
                                        align_items="flex-start", spacing="0"
                                    ),
                                    class_name="doc-btn",
                                    on_click=ClinicState.select_doctor(doc["name"]), 
                                    border_radius="12px", padding="1.5em", 
                                    bg=rx.cond(ClinicState.selected_doctor == doc["name"], ACTIVE_GREEN, "rgba(255,255,255,0.8)"), 
                                    color=rx.cond(ClinicState.selected_doctor == doc["name"], ACTIVE_TEXT, TEXT_DARK), 
                                    height="115px", # <-- Fixed height prevents the whole desk from expanding!
                                    align_items="flex-start",
                                    **BTN_STYLE
                                )
                            ),
                            columns={"initial": "1", "sm": "2", "md": "3"}, spacing="3", width="100%"
                        ), width="100%", spacing="4"
                    ), ClinicState.step >= 1
                ),
                
                # Step 2: Reason 
                animated_container(
                    rx.box(
                        rx.divider(margin_y="1.5em", border_color="rgba(0,0,0,0.1)"),
                        rx.vstack(
                            rx.text("Reason for visit?", font_weight="500", color=TEXT_DARK),
                            rx.input(placeholder="e.g., Routine checkup, tooth pain...", value=ClinicState.selected_reason, on_change=ClinicState.set_selected_reason, border_radius="12px", size="3", bg=f"rgba(184, 206, 183, 0.4)", width="100%", **INPUT_STYLE),
                            rx.button("Next", on_click=ClinicState.confirm_reason, border_radius="12px", padding="1em 2em", bg=PALETTE_DARK, color="white", **BTN_STYLE),
                            width="100%", spacing="4", **INNER_GLASS_STYLE
                        ), width="100%"
                    ), ClinicState.step >= 2
                ),
                
                # Step 3: Calendar 
                animated_container(
                    rx.box(
                        rx.divider(margin_y="1.5em", border_color="rgba(0,0,0,0.1)"),
                        rx.vstack(
                            rx.text("Select a Date (Closed Sundays)", font_weight="500", color=TEXT_DARK),
                            rx.hstack(
                                rx.select(ClinicState.years, value=ClinicState.selected_year, on_change=ClinicState.set_selected_year, bg=f"rgba(184, 206, 183, 0.4)", **INPUT_STYLE), 
                                rx.select(ClinicState.months, value=ClinicState.selected_month, on_change=ClinicState.set_selected_month, bg=f"rgba(184, 206, 183, 0.4)", **INPUT_STYLE), 
                                width="100%", spacing="4"
                            ),
                            rx.grid(
                                rx.foreach(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], lambda d: rx.text(d, text_align="center", font_size="0.8em", font_weight="600", color=TEXT_LIGHT)),
                                columns="7", spacing="2", width="100%", padding_top="1em"
                            ),
                            rx.grid(
                                rx.foreach(ClinicState.calendar_days, lambda day_dict: rx.cond(
                                    day_dict["day"] != "",
                                    rx.button(
                                        day_dict["day"], 
                                        on_click=rx.cond(~day_dict["disabled"], ClinicState.select_day(day_dict["day"]), None), 
                                        disabled=day_dict["disabled"],
                                        border_radius="8px", padding="1em", 
                                        bg=rx.cond(day_dict["disabled"], "rgba(0,0,0,0.04)", rx.cond(ClinicState.selected_day == day_dict["day"], ACTIVE_GREEN, "white")), 
                                        color=rx.cond(day_dict["disabled"], "rgba(0,0,0,0.3)", rx.cond(ClinicState.selected_day == day_dict["day"], ACTIVE_TEXT, TEXT_DARK)), 
                                        border=rx.cond(day_dict["disabled"], "none", f"1px solid {PALETTE_LIGHT}"), 
                                        **BTN_STYLE
                                    ),
                                    rx.box() 
                                )),
                                columns="7", spacing="2", width="100%", padding_top="0.5em"
                            ), width="100%", spacing="4", **INNER_GLASS_STYLE
                        ), width="100%"
                    ), ClinicState.step >= 3
                ),
                
                # Step 4: Time Slots
                animated_container(
                    rx.box(
                        rx.divider(margin_y="1.5em", border_color="rgba(0,0,0,0.1)"),
                        rx.vstack(
                            rx.hstack(
                                rx.text("Available Times (08:00 - 17:00)", font_weight="500", color=TEXT_DARK),
                                rx.spacer(),
                                rx.hstack(rx.box(width="12px", height="12px", bg=ACTIVE_GREEN, border_radius="999px"), rx.text("Available", font_size="0.85em", color=TEXT_LIGHT), spacing="2", align_items="center"),
                                rx.hstack(rx.box(width="12px", height="12px", bg=SOFT_YELLOW, border_radius="999px"), rx.text("Waitlist", font_size="0.85em", color=TEXT_LIGHT), spacing="2", align_items="center"),
                                width="100%", align_items="center"
                            ),
                            rx.grid(rx.foreach(ClinicState.daily_schedule, lambda item: time_slot_card(item[0], item[1])), columns={"initial": "2", "sm": "3", "md": "4"}, spacing="3", width="100%"),
                            width="100%", spacing="4"
                        ), width="100%"
                    ), ClinicState.step >= 4
                ),
                
                # Step 5: Final Confirm Button
                animated_container(
                    rx.box(
                        rx.divider(margin_y="1.5em", border_color="rgba(0,0,0,0.1)"),
                        rx.button(
                            rx.cond(ClinicState.booking_type == "standard", "Confirm Appointment", "Join Waitlist"),
                            on_click=ClinicState.submit_appointment,
                            border_radius="12px", padding="1.5em", bg=PALETTE_DARK, color="white", width="100%", box_shadow=SOFT_SHADOW, **BTN_STYLE
                        )
                    ), ClinicState.step >= 5
                ),
                
                # Replaced Desk Style with an inner container style so it flows inside the main workspace
                width="100%", bg="rgba(255, 255, 255, 0.3)", padding="3.5em", border_radius="24px", box_shadow=SOFT_SHADOW, margin_top="2em",
                animation=FADE_UP_ANIMATION 
            )
        ),
        width="100%", align_items="center", padding_y="1em"
    )

def dashboard() -> rx.Component:
    return rx.vstack(
        # --- Dedicated Header Box ---
        rx.hstack(
            rx.heading("Burmal Dentist", size="7", color="white"),
            rx.spacer(),
            rx.text("Mon-Sat: 08:00 - 17:00 | Sun: Closed", color="rgba(255,255,255,0.8)", font_size="0.9em", font_weight="500", display={"initial": "none", "md": "block"}),
            rx.spacer(),
            rx.button(
                "Log Out",
                on_click=ClinicState.logout,
                bg="rgba(0, 0, 0, 0.2)", color="white", border_radius="12px", padding="0.8em 1.5em",
                border="1px solid rgba(255,255,255,0.1)", transition="all 0.3s ease",
                _hover={"bg": "rgba(0, 0, 0, 0.4)", "transform": "translateY(-2px)"}
            ),
            width="100%", padding="1.5em 3em",
            bg=PALETTE_MID_DARK, # Distinct color separating it from the desk
            box_shadow="0 10px 30px -10px rgba(0,0,0,0.3)"
        ),
        
        # --- Persistent Working Space (Blurry Desk) ---
        rx.vstack(
            # Standard Appointments List 
            rx.vstack(
                rx.heading(f"{ClinicState.client_name}'s Upcoming Appointments", size="5", color=TEXT_DARK, margin_bottom="0.5em"),
                rx.cond(
                    ClinicState.my_appointments.length() > 0,
                    rx.foreach(ClinicState.my_appointments, lambda appt: entry_card(appt, is_waitlist=False)),
                    rx.text("You have no upcoming appointments.", color=TEXT_DARK, opacity="0.8", font_style="italic", padding_left="0.5em")
                ),
                width="100%", spacing="4", padding_bottom="1.5em"
            ),

            # Waitlist List 
            rx.vstack(
                rx.heading(f"{ClinicState.client_name}'s Waitlist Entries", size="5", color=TEXT_DARK, margin_bottom="0.5em"),
                rx.cond(
                    ClinicState.my_waitlist.length() > 0,
                    rx.foreach(ClinicState.my_waitlist, lambda appt: entry_card(appt, is_waitlist=True)),
                    rx.text("You have no waitlisted appointments.", color=TEXT_DARK, opacity="0.8", font_style="italic", padding_left="0.5em")
                ),
                width="100%", spacing="4", padding_bottom="1.5em"
            ),
            
            booking_widget(),
            
            # The Glass Desk is now applied to the entire working area
            **GLASS_DESK_STYLE,
            max_width="850px", margin_top="3em" 
        ),
        
        width="100%", align_items="center", justify_content="flex-start", padding_bottom="3em", min_height="100vh"
    )

def index() -> rx.Component:
    return rx.box(
        rx.cond(
            ClinicState.is_logged_in,
            dashboard(),
            auth_screen()
        ),
        background=f"radial-gradient(circle at 50% 50%, {PALETTE_MID} 0%, #1e2e1e 100%)",
        background_attachment="fixed", 
        min_height="100vh"
    )

app = rx.App(style=GLOBAL_STYLE)
app.add_page(index)