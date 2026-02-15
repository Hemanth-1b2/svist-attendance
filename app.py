#!/usr/bin/env python3
# ============================================
# SVIST ATTENDANCE MANAGEMENT SYSTEM
# Production Version for Railway.app + TiDB
# ============================================

import os
import sys
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from calendar import monthrange

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SelectField, IntegerField, SubmitField, EmailField
from wtforms.validators import DataRequired, Email, Length
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY')
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY environment variable is required")

# TiDB Cloud Serverless Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
if not app.config['SQLALCHEMY_DATABASE_URI']:
    raise ValueError("DATABASE_URL environment variable is required")

# Railway.app - Simplified engine options (no SSL CA needed for TiDB Serverless)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Mail Configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

# GPS Configuration
COLLEGE_LAT = float(os.environ.get('COLLEGE_LAT', 17.1000))
COLLEGE_LNG = float(os.environ.get('COLLEGE_LNG', 80.6000))
ALLOWED_RADIUS_KM = float(os.environ.get('ALLOWED_RADIUS_KM', 0.5))

# Initialize Extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'info'
mail = Mail(app)
csrf = CSRFProtect(app)

# ============================================
# DATABASE MODELS (Keep all your existing models)
# ============================================

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, index=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    student = db.relationship('Student', backref='user', uselist=False, lazy='joined')
    teacher = db.relationship('Teacher', backref='user', uselist=False, lazy='joined')

class SemesterHistory(db.Model):
    __tablename__ = 'semester_history'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), index=True)
    semester_number = db.Column(db.Integer, nullable=False)
    section = db.Column(db.String(5))
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    total_theory_classes = db.Column(db.Integer, default=0)
    present_theory_classes = db.Column(db.Integer, default=0)
    total_lab_classes = db.Column(db.Integer, default=0)
    present_lab_classes = db.Column(db.Integer, default=0)
    attendance_percentage = db.Column(db.Float, default=0.0)
    stopped_by_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    stopped_at = db.Column(db.DateTime)

class StoppedSemester(db.Model):
    __tablename__ = 'stopped_semesters'
    id = db.Column(db.Integer, primary_key=True)
    branch = db.Column(db.String(10), nullable=False, index=True)
    semester = db.Column(db.Integer, nullable=False, index=True)
    stopped_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    stopped_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True, index=True)
    
    admin = db.relationship('User', backref='stopped_semesters')

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    register_number = db.Column(db.String(20), unique=True, nullable=False, index=True)
    branch = db.Column(db.String(10), nullable=False, index=True)
    current_semester = db.Column(db.Integer, nullable=False, index=True)
    section = db.Column(db.String(5), nullable=False, index=True)
    phone = db.Column(db.String(15))
    semester_start_date = db.Column(db.Date, nullable=False)
    is_semester_active = db.Column(db.Boolean, default=True, index=True)
    
    attendances = db.relationship('Attendance', backref='student', lazy='dynamic')

class Teacher(db.Model):
    __tablename__ = 'teachers'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    branch = db.Column(db.String(10), nullable=False, index=True)
    qualification = db.Column(db.String(100), nullable=False)
    employee_id = db.Column(db.String(20), unique=True, nullable=False, index=True)
    staff_category = db.Column(db.String(50), nullable=False)
    role = db.Column(db.String(100), nullable=False)
    registration_date = db.Column(db.Date, nullable=False)
    
    attendances = db.relationship('TeacherAttendance', backref='teacher', lazy='dynamic')

class TeacherAttendance(db.Model):
    __tablename__ = 'teacher_attendance'
    id = db.Column(db.Integer, primary_key=True)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teachers.id'), index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    check_in = db.Column(db.DateTime)
    check_out = db.Column(db.DateTime)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location_verified = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(10), default='absent', index=True)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('students.id'), index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    period = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(10), default='absent', index=True)
    marked_by = db.Column(db.Integer, db.ForeignKey('teachers.id'))
    marked_at = db.Column(db.DateTime, default=datetime.utcnow)
    subject = db.Column(db.String(50))
    semester_at_time = db.Column(db.Integer)
    attendance_type = db.Column(db.String(20), default='theory', index=True)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    branch = db.Column(db.String(10), nullable=False, index=True)
    semester = db.Column(db.Integer, nullable=False, index=True)
    subject_type = db.Column(db.String(20), default='theory', index=True)

class AdminLog(db.Model):
    __tablename__ = 'admin_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    action = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

# ============================================
# ROLE DEFINITIONS
# ============================================

TEACHER_ROLES = {
    'Teaching Staff': [
        'Professor', 'Associate Professor', 'Assistant Professor',
        'Lecturer', 'Visiting Faculty', 'Temporary Faculty'
    ],
    'Technical Staff': [
        'Lab Technician', 'Lab Assistant', 'System Administrator', 'Workshop Instructor'
    ],
    'Key Administrative & Specialized Faculty': [
        'Principal', 'Dean - Academics', 'Training & Placement Officer (TPO)',
        'Librarian', 'Assistant Librarian', 'Physical Director', 'Class Advisor/Mentor'
    ],
    'Support Administrative Staff': [
        'Administrative Officer (AO)', 'Accounts Officer/Clerk',
        'Office Assistant', 'Maintenance Supervisor'
    ],
    'Examination Cell': [
        'Controller of Examinations (CoE)', 'Examination In-charge',
        'Clerk/Examination Assistant', 'Data Entry Operator', 'Frisking Staff'
    ]
}

BRANCHES = [
    ('ECE', 'ECE'), ('CSE', 'CSE'), ('EEE', 'EEE'),
    ('CIVIL', 'CIVIL'), ('MECH', 'MECH'), ('DS', 'DS'), ('AIML', 'AIML')
]

# ============================================
# FORMS
# ============================================

class StudentRegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    register_number = StringField('Register Number', validators=[DataRequired(), Length(max=20)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    branch = SelectField('Branch', choices=BRANCHES)
    semester = SelectField('Current Semester', choices=[(str(i), f'Semester {i}') for i in range(1, 9)])
    section = SelectField('Section', choices=[('A', 'A'), ('B', 'B'), ('C', 'C')])
    phone = StringField('Phone Number', validators=[Length(max=15)])
    submit = SubmitField('Register')

class TeacherRegistrationForm(FlaskForm):
    name = StringField('Full Name', validators=[DataRequired(), Length(max=100)])
    employee_id = StringField('Employee ID', validators=[DataRequired(), Length(max=20)])
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    branch = SelectField('Branch', choices=BRANCHES + [
        ('EXAMINATION', 'Examination Cell'), ('ADMIN', 'Administration')
    ])
    qualification = StringField('Qualification', validators=[DataRequired(), Length(max=100)])
    staff_category = SelectField('Staff Category', choices=[(k, k) for k in TEACHER_ROLES.keys()])
    role = SelectField('Role', choices=[])
    submit = SubmitField('Register')

class LoginForm(FlaskForm):
    email = EmailField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    role = SelectField('Login As', choices=[
        ('student', 'Student'), ('teacher', 'Teacher'), ('admin', 'Administrator')
    ])
    submit = SubmitField('Login')

class StopSemesterForm(FlaskForm):
    branch = SelectField('Branch', choices=BRANCHES)
    semester = SelectField('Semester', choices=[(str(i), f'Semester {i}') for i in range(1, 9)])
    submit = SubmitField('Stop Semester Attendance')

class SubjectForm(FlaskForm):
    code = StringField('Subject Code', validators=[DataRequired()])
    name = StringField('Subject Name', validators=[DataRequired()])
    branch = SelectField('Branch', choices=BRANCHES)
    semester = SelectField('Semester', choices=[(str(i), f'Semester {i}') for i in range(1, 9)])
    subject_type = SelectField('Type', choices=[
        ('theory', 'Theory'), ('lab', 'Lab'), ('crt', 'CRT'), ('workshop', 'Workshop')
    ])
    submit = SubmitField('Add Subject')

# ============================================
# UTILITIES
# ============================================

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def teacher_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'teacher':
            flash('Teacher access required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def calculate_distance(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    lat1, lng1, lat2, lng2 = map(radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlng/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c

def verify_location(latitude, longitude):
    if not latitude or not longitude:
        return False
    try:
        distance = calculate_distance(float(latitude), float(longitude), COLLEGE_LAT, COLLEGE_LNG)
        return distance <= ALLOWED_RADIUS_KM
    except (ValueError, TypeError):
        return False

def is_semester_stopped(branch, semester):
    stopped = StoppedSemester.query.filter_by(
        branch=branch, semester=semester, is_active=True
    ).first()
    return stopped is not None

def get_comprehensive_attendance(student, start_date=None, end_date=None):
    if start_date is None:
        start_date = student.semester_start_date
    if end_date is None:
        end_date = datetime.now().date()
    
    attendances = Attendance.query.filter(
        Attendance.student_id == student.id,
        Attendance.date >= start_date,
        Attendance.date <= end_date,
        Attendance.semester_at_time == student.current_semester
    ).all()
    
    theory_attendances = [att for att in attendances if att.attendance_type == 'theory']
    practical_attendances = [att for att in attendances if att.attendance_type in ['lab', 'crt', 'workshop']]
    
    theory_total = len(theory_attendances)
    theory_present = sum(1 for att in theory_attendances if att.status == 'present')
    
    practical_total = len(practical_attendances)
    practical_present = sum(1 for att in practical_attendances if att.status == 'present')
    
    total_periods = theory_total + practical_total
    present_periods = theory_present + practical_present
    
    subject_wise = {}
    for att in attendances:
        subject = att.subject or 'Unknown'
        if subject not in subject_wise:
            subject_wise[subject] = {'total': 0, 'present': 0, 'type': att.attendance_type}
        subject_wise[subject]['total'] += 1
        if att.status == 'present':
            subject_wise[subject]['present'] += 1
    
    for subject in subject_wise:
        total = subject_wise[subject]['total']
        present = subject_wise[subject]['present']
        subject_wise[subject]['percentage'] = (present / total * 100) if total > 0 else 0
    
    monthly_data = {}
    for att in attendances:
        month_key = att.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                'month_name': att.date.strftime('%B %Y'),
                'theory_total': 0, 'theory_present': 0,
                'practical_total': 0, 'practical_present': 0
            }
        if att.attendance_type == 'theory':
            monthly_data[month_key]['theory_total'] += 1
            if att.status == 'present':
                monthly_data[month_key]['theory_present'] += 1
        else:
            monthly_data[month_key]['practical_total'] += 1
            if att.status == 'present':
                monthly_data[month_key]['practical_present'] += 1
    
    return {
        'start_date': start_date, 'end_date': end_date,
        'theory_total': theory_total, 'theory_present': theory_present,
        'theory_percentage': (theory_present / theory_total * 100) if theory_total > 0 else 0,
        'practical_total': practical_total, 'practical_present': practical_present,
        'practical_percentage': (practical_present / practical_total * 100) if practical_total > 0 else 0,
        'total_periods': total_periods, 'present_periods': present_periods,
        'overall_percentage': (present_periods / total_periods * 100) if total_periods > 0 else 0,
        'subject_wise': subject_wise, 'monthly_breakdown': monthly_data,
        'theory_attendances': theory_attendances, 'practical_attendances': practical_attendances
    }

def get_teacher_yearly_attendance(teacher, year=None):
    if year is None:
        year = datetime.now().year
    
    start_date = datetime(year, 1, 1).date()
    end_date = datetime(year, 12, 31).date()
    
    if teacher.registration_date.year == year:
        start_date = teacher.registration_date
    
    attendances = TeacherAttendance.query.filter(
        TeacherAttendance.teacher_id == teacher.id,
        TeacherAttendance.date >= start_date,
        TeacherAttendance.date <= end_date,
        TeacherAttendance.status == 'present'
    ).all()
    
    total_days = len(attendances)
    
    monthly_data = {}
    for att in attendances:
        month_key = att.date.strftime('%Y-%m')
        if month_key not in monthly_data:
            monthly_data[month_key] = {'month_name': att.date.strftime('%B'), 'days_present': 0, 'check_ins': []}
        monthly_data[month_key]['days_present'] += 1
        monthly_data[month_key]['check_ins'].append({
            'date': att.date,
            'check_in': att.check_in.strftime('%H:%M') if att.check_in else '-',
            'check_out': att.check_out.strftime('%H:%M') if att.check_out else '-'
        })
    
    working_days = sum(1 for day in range((end_date - start_date).days + 1) 
                      if (start_date + timedelta(days=day)).weekday() < 5)
    
    return {
        'year': year, 'start_date': start_date, 'end_date': end_date,
        'total_days_present': total_days, 'working_days': working_days,
        'percentage': (total_days / working_days * 100) if working_days > 0 else 0,
        'monthly_breakdown': monthly_data
    }

def send_low_attendance_email(student, attendance_percentage):
    if not app.config['MAIL_USERNAME']:
        return
    try:
        msg = Message(
            'Low Attendance Alert - Sree Vahini Institute',
            recipients=[student.user.email]
        )
        msg.body = f"""Dear {student.name},

This is to inform you that your attendance has fallen below 75%.
Current Semester: {student.current_semester}
Current Attendance: {attendance_percentage:.2f}%

Please ensure regular attendance to avoid academic penalties.

Regards,
Sree Vahini Institute of Science and Technology"""
        mail.send(msg)
    except Exception as e:
        app.logger.error(f"Failed to send email: {e}")

# ============================================
# ROUTES
# ============================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        db.session.execute('SELECT 1')
        db_status = 'connected'
    except Exception as e:
        db_status = f'disconnected: {str(e)}'
    
    return jsonify({
        'status': 'healthy',
        'service': 'SVIST Attendance System',
        'database': db_status,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/')
def index():
    return render_template_string(INDEX_HTML)

@app.route('/register/student', methods=['GET', 'POST'])
def register_student():
    form = StudentRegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register_student'))
        
        if Student.query.filter_by(register_number=form.register_number.data).first():
            flash('Register number already exists.', 'danger')
            return redirect(url_for('register_student'))
        
        try:
            user = User(
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
                role='student'
            )
            db.session.add(user)
            db.session.flush()
            
            student = Student(
                user_id=user.id,
                name=form.name.data,
                register_number=form.register_number.data,
                branch=form.branch.data,
                current_semester=int(form.semester.data),
                section=form.section.data,
                phone=form.phone.data,
                semester_start_date=datetime.now().date(),
                is_semester_active=True
            )
            db.session.add(student)
            db.session.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Student registration error: {e}")
            flash('Registration failed. Please try again.', 'danger')
    
    return render_template_string(REGISTER_STUDENT_HTML, form=form)

@app.route('/get-teacher-roles/<category>')
def get_teacher_roles(category):
    roles = TEACHER_ROLES.get(category, [])
    return jsonify(roles)

@app.route('/register/teacher', methods=['GET', 'POST'])
def register_teacher():
    form = TeacherRegistrationForm()
    
    if form.staff_category.data and form.staff_category.data in TEACHER_ROLES:
        form.role.choices = [(r, r) for r in TEACHER_ROLES[form.staff_category.data]]
    else:
        form.role.choices = []
    
    if form.validate_on_submit():
        if User.query.filter_by(email=form.email.data).first():
            flash('Email already registered.', 'danger')
            return redirect(url_for('register_teacher'))
        
        if Teacher.query.filter_by(employee_id=form.employee_id.data).first():
            flash('Employee ID already exists.', 'danger')
            return redirect(url_for('register_teacher'))
        
        try:
            user = User(
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
                role='teacher'
            )
            db.session.add(user)
            db.session.flush()
            
            teacher = Teacher(
                user_id=user.id,
                name=form.name.data,
                employee_id=form.employee_id.data,
                branch=form.branch.data,
                qualification=form.qualification.data,
                staff_category=form.staff_category.data,
                role=form.role.data,
                registration_date=datetime.now().date()
            )
            db.session.add(teacher)
            db.session.commit()
            
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Teacher registration error: {e}")
            flash('Registration failed. Please try again.', 'danger')
    
    return render_template_string(REGISTER_TEACHER_HTML, form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and check_password_hash(user.password_hash, form.password.data):
            if user.role == form.role.data:
                login_user(user)
                flash(f'Welcome back!', 'success')
                
                if user.role == 'admin':
                    return redirect(url_for('admin_dashboard'))
                elif user.role == 'teacher':
                    return redirect(url_for('teacher_dashboard'))
                else:
                    return redirect(url_for('student_dashboard'))
            else:
                flash('Invalid role selected.', 'danger')
        else:
            flash('Invalid email or password.', 'danger')
    
    return render_template_string(LOGIN_HTML, form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# ============================================
# STUDENT ROUTES
# ============================================

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    student = current_user.student
    today = datetime.now().date()
    
    semester_stopped = is_semester_stopped(student.branch, student.current_semester)
    if semester_stopped and student.is_semester_active:
        student.is_semester_active = False
        db.session.commit()
        flash('Your semester attendance has been closed by administration.', 'info')
    
    sem_data = get_comprehensive_attendance(student)
    today_attendance = Attendance.query.filter_by(
        student_id=student.id, date=today
    ).order_by(Attendance.period).all()
    
    past_semesters = SemesterHistory.query.filter_by(student_id=student.id).order_by(
        SemesterHistory.semester_number
    ).all()
    
    return render_template_string(
        STUDENT_DASHBOARD_HTML,
        student=student,
        today_attendance=today_attendance,
        sem_data=sem_data,
        past_semesters=past_semesters,
        today=today,
        semester_stopped=semester_stopped or not student.is_semester_active
    )

@app.route('/student/reports/semester')
@login_required
def student_semester_report():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    student = current_user.student
    sem_data = get_comprehensive_attendance(student)
    
    return render_template_string(STUDENT_SEMESTER_REPORT_HTML, student=student, sem_data=sem_data)

# ============================================
# TEACHER ROUTES
# ============================================

@app.route('/teacher/dashboard')
@login_required
def teacher_dashboard():
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    teacher = current_user.teacher
    today = datetime.now().date()
    current_year = datetime.now().year
    
    today_status = TeacherAttendance.query.filter_by(
        teacher_id=teacher.id, date=today
    ).first()
    
    yearly_data = get_teacher_yearly_attendance(teacher, current_year)
    subjects = Subject.query.filter_by(branch=teacher.branch).all()
    semester_stopped = is_semester_stopped(teacher.branch, 1)
    
    return render_template_string(
        TEACHER_DASHBOARD_HTML,
        teacher=teacher,
        today_status=today_status,
        yearly_data=yearly_data,
        subjects=subjects,
        today=today,
        semester_stopped=semester_stopped
    )

@app.route('/teacher/mark-attendance', methods=['POST'])
@login_required
def mark_teacher_attendance():
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    
    if not latitude or not longitude:
        return jsonify({'error': 'Location required'}), 400
    
    is_valid_location = verify_location(latitude, longitude)
    teacher = current_user.teacher
    today = datetime.now().date()
    
    existing = TeacherAttendance.query.filter_by(
        teacher_id=teacher.id, date=today
    ).first()
    
    try:
        if existing:
            if existing.check_out is None:
                existing.check_out = datetime.utcnow()
                message = 'Check-out successful'
            else:
                return jsonify({'error': 'Already checked out today'}), 400
        else:
            if not is_valid_location:
                return jsonify({'error': 'You must be within college premises'}), 403
            
            attendance = TeacherAttendance(
                teacher_id=teacher.id,
                date=today,
                check_in=datetime.utcnow(),
                latitude=float(latitude),
                longitude=float(longitude),
                location_verified=True,
                status='present'
            )
            db.session.add(attendance)
            message = 'Check-in successful'
        
        db.session.commit()
        return jsonify({'success': True, 'message': message, 'location_verified': is_valid_location})
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Teacher attendance error: {e}")
        return jsonify({'error': 'Failed to mark attendance'}), 500

@app.route('/teacher/mark-student-attendance', methods=['POST'])
@login_required
def mark_student_attendance():
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    data = request.get_json()
    student_id = data.get('student_id')
    periods = data.get('periods', [])
    status = data.get('status', 'present')
    subject = data.get('subject')
    attendance_type = data.get('attendance_type', 'theory')
    
    if not all([student_id, periods, subject]):
        return jsonify({'error': 'Missing required fields'}), 400
    
    teacher = current_user.teacher
    today = datetime.now().date()
    
    teacher_att = TeacherAttendance.query.filter_by(
        teacher_id=teacher.id, date=today
    ).first()
    
    if not teacher_att or not teacher_att.check_in:
        return jsonify({'error': 'Please mark your attendance first'}), 403
    
    student = Student.query.get(student_id)
    if not student:
        return jsonify({'error': 'Student not found'}), 404
    
    if is_semester_stopped(student.branch, student.current_semester) or not student.is_semester_active:
        return jsonify({'error': 'Semester attendance is closed for this student'}), 403
    
    try:
        for period in periods:
            existing = Attendance.query.filter_by(
                student_id=student_id, date=today, period=period, attendance_type=attendance_type
            ).first()
            
            if existing:
                existing.status = status
                existing.marked_by = teacher.id
                existing.subject = subject
            else:
                attendance = Attendance(
                    student_id=student_id,
                    date=today,
                    period=period,
                    status=status,
                    marked_by=teacher.id,
                    subject=subject,
                    semester_at_time=student.current_semester,
                    attendance_type=attendance_type
                )
                db.session.add(attendance)
        
        db.session.commit()
        
        sem_data = get_comprehensive_attendance(student)
        if sem_data['overall_percentage'] < 75 and sem_data['total_periods'] > 10:
            send_low_attendance_email(student, sem_data['overall_percentage'])
        
        return jsonify({
            'success': True,
            'message': f'Attendance marked for {len(periods)} periods',
            'periods_marked': len(periods)
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Student attendance error: {e}")
        return jsonify({'error': 'Failed to mark attendance'}), 500

@app.route('/teacher/get-subjects/<branch>/<semester>')
@login_required
def get_subjects(branch, semester):
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    subjects = Subject.query.filter_by(branch=branch, semester=int(semester)).all()
    return jsonify([{
        'id': s.id, 'code': s.code, 'name': s.name, 'type': s.subject_type
    } for s in subjects])

@app.route('/teacher/get-students')
@login_required
def get_students():
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    branch = request.args.get('branch')
    semester = request.args.get('semester')
    section = request.args.get('section')
    
    students = Student.query.filter_by(
        branch=branch,
        current_semester=int(semester),
        section=section,
        is_semester_active=True
    ).all()
    
    return jsonify([{
        'id': s.id,
        'register_number': s.register_number,
        'name': s.name
    } for s in students])

# ============================================
# ADMIN ROUTES
# ============================================

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_students = Student.query.count()
    total_teachers = Teacher.query.count()
    today = datetime.now().date()
    
    today_student_attendance = Attendance.query.filter_by(date=today).count()
    today_teacher_attendance = TeacherAttendance.query.filter_by(date=today).count()
    
    stopped_semesters = StoppedSemester.query.filter_by(is_active=True).all()
    admins = User.query.filter_by(role='admin').all()
    recent_logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(10).all()
    
    return render_template_string(
        ADMIN_DASHBOARD_HTML,
        total_students=total_students,
        total_teachers=total_teachers,
        today_student_attendance=today_student_attendance,
        today_teacher_attendance=today_teacher_attendance,
        stopped_semesters=stopped_semesters,
        admins=admins,
        logs=recent_logs
    )

@app.route('/admin/stop-semester', methods=['POST'])
@login_required
@admin_required
def stop_semester():
    form = StopSemesterForm()
    
    if form.validate_on_submit():
        branch = form.branch.data
        semester = int(form.semester.data)
        
        existing = StoppedSemester.query.filter_by(
            branch=branch, semester=semester, is_active=True
        ).first()
        
        if existing:
            flash(f'Semester {semester} for {branch} is already stopped.', 'warning')
            return redirect(url_for('admin_dashboard'))
        
        try:
            stop_record = StoppedSemester(
                branch=branch,
                semester=semester,
                stopped_by=current_user.id,
                is_active=True
            )
            db.session.add(stop_record)
            
            students = Student.query.filter_by(
                branch=branch, current_semester=semester, is_semester_active=True
            ).all()
            
            archived_count = 0
            for student in students:
                sem_data = get_comprehensive_attendance(student)
                
                history = SemesterHistory(
                    student_id=student.id,
                    semester_number=student.current_semester,
                    section=student.section,
                    start_date=student.semester_start_date,
                    end_date=datetime.now().date(),
                    total_theory_classes=sem_data['theory_total'],
                    present_theory_classes=sem_data['theory_present'],
                    total_lab_classes=sem_data['practical_total'],
                    present_lab_classes=sem_data['practical_present'],
                    attendance_percentage=sem_data['overall_percentage'],
                    stopped_by_admin_id=current_user.id,
                    stopped_at=datetime.utcnow()
                )
                db.session.add(history)
                student.is_semester_active = False
                archived_count += 1
            
            log = AdminLog(
                admin_id=current_user.id,
                action=f'Stopped Semester {semester} for {branch}. Archived {archived_count} students.'
            )
            db.session.add(log)
            db.session.commit()
            
            flash(f'Successfully stopped Semester {semester} for {branch}. {archived_count} students archived.', 'success')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Stop semester error: {e}")
            flash('Failed to stop semester.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reactivate-semester/<int:stop_id>', methods=['POST'])
@login_required
@admin_required
def reactivate_semester(stop_id):
    stop_record = StoppedSemester.query.get_or_404(stop_id)
    
    if not stop_record.is_active:
        flash('This semester is already active.', 'warning')
        return redirect(url_for('admin_dashboard'))
    
    try:
        stop_record.is_active = False
        
        log = AdminLog(
            admin_id=current_user.id,
            action=f'Reactivated Semester {stop_record.semester} for {stop_record.branch}'
        )
        db.session.add(log)
        db.session.commit()
        
        flash(f'Semester {stop_record.semester} for {stop_record.branch} has been reactivated.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Reactivate semester error: {e}")
        flash('Failed to reactivate semester.', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/add-subject', methods=['GET', 'POST'])
@login_required
@admin_required
def add_subject():
    form = SubjectForm()
    
    if form.validate_on_submit():
        try:
            subject = Subject(
                code=form.code.data,
                name=form.name.data,
                branch=form.branch.data,
                semester=int(form.semester.data),
                subject_type=form.subject_type.data
            )
            db.session.add(subject)
            db.session.commit()
            flash(f'Subject {form.name.data} added successfully.', 'success')
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Add subject error: {e}")
            flash('Failed to add subject.', 'danger')
    
    subjects = Subject.query.order_by(Subject.branch, Subject.semester).all()
    return render_template_string(ADMIN_SUBJECTS_HTML, form=form, subjects=subjects)

@app.route('/admin/reports/students/semester')
@login_required
@admin_required
def admin_student_semester_report():
    branch = request.args.get('branch', 'all')
    semester = int(request.args.get('semester', 1))
    section = request.args.get('section', 'all')
    
    query = Student.query.filter_by(current_semester=semester)
    if branch != 'all':
        query = query.filter_by(branch=branch)
    if section != 'all':
        query = query.filter_by(section=section)
    
    students = query.all()
    student_data = [{'student': s, 'data': get_comprehensive_attendance(s)} for s in students]
    
    return render_template_string(
        ADMIN_STUDENT_SEMESTER_HTML,
        student_data=student_data,
        semester=semester,
        branch=branch,
        section=section,
        branches=['ECE', 'CSE', 'EEE', 'CIVIL', 'MECH', 'DS', 'AIML'],
        sections=['A', 'B', 'C']
    )

# ============================================
# HTML TEMPLATES (Inline for single-file deployment)
# ============================================

BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Attendance System{% endblock %} - Sree Vahini Institute</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .card {
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 20px;
        }
        .btn {
            display: inline-block;
            padding: 12px 24px;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            border: none;
            cursor: pointer;
            font-size: 16px;
            transition: all 0.3s;
        }
        .btn:hover { background: #5568d3; transform: translateY(-2px); }
        .btn-success { background: #48bb78; }
        .btn-danger { background: #f56565; }
        .btn-warning { background: #ed8936; }
        .btn-info { background: #4299e1; }
        .form-group { margin-bottom: 20px; }
        .form-group label { display: block; margin-bottom: 5px; font-weight: 600; color: #333; }
        .form-control {
            width: 100%;
            padding: 12px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 16px;
        }
        .form-control:focus { outline: none; border-color: #667eea; }
        .alert { padding: 15px; border-radius: 8px; margin-bottom: 20px; }
        .alert-success { background: #c6f6d5; color: #22543d; }
        .alert-danger { background: #fed7d7; color: #742a2a; }
        .alert-info { background: #bee3f8; color: #2a4365; }
        .navbar {
            background: rgba(255,255,255,0.95);
            padding: 15px 0;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }
        .navbar-content {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .nav-links a {
            margin-left: 20px;
            text-decoration: none;
            color: #333;
            font-weight: 500;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 25px;
            border-radius: 12px;
            text-align: center;
        }
        .stat-number { font-size: 36px; font-weight: bold; margin-bottom: 5px; }
        .stat-label { font-size: 14px; opacity: 0.9; }
        table { width: 100%; border-collapse: collapse; margin-top: 20px; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #e2e8f0; }
        th { background: #f7fafc; font-weight: 600; color: #4a5568; }
        .badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
        }
        .badge-success { background: #c6f6d5; color: #22543d; }
        .badge-danger { background: #fed7d7; color: #742a2a; }
        .period-selector { display: flex; gap: 10px; flex-wrap: wrap; margin: 10px 0; }
        .period-checkbox {
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 8px 12px;
            background: #f7fafc;
            border-radius: 6px;
            cursor: pointer;
        }
        .period-checkbox.selected { background: #c6f6d5; border: 2px solid #48bb78; }
        .stopped-banner {
            background: #fed7d7;
            color: #742a2a;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
            text-align: center;
            font-weight: bold;
        }
        .filter-bar {
            background: #f7fafc;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            align-items: flex-end;
        }
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: 1fr; }
            .filter-bar { flex-direction: column; }
        }
    </style>
    {% block extra_css %}{% endblock %}
</head>
<body>
    {% block navbar %}
    <nav class="navbar">
        <div class="navbar-content">
            <div class="logo"><strong>SVIST Attendance</strong></div>
            <div class="nav-links">
                {% if current_user.is_authenticated %}
                    {% if current_user.role == 'student' %}
                        <a href="{{ url_for('student_dashboard') }}">Dashboard</a>
                    {% elif current_user.role == 'teacher' %}
                        <a href="{{ url_for('teacher_dashboard') }}">Dashboard</a>
                    {% elif current_user.role == 'admin' %}
                        <a href="{{ url_for('admin_dashboard') }}">Admin Panel</a>
                    {% endif %}
                    <a href="{{ url_for('logout') }}">Logout</a>
                {% else %}
                    <a href="{{ url_for('login') }}">Login</a>
                    <a href="{{ url_for('register_student') }}">Register Student</a>
                    <a href="{{ url_for('register_teacher') }}">Register Faculty</a>
                {% endif %}
            </div>
        </div>
    </nav>
    {% endblock %}
    
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
    
    {% block extra_js %}{% endblock %}
</body>
</html>
"""

INDEX_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Home") \
    .replace("{% block content %}{% endblock %}", """
    <div class="card" style="text-align: center; padding: 60px 20px;">
        <h1 style="margin-bottom: 20px; color: #333;">Sree Vahini Institute of Science and Technology</h1>
        <h2 style="margin-bottom: 30px; color: #666;">Digital Attendance Management System</h2>
        <p style="margin-bottom: 30px; color: #666; font-size: 18px;">
            Comprehensive attendance tracking with subject-wise breakdown, Labs/CRT/Workshops, and admin-controlled semester management.
        </p>
        <div style="display: flex; gap: 15px; justify-content: center; flex-wrap: wrap;">
            <a href="{{ url_for('login') }}" class="btn">Login</a>
            <a href="{{ url_for('register_student') }}" class="btn btn-success">Register as Student</a>
            <a href="{{ url_for('register_teacher') }}" class="btn btn-warning">Register as Faculty</a>
        </div>
    </div>
""")

LOGIN_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Login") \
    .replace("{% block content %}{% endblock %}", """
    <div class="card" style="max-width: 500px; margin: 0 auto;">
        <h2 style="text-align: center; margin-bottom: 30px;">Login</h2>
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">
                {{ form.email.label }}
                {{ form.email(class="form-control") }}
            </div>
            <div class="form-group">
                {{ form.password.label }}
                {{ form.password(class="form-control") }}
            </div>
            <div class="form-group">
                {{ form.role.label }}
                {{ form.role(class="form-control") }}
            </div>
            <div style="text-align: center;">
                {{ form.submit(class="btn", style="width: 100%;") }}
            </div>
        </form>
    </div>
""")

REGISTER_STUDENT_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Student Registration") \
    .replace("{% block content %}{% endblock %}", """
    <div class="card" style="max-width: 600px; margin: 0 auto;">
        <h2 style="text-align: center; margin-bottom: 30px;">Student Registration</h2>
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">{{ form.name.label }}{{ form.name(class="form-control") }}</div>
            <div class="form-group">{{ form.register_number.label }}{{ form.register_number(class="form-control") }}</div>
            <div class="form-group">{{ form.email.label }}{{ form.email(class="form-control") }}</div>
            <div class="form-group">{{ form.password.label }}{{ form.password(class="form-control") }}</div>
            <div class="form-group">{{ form.branch.label }}{{ form.branch(class="form-control") }}</div>
            <div class="form-group">{{ form.semester.label }}{{ form.semester(class="form-control") }}</div>
            <div class="form-group">{{ form.section.label }}{{ form.section(class="form-control") }}</div>
            <div class="form-group">{{ form.phone.label }}{{ form.phone(class="form-control") }}</div>
            <div style="text-align: center;">{{ form.submit(class="btn btn-success", style="width: 100%;") }}</div>
        </form>
    </div>
""")

REGISTER_TEACHER_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Faculty Registration") \
    .replace("{% block content %}{% endblock %}", """
    <div class="card" style="max-width: 600px; margin: 0 auto;">
        <h2 style="text-align: center; margin-bottom: 30px;">Faculty Registration</h2>
        <form method="POST" id="teacherForm">
            {{ form.hidden_tag() }}
            <div class="form-group">{{ form.name.label }}{{ form.name(class="form-control") }}</div>
            <div class="form-group">{{ form.employee_id.label }}{{ form.employee_id(class="form-control") }}</div>
            <div class="form-group">{{ form.email.label }}{{ form.email(class="form-control") }}</div>
            <div class="form-group">{{ form.password.label }}{{ form.password(class="form-control") }}</div>
            <div class="form-group">{{ form.branch.label }}{{ form.branch(class="form-control") }}</div>
            <div class="form-group">{{ form.qualification.label }}{{ form.qualification(class="form-control") }}</div>
            <div class="form-group">
                {{ form.staff_category.label }}
                {{ form.staff_category(class="form-control", onchange="updateRoles()") }}
            </div>
            <div class="form-group">{{ form.role.label }}{{ form.role(class="form-control") }}</div>
            <div style="text-align: center;">{{ form.submit(class="btn btn-success", style="width: 100%;") }}</div>
        </form>
    </div>
    <script>
        function updateRoles() {
            const category = document.getElementById('staff_category').value;
            fetch('/get-teacher-roles/' + category)
                .then(r => r.json())
                .then(roles => {
                    const select = document.getElementById('role');
                    select.innerHTML = '';
                    roles.forEach(role => {
                        const option = document.createElement('option');
                        option.value = role;
                        option.textContent = role;
                        select.appendChild(option);
                    });
                });
        }
    </script>
""")

STUDENT_DASHBOARD_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Student Dashboard") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Welcome, {{ student.name }}</h2>
    <div style="margin-bottom: 20px;">
        <span class="badge badge-success">{{ student.branch }}</span>
        <span class="badge badge-info">Semester {{ student.current_semester }}</span>
        <span class="badge badge-info">Section {{ student.section }}</span>
    </div>
    
    {% if semester_stopped %}
    <div class="stopped-banner">⚠️ Your semester attendance has been closed</div>
    {% endif %}
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{{ "%.1f"|format(sem_data.overall_percentage) }}%</div>
            <div class="stat-label">Overall Attendance</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
            <div class="stat-number">{{ sem_data.theory_percentage|round(1) }}%</div>
            <div class="stat-label">Theory</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
            <div class="stat-number">{{ sem_data.practical_percentage|round(1) }}%</div>
            <div class="stat-label">Practical</div>
        </div>
    </div>
    
    <div class="card">
        <h3>Today's Attendance</h3>
        {% if today_attendance %}
        <table>
            <tr><th>Period</th><th>Subject</th><th>Status</th></tr>
            {% for att in today_attendance %}
            <tr>
                <td>{{ att.period }}</td>
                <td>{{ att.subject or 'N/A' }}</td>
                <td><span class="badge badge-{{ 'success' if att.status == 'present' else 'danger' }}">{{ att.status.upper() }}</span></td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p>No attendance marked today.</p>
        {% endif %}
    </div>
""")

TEACHER_DASHBOARD_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Faculty Dashboard") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Welcome, {{ teacher.name }}</h2>
    <div style="margin-bottom: 20px;">
        <span class="badge badge-info">{{ teacher.role }}</span>
        <span class="badge badge-secondary">{{ teacher.branch }}</span>
    </div>
    
    {% if semester_stopped %}
    <div class="stopped-banner">⚠️ Semester attendance is currently stopped</div>
    {% endif %}
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{{ "%.1f"|format(yearly_data.percentage) }}%</div>
            <div class="stat-label">Yearly Attendance</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
            <div class="stat-number">{{ yearly_data.total_days_present }}</div>
            <div class="stat-label">Days Present</div>
        </div>
    </div>
    
    <div class="card" style="text-align: center;">
        <h3>Your Attendance Today</h3>
        {% if today_status and today_status.check_in %}
            <div style="padding: 20px; background: #c6f6d5; border-radius: 8px;">
                <p style="color: #22543d; font-size: 18px; font-weight: bold;">✓ Checked In at {{ today_status.check_in.strftime('%H:%M') }}</p>
                {% if today_status.check_out %}
                    <p>Checked Out at {{ today_status.check_out.strftime('%H:%M') }}</p>
                {% else %}
                    <button onclick="markAttendance()" class="btn btn-danger">Check Out</button>
                {% endif %}
            </div>
        {% else %}
            <button onclick="markAttendance()" class="btn btn-success">Mark Attendance (GPS)</button>
        {% endif %}
    </div>
    
    {% if not semester_stopped %}
    <div class="card">
        <h3>Mark Student Attendance</h3>
        <div class="form-group">
            <label>Section</label>
            <select id="studentSection" class="form-control">
                <option value="">Select</option>
                <option value="A">A</option>
                <option value="B">B</option>
                <option value="C">C</option>
            </select>
        </div>
        <div class="form-group">
            <label>Semester</label>
            <select id="studentSemester" class="form-control" onchange="loadSubjects()">
                <option value="">Select</option>
                {% for i in range(1, 9) %}
                <option value="{{ i }}">Semester {{ i }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="form-group">
            <label>Subject</label>
            <select id="subjectSelect" class="form-control"></select>
        </div>
        <div class="form-group">
            <label>Type</label>
            <select id="attendanceType" class="form-control">
                <option value="theory">Theory</option>
                <option value="lab">Lab</option>
                <option value="crt">CRT</option>
                <option value="workshop">Workshop</option>
            </select>
        </div>
        <div class="form-group">
            <label>Periods</label>
            <div class="period-selector" id="periodSelector">
                {% for i in range(1, 9) %}
                <div class="period-checkbox" onclick="togglePeriod(this)">
                    <input type="checkbox" value="{{ i }}" id="p{{ i }}">
                    <label for="p{{ i }}">P{{ i }}</label>
                </div>
                {% endfor %}
            </div>
        </div>
        <button onclick="loadStudents()" class="btn btn-info">Load Students</button>
        <div id="studentsContainer" style="margin-top: 20px; display: none;">
            <table id="studentsTable">
                <thead><tr><th>S.No</th><th>Roll No</th><th>Name</th><th>Status</th><th>Action</th></tr></thead>
                <tbody id="studentsTableBody"></tbody>
            </table>
        </div>
    </div>
    {% endif %}
""") \
    .replace("{% block extra_js %}{% endblock %}", """
    <script>
        let selectedPeriods = [];
        function togglePeriod(el) {
            const cb = el.querySelector('input');
            cb.checked = !cb.checked;
            el.classList.toggle('selected', cb.checked);
            selectedPeriods = Array.from(document.querySelectorAll('.period-checkbox.selected input')).map(i => i.value);
        }
        function markAttendance() {
            navigator.geolocation.getCurrentPosition(pos => {
                fetch('/teacher/mark-attendance', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({latitude: pos.coords.latitude, longitude: pos.coords.longitude})
                }).then(r => r.json()).then(d => {
                    alert(d.message || d.error);
                    if(d.success) location.reload();
                });
            }, err => alert('Location access denied'));
        }
        function loadSubjects() {
            const sem = document.getElementById('studentSemester').value;
            fetch(`/teacher/get-subjects/{{ teacher.branch }}/${sem}`)
                .then(r => r.json())
                .then(subjects => {
                    const sel = document.getElementById('subjectSelect');
                    sel.innerHTML = '<option value="">Select Subject</option>';
                    subjects.forEach(s => {
                        const opt = document.createElement('option');
                        opt.value = s.name;
                        opt.textContent = `${s.code} - ${s.name}`;
                        sel.appendChild(opt);
                    });
                });
        }
        function loadStudents() {
            const section = document.getElementById('studentSection').value;
            const semester = document.getElementById('studentSemester').value;
            if(!section || !semester || selectedPeriods.length === 0) {
                alert('Please select section, semester, and periods');
                return;
            }
            fetch(`/teacher/get-students?branch={{ teacher.branch }}&semester=${semester}&section=${section}`)
                .then(r => r.json())
                .then(students => {
                    const tbody = document.getElementById('studentsTableBody');
                    tbody.innerHTML = '';
                    students.forEach((s, i) => {
                        const row = document.createElement('tr');
                        row.innerHTML = `
                            <td>${i+1}</td>
                            <td>${s.register_number}</td>
                            <td>${s.name}</td>
                            <td id="status-${s.id}">-</td>
                            <td>
                                <button onclick="markStudent(${s.id}, 'present')" class="btn btn-success" style="padding:5px 10px;font-size:12px;">P</button>
                                <button onclick="markStudent(${s.id}, 'absent')" class="btn btn-danger" style="padding:5px 10px;font-size:12px;">A</button>
                            </td>
                        `;
                        tbody.appendChild(row);
                    });
                    document.getElementById('studentsContainer').style.display = 'block';
                });
        }
        function markStudent(id, status) {
            const subject = document.getElementById('subjectSelect').value;
            const type = document.getElementById('attendanceType').value;
            fetch('/teacher/mark-student-attendance', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({student_id: id, periods: selectedPeriods, status, subject, attendance_type: type})
            }).then(r => r.json()).then(d => {
                if(d.success) {
                    document.getElementById(`status-${id}`).innerHTML = `<span class="badge badge-${status === 'present' ? 'success' : 'danger'}">${status.toUpperCase()}</span>`;
                } else {
                    alert(d.error);
                }
            });
        }
    </script>
""")

ADMIN_DASHBOARD_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Admin Dashboard") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Administrator Dashboard</h2>
    
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{{ total_students }}</div>
            <div class="stat-label">Total Students</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
            <div class="stat-number">{{ total_teachers }}</div>
            <div class="stat-label">Total Faculty</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
            <div class="stat-number">{{ today_student_attendance }}</div>
            <div class="stat-label">Today's Records</div>
        </div>
        <div class="stat-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
            <div class="stat-number">{{ today_teacher_attendance }}</div>
            <div class="stat-label">Faculty Present</div>
        </div>
    </div>
    
    <div class="card">
        <h3>Semester Control</h3>
        <form method="post" action="{{ url_for('stop_semester') }}">
            <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
            <div class="filter-bar">
                <div class="form-group" style="margin-bottom:0;">
                    <label>Branch</label>
                    <select name="branch" class="form-control" required>
                        {% for code, name in [('ECE','ECE'),('CSE','CSE'),('EEE','EEE'),('CIVIL','CIVIL'),('MECH','MECH'),('DS','DS'),('AIML','AIML')] %}
                        <option value="{{ code }}">{{ name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div class="form-group" style="margin-bottom:0;">
                    <label>Semester</label>
                    <select name="semester" class="form-control" required>
                        {% for i in range(1, 9) %}
                        <option value="{{ i }}">Semester {{ i }}</option>
                        {% endfor %}
                    </select>
                </div>
                <button type="submit" class="btn btn-danger" onclick="return confirm('Stop this semester? This archives all data.')">Stop Semester</button>
            </div>
        </form>
        
        {% if stopped_semesters %}
        <h4 style="margin-top:20px;">Stopped Semesters</h4>
        <table>
            <tr><th>Branch</th><th>Semester</th><th>Stopped At</th><th>Action</th></tr>
            {% for stop in stopped_semesters %}
            <tr>
                <td>{{ stop.branch }}</td>
                <td>{{ stop.semester }}</td>
                <td>{{ stop.stopped_at.strftime('%Y-%m-%d') }}</td>
                <td>
                    <form method="post" action="{{ url_for('reactivate_semester', stop_id=stop.id) }}" style="display:inline;">
                        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                        <button type="submit" class="btn btn-warning" style="padding:5px 10px;font-size:12px;">Reactivate</button>
                    </form>
                </td>
            </tr>
            {% endfor %}
        </table>
        {% endif %}
    </div>
    
    <div class="card">
        <h3>Quick Links</h3>
        <a href="{{ url_for('add_subject') }}" class="btn btn-success">Manage Subjects</a>
        <a href="{{ url_for('admin_student_semester_report') }}" class="btn btn-info">View Reports</a>
    </div>
""")

STUDENT_SEMESTER_REPORT_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Semester Report") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Semester Attendance Report</h2>
    <div class="card">
        <h3>Summary</h3>
        <p><strong>Theory:</strong> {{ sem_data.theory_present }}/{{ sem_data.theory_total }} ({{ sem_data.theory_percentage|round(2) }}%)</p>
        <p><strong>Practical:</strong> {{ sem_data.practical_present }}/{{ sem_data.practical_total }} ({{ sem_data.practical_percentage|round(2) }}%)</p>
        <p><strong>Overall:</strong> {{ sem_data.present_periods }}/{{ sem_data.total_periods }} ({{ sem_data.overall_percentage|round(2) }}%)</p>
    </div>
    <div class="card">
        <h3>Subject-wise Breakdown</h3>
        <table>
            <tr><th>Subject</th><th>Type</th><th>Present/Total</th><th>Percentage</th></tr>
            {% for subject, data in sem_data.subject_wise.items() %}
            <tr>
                <td>{{ subject }}</td>
                <td>{{ data.type }}</td>
                <td>{{ data.present }}/{{ data.total }}</td>
                <td>{{ data.percentage|round(2) }}%</td>
            </tr>
            {% endfor %}
        </table>
    </div>
""")

ADMIN_SUBJECTS_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Manage Subjects") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Manage Subjects</h2>
    <div class="card">
        <h3>Add New Subject</h3>
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">{{ form.code.label }}{{ form.code(class="form-control") }}</div>
            <div class="form-group">{{ form.name.label }}{{ form.name(class="form-control") }}</div>
            <div class="form-group">{{ form.branch.label }}{{ form.branch(class="form-control") }}</div>
            <div class="form-group">{{ form.semester.label }}{{ form.semester(class="form-control") }}</div>
            <div class="form-group">{{ form.subject_type.label }}{{ form.subject_type(class="form-control") }}</div>
            {{ form.submit(class="btn btn-success") }}
        </form>
    </div>
    <div class="card">
        <h3>Existing Subjects</h3>
        <table>
            <tr><th>Code</th><th>Name</th><th>Branch</th><th>Semester</th><th>Type</th></tr>
            {% for s in subjects %}
            <tr>
                <td>{{ s.code }}</td>
                <td>{{ s.name }}</td>
                <td>{{ s.branch }}</td>
                <td>{{ s.semester }}</td>
                <td>{{ s.subject_type }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
""")

ADMIN_STUDENT_SEMESTER_HTML = BASE_TEMPLATE.replace("{% block title %}Attendance System{% endblock %}", "Student Reports") \
    .replace("{% block content %}{% endblock %}", """
    <h2>Student Semester Reports</h2>
    <div class="card">
        <form method="get" class="filter-bar">
            <div class="form-group" style="margin-bottom:0;">
                <label>Branch</label>
                <select name="branch" class="form-control">
                    <option value="all">All</option>
                    {% for b in branches %}
                    <option value="{{ b }}" {{ 'selected' if branch == b else '' }}>{{ b }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
                <label>Semester</label>
                <select name="semester" class="form-control">
                    {% for i in range(1, 9) %}
                    <option value="{{ i }}" {{ 'selected' if semester == i else '' }}>Semester {{ i }}</option>
                    {% endfor %}
                </select>
            </div>
            <div class="form-group" style="margin-bottom:0;">
                <label>Section</label>
                <select name="section" class="form-control">
                    <option value="all">All</option>
                    {% for s in sections %}
                    <option value="{{ s }}" {{ 'selected' if section == s else '' }}>{{ s }}</option>
                    {% endfor %}
                </select>
            </div>
            <button type="submit" class="btn btn-info">Filter</button>
            <a href="{{ url_for('admin_export_students_semester', branch=branch, semester=semester, section=section) }}" class="btn btn-success">Export PDF</a>
        </form>
    </div>
    <div class="card">
        <table>
            <tr>
                <th>Roll No</th>
                <th>Name</th>
                <th>Section</th>
                <th>Theory %</th>
                <th>Practical %</th>
                <th>Overall %</th>
            </tr>
            {% for item in student_data %}
            <tr>
                <td>{{ item.student.register_number }}</td>
                <td>{{ item.student.name }}</td>
                <td>{{ item.student.section }}</td>
                <td>{{ item.data.theory_percentage|round(1) }}%</td>
                <td>{{ item.data.practical_percentage|round(1) }}%</td>
                <td><strong>{{ item.data.overall_percentage|round(1) }}%</strong></td>
            </tr>
            {% endfor %}
        </table>
    </div>
""")

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template_string("""
        <div class="container" style="text-align:center;padding-top:50px;">
            <h1>404 - Page Not Found</h1>
            <a href="/" class="btn">Go Home</a>
        </div>
    """), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template_string("""
        <div class="container" style="text-align:center;padding-top:50px;">
            <h1>500 - Internal Server Error</h1>
            <p>Something went wrong. Please try again later.</p>
            <a href="/" class="btn">Go Home</a>
        </div>
    """), 500

# ============================================
# DATABASE INITIALIZATION
# ============================================

def init_db():
    with app.app_context():
        try:
            db.create_all()
            
            # Create default admin
            admin_email = os.environ.get('ADMIN_EMAIL', 'admin@svist.edu.in')
            admin_password = os.environ.get('ADMIN_PASSWORD', 'admin123')
            
            if not User.query.filter_by(email=admin_email).first():
                admin_user = User(
                    email=admin_email,
                    password_hash=generate_password_hash(admin_password),
                    role='admin'
                )
                db.session.add(admin_user)
                db.session.commit()
                app.logger.info(f"Default admin created: {admin_email}")
        except Exception as e:
            app.logger.error(f"Database initialization error: {e}")
            raise

if __name__ == '__main__':
    init_db()
    # Railway.app provides PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
else:
    # For WSGI (Gunicorn)
    init_db()