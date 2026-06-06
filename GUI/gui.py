import reflex
import os
import sys
import requests

# ClinicState manages the state of the clinic appointment scheduling application
class ClinicState(reflex.State):
    
    # --- Auth State ---
    is_logged_in: bool = False
    username: str = ""
    password: str = ""

    # ---  Doctor State ---
    selected_doctor: str = "<Choose Doctor>"
    doctor_list: list[str] = ["Dr. Smith", "Dr. Johnson", "Dr. Lee"]

    # --- Appointment State ---
    selected_date: str = ""
    selected_time: tuple[str, str] = ("", "")
    selected_reason: str = ""
    apointment_status: str = ""
    schedule_data: dict[str, str, tuple[str, str], str] = {(selected_reason, selected_date, selected_time): apointment_status}

    # Load schedule data from a file (if it exists)
    def load_schedule(self):
        #TODO: Implement loading schedule data from a file

        self.schedule_data = {
            ("cleaning", "2023-10-15", "10:00"): "booked"
        }

    # Cancel an appointment by updating the schedule data
    def cancel_appointment(self):
        #TODO: Implement canceling an appointment

        self.load_schedule()

    
    # Renders the time slot options based on the selected doctor, date and availability
    def render_time_slots():

        return