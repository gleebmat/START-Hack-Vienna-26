# Burmal Dentist

Dental appointment management system built for **START Hack Vienna '26**.

The project combines a FastAPI backend, a PostgreSQL database, fonio.ai and a Reflex web combined with
interface for patients and clinic admins. Patients can register, book available
appointments, join a waitlist when a slot is taken, cancel bookings and many more. Clinic
admins can monitor appointments, waitlist entries, metrics, and call activity. But the main focus is implementing ai-based call system who make our life easier!

## Features

- Patient registration and HTTP Basic authentication
- Appointment booking by doctor, date, and time
- Automatic waitlist handling for already-booked slots
- Appointment and waitlist cancellation flows
- Fonio webhook support for inbound and outbound call intake data
- Admin dashboard for live clinic metrics and operational overview

## Tech Stack

- Python
- FastAPI
- PostgreSQL
- Psycopg
- Reflex
- Requests / HTTPX
- Beaver
- ngrok
- fonio.ai

## Getting Started

### Prerequisites

- Python 3.11 or newer
- PostgreSQL running locally
- A Fonio API key for call automation features

### Backend Setup


Create and activate a virtual environment, then install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Create a local PostgreSQL database:

```sql
CREATE DATABASE fonio_hackathon;
```

Create a `.env` file from the example and add your Fonio API key:

```bash
copy .env.example .env
```

Required environment variables:

```env
FONIO_API_KEY=your_fonio_api_key
```

Initialize and seed the database:

```bash
python database.py
python seed_db.py
```

Run the FastAPI backend:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8080
```

API documentation is available at:

```text
http://127.0.0.1:8080/docs
```

### Frontend Setup

In a second terminal, start the Reflex app:

```bash
cd GUI
reflex run
```

The frontend expects the backend to be available at:

```text
http://127.0.0.1:8080
```

## Demo Credentials

After running `seed_db.py`, all seeded users use the password:

```text
test1234
```

Example seeded phone numbers:

- `+436601111111`
- `+436601111112`
- `+436601111113`
- `+436601111114`
- `+436601111115`

## Project Structure

```text
.
|-- main.py              # FastAPI application and API routes
|-- database.py          # Database table creation script
|-- seed_db.py           # Demo data seeding script
|-- requirements.txt     # Python dependencies
|-- GUI/                 # Reflex frontend application
|   |-- gui/gui.py       # Patient UI
|   `-- gui/admin.py     # Admin UI
|-- .env.example         # Environment variable template
|-- LICENSE              # MIT license
`-- README.md
```

## Configuration Notes

Database connection settings are currently defined in `main.py`, `database.py`,
and `seed_db.py`. The default local configuration is:

```text
host=localhost
port=5432
dbname=fonio_hackathon
user=postgres
password=1234
```


## License

This project is released under the MIT License. See [LICENSE](LICENSE).
