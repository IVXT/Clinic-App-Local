==================================================
Clinic App (Local) – README
==================================================

This is a Flask-based clinic management app designed to run locally on Windows.

It includes:
- Appointments
- Patients
- Receipts and payments
- Expenses
- Reports
- Admin / roles / users

This folder "Clinic-App-Local" is the main project folder.

--------------------------------------------------
1. How to run the app on Windows
--------------------------------------------------

First time:

1. Install Python 3.12 (or a compatible 3.x) on Windows.
2. Put this project folder somewhere, for example:
   C:\Clinic-App-Local
3. In that folder, double-click:
   Start-Clinic.bat

The script will:
- Create a virtual environment (.venv) the first time
- Install dependencies from requirements.txt
- Run the app via wsgi.py on port 8080

Next times:

1. Open the Clinic-App-Local folder.
2. Double-click Start-Clinic.bat again.
3. When the console says the server is running, open your browser and go to:

   http://127.0.0.1:8080/

Then log in with your clinic user.

--------------------------------------------------
2. Project structure (short version)
--------------------------------------------------

You are in the folder: Clinic-App-Local.

Important locations:

- clinic_app/      → main Python backend code
  - clinic_app/blueprints/  → routes / views / APIs, grouped by feature
    - appointments/         → appointments-related routes and APIs
    - patients/, payments/, receipts/, reports/, expenses/, admin_*, etc.
  - clinic_app/services/    → shared logic (database, appointments, security, helpers)
  - clinic_app/extensions.py → Flask extensions (DB, login, limiter, etc.)

- templates/      → Jinja2 HTML templates
  - _base.html            → main layout
  - _nav.html             → top navigation bar
  - appointments/vanilla.html → modern appointments UI (Tailwind + JavaScript)

- static/         → CSS, JS, images
- tests/          → pytest tests for the project
- data/           → local database files and data (real clinic data – important)

Root-level important files:

- wsgi.py              → entry point for the app
- Start-Clinic.bat     → run the app on Windows
- Run-Tests.bat        → run tests on Windows
- Run-Migrations.bat   → run database migrations
- requirements.txt     → runtime Python dependencies
- requirements.dev.txt → dev/test dependencies
- README.md            → this file

--------------------------------------------------
3. Appointments page (the "fancy" UI)
--------------------------------------------------

The main appointments UI should live here:

Frontend:
- Template file:
  templates/appointments/vanilla.html

Backend:
- Route module:
  clinic_app/blueprints/appointments/routes.py
- Function (usually):
  appointments_vanilla()

How it works:

1. The backend route loads appointments, doctors, and patients from the database.
2. It converts them to JSON.
3. It injects that JSON into the template using three script tags:

   <script type="application/json" id="appointments-data">{{ appointments_json | safe }}</script>
   <script type="application/json" id="patients-data">{{ patients_json | safe }}</script>
   <script type="application/json" id="doctors-data">{{ doctors_json | safe }}</script>

4. The JavaScript inside templates/appointments/vanilla.html reads those JSON blobs and:
   - Renders appointment cards grouped by date
   - Handles filters (date, doctor)
   - Handles patient search
   - Opens modals to view/add/edit/delete appointments through backend APIs

If the appointments page is broken, it usually means:
- These script tags are missing or changed, or
- The JSON data format from the backend does not match what the frontend expects.

--------------------------------------------------
4. Running tests
--------------------------------------------------

To run tests on Windows:

Option 1: Double-click
- Run-Tests.bat

Option 2: From a terminal in the project folder, with the virtual environment active:

- .venv\Scripts\python -m pytest

All tests live under:
- tests/

--------------------------------------------------
5. Requirements
--------------------------------------------------

Dependencies are listed in:

- requirements.txt          → main runtime dependencies
- requirements.dev.txt      → dev/test tools (like pytest, etc.)

Inside the virtual environment you can install them manually with:

- pip install -r requirements.txt
- pip install -r requirements.dev.txt

--------------------------------------------------
6. Notes for AI assistants (Cline, ChatGPT, etc.)
--------------------------------------------------

- The user is NOT a coder. Use simple language and small, safe changes.
- Read the rules file for this project if it exists (for example: .clinerules/rules.md or Workspace Rules).
- Do NOT modify or delete:
  - .git/
  - .venv/ or .venv-wsl/
  - data/
  - migrations/
- For appointments UI:
  - Frontend: templates/appointments/vanilla.html
  - Backend: clinic_app/blueprints/appointments/routes.py
  - Keep the three JSON script tags intact:
    - appointments-data
    - patients-data
    - doctors-data
- Always start by showing a short plan before making changes.
- Prefer small, local edits over big refactors.

==================================================
END OF README CONTENT
==================================================
