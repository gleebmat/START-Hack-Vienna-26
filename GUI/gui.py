import reflex as rx
import os
import sys

# Stores all the states of the site
class ClinincState(rx.State):
    # --- User states ---
    is_logged_in: bool = False
    user: str = ""
    is_admin: bool = False

    # --- Doctor states ---
    current_doctor: str = "<Select a doctor>"
    doctor_list: list[str] = ["Dr. Smith", "Dr. Johnson", "Dr. Lee"]

    # --- Appointment states ---
    schedule_data: dict[tuple[str, str], str] = {}

    

    pass
