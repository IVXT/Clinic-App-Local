Hello. Your task is to fix the appointments page in my Flask application, which is based on the repository at https://github.com/IVXT/Clinic-App-Local.The page is failing with a JSON.parse() error because the Python backend is not correctly injecting the appointments_json, patients_json, and doctors_json data into the appointments.html template.Please perform the following four steps exactly.Step 1: Modify app/models.pyOpen the file app/models.py. We must add to_dict() methods to the Patient and Appointment models so they can be easily converted to JSON.Inside the Patient class, add this method:def to_dict(self):
    return {
        'id': self.id,
        'name': self.name,
        'fileNumber': self.file_number,
        'phoneNumber': self.phone
    }
Inside the Appointment class, add this method:def to_dict(self):
    return {
        'id': self.id,
        'patientName': self.patient.name,
        'phoneNumber': self.patient.phone,
        'fileNumber': self.patient.file_number,
        'doctor': self.doctor.username,
        'startTime': self.start_time.isoformat() if self.start_time else None,
        'endTime': self.end_time.isoformat() if self.end_time else None,
        'reason': self.reason,
        'status': self.status
    }
(Note: I've added checks for self.start_time and self.end_time just in case they are ever None).Step 2: Modify app/main/routes.pyOpen the file app/main/routes.py. We need to replace the existing appointments route with a new one that fetches data from the database and injects it into the template.At the top of the file, add these required imports:import json
from app.models import Appointment, Patient, User
Find and replace the entire @main.route('/appointments') function with this new version:@main.route('/appointments')
@login_required
def appointments():
    # 1. Fetch data from your database
    all_appointments = Appointment.query.all()
    all_patients = Patient.query.all()
    # Find all users with the 'doctor' role
    all_doctors = User.query.filter_by(role='doctor').all()

    # 2. Format the data using the .to_dict() methods
    appointments_list = [appt.to_dict() for appt in all_appointments]
    patients_list = [patient.to_dict() for patient in all_patients]

    # Format the doctors list just as the JavaScript expects
    doctors_list = ['All Doctors'] + [doc.username for doc in all_doctors]

    # 3. Convert the data to JSON strings
    appointments_json = json.dumps(appointments_list)
    patients_json = json.dumps(patients_list)
    doctors_json = json.dumps(doctors_list)

    # 4. Pass the JSON strings to your template
    return render_template('appointments.html', 
                           title='Appointments',
                           appointments_json=appointments_json,
                           patients_json=patients_json,
                           doctors_json=doctors_json)
Step 3: Delete the old JavaScript fileThe new template contains all its own JavaScript, so the old file is no longer needed and will conflict.Please delete this file: app/static/js/appointments.js.Step 4: Replace the HTML TemplateOpen the template file: app/templates/appointments.html.Delete all of its current contents.Replace it with the exact code from the appointments_template.html file I provided.After you perform these four steps, the data will be correctly injected, and the appointments page will be fully functional.