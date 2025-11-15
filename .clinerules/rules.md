You are working in a Flask project called **Clinic-App-Local** on Windows.  
The human user is a beginner and **not a coder**. You are the coding expert.

Your main goals:
- Make small, safe, understandable changes.
- Keep the project tidy and documented.
- Update requirements and docs when features change, **without messing them up**.

---

## 1. General behaviour

- Always start with a **short, clear plan** before changing any files.
- Work on **one focused task at a time**  
  (examples: "fix appointments UI", "add a small feature", "update docs", "fix failing tests").
- Prefer **small, readable edits** instead of big refactors.
- Before you:
  - Delete any file or folder
  - Rename files or folders
  - Change database schema or migrations  
  → Explain what you want to do and wait for user confirmation.

If a command or tests fail:
- Explain briefly what failed.
- Suggest a small, safe fix and apply it if the user agrees.

Keep explanations short and simple. The user is not a coder.

---

## 2. Important project layout

You are in the folder: `Clinic-App-Local`.

Key locations:

- `clinic_app/` – main Python backend code  
  - `clinic_app/blueprints/` – routes / views / APIs, grouped by feature  
    - `appointments/` – appointments-related routes and APIs  
    - `patients/`, `payments/`, `receipts/`, `reports/`, `expenses/`, `admin_*`, etc.  
  - `clinic_app/services/` – shared logic (database, appointments, security, helpers)  
  - `clinic_app/extensions.py` – Flask extensions (DB, login, limiter, etc.)

- `templates/` – Jinja2 HTML templates  
  - `_base.html` – main layout  
  - `_nav.html` – top navigation bar  
  - `appointments/vanilla.html` – **modern appointments UI** (Tailwind + JavaScript)

- `static/` – CSS, JS, images

- `tests/` – pytest tests for the project

- `data/` – local database files and data (real clinic data – important)

- Root-level important files:
  - `wsgi.py` – entry point for the app
  - `Start-Clinic.bat` – run the app on Windows
  - `Run-Tests.bat` – run tests on Windows
  - `Run-Migrations.bat` – run DB migrations
  - `requirements.txt` – runtime Python dependencies
  - `requirements.dev.txt` – dev/test dependencies
  - `README.md` – main documentation for the project

---

## 3. Do NOT touch these unless the user clearly asks

Never modify or delete these on your own:

- `.git/`
- `.venv/` or `.venv-wsl/`
- `data/`
- `migrations/`

Be extra careful with:
- Database configs and migration files.
- Batch scripts the user relies on:
  - `Start-Clinic.bat`
  - `Run-Tests.bat`
  - `Run-Migrations.bat`

If a change might be risky (e.g. DB structure), explain the risk first in your plan.

---

## 4. Appointments page rules (very important)

The "fancy" appointments UI should live here:

- Frontend template:  
  `templates/appointments/vanilla.html`

- Backend route:  
  `clinic_app/blueprints/appointments/routes.py`  
  Function: usually `appointments_vanilla()` (or similar) that renders this template.

When working on the **appointments UI**:

1. **Do not break the data injection.**  
   Keep these three `<script>` tags in the template intact, as they are how data flows from backend to frontend:

   <script type="application/json" id="appointments-data">{{ appointments_json | safe }}</script>
   <script type="application/json" id="patients-data">{{ patients_json | safe }}</script>
   <script type="application/json" id="doctors-data">{{ doctors_json | safe }}</script>

2. UI-only changes (styling, layout, text, modals, filters, etc.):
   - Stay inside templates/appointments/vanilla.html.

3. Backend/data changes (how appointments, patients, and doctors are loaded, filtered, and structured):
   - Stay inside:
     - clinic_app/blueprints/appointments/routes.py
     - and, if needed, appointments-related services in clinic_app/services/.

4. If you must change the JSON structure:
   - Update both backend and frontend.
   - Explain clearly what changed.

---

## 5. Requirements & documentation updates (keep in sync, don’t wreck them)

The user wants you to keep requirements and README up to date when things change, but not to mess them up.

### 5.1 Python dependencies

If you add a new Python package:
- Add it to requirements.txt.
- If it is dev-only (tests, linters, tools), add it to requirements.dev.txt instead.
- In your plan, explicitly say:
  - Which package you are adding.
  - Which file(s) you will update.

If you remove a package from the code:
- Propose removing it from requirements.txt / requirements.dev.txt as a separate, small step.
- Do NOT rewrite or reorder the whole requirements file.
- Only touch the specific lines that are relevant.

### 5.2 README / docs

If you add or change a user-visible feature or important page:
- Check README.md and docs/ (if present).
- Propose a small, focused update:
  - Add a bullet.
  - Add a short subsection.
  - Update one paragraph.

In your plan, clearly state:
- Which doc file you will edit.
- Which section or heading you will change or add.

When editing docs:
- Keep the existing structure.
- Do NOT rewrite the whole README unless the user explicitly asks.
- Do NOT delete information unless it is clearly wrong or outdated.

---

## 6. Running and testing

On Windows, prefer using the existing scripts:

To run the app:
- Start-Clinic.bat

To run tests:
- Run-Tests.bat

If you need to show raw terminal commands instead, use:
- .venv\Scripts\python wsgi.py
- .venv\Scripts\python -m pytest

If you change backend logic or routes, it is good practice to run the tests.

---

## 7. Style and code quality

- Follow the existing style and structure of the code.
- Keep new functions focused and reasonably small.
- Reuse helpers and services in clinic_app/services/ instead of duplicating logic.
- Keep changes as local as possible to the relevant blueprint/template.

---

## 8. When the request is vague or you are unsure

The user is not a coder.

When you are confused:
- Say what you think the user wants, in simple language.
- Ask one clear question if you need clarification.
- Suggest a safe, small plan that will not break the app.

Always keep your explanations short, friendly, and concrete.
