#!/usr/bin/env python3
# ============================================
# SVIST ATTENDANCE MANAGEMENT SYSTEM
# Production Version for Railway.app + TiDB
# ============================================

import pymysql
pymysql.install_as_MySQLdb()

import os
import sys
from datetime import datetime, timedelta
from functools import wraps
from io import BytesIO
from calendar import monthrange

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_file, render_template_string, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_mail import Mail, Message
from flask_wtf import FlaskForm, CSRFProtect
from wtforms import StringField, PasswordField, SelectField, IntegerField, SubmitField, EmailField, DateField
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
database_url = os.environ.get('DATABASE_URL')

# Ensure we use pymysql driver
if database_url and database_url.startswith('mysql://'):
    database_url = database_url.replace('mysql://', 'mysql+pymysql://', 1)
elif database_url and not database_url.startswith('mysql+pymysql://'):
    database_url = 'mysql+pymysql://' + database_url

app.config['SQLALCHEMY_DATABASE_URI'] = database_url

# Railway.app - Simplified engine options (no SSL CA needed for TiDB Serverless)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 5,
    'max_overflow': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True,
    'connect_args': {
        'ssl_disabled': False,  # Force SSL on
        'ssl': {
            'ca': None,  # Use system CA certificates
            'check_hostname': True,
            'ssl_mode': 'VERIFY_IDENTITY'
        }
    }
}

# Mail Configuration
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'true').lower() == 'true'
app.config['MAIL_USERNAME'] = os.environ.get('svistattendance7@gmail.com')
app.config['MAIL_PASSWORD'] = os.environ.get('jjdz rizt ccli ojsr')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('svistattendance7@gmail.com')

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

# Make datetime and other utilities available in all templates
@app.context_processor
def inject_utilities():
    return dict(
        datetime=datetime,
        str=str,
        int=int
    )

# ============================================
# DATABASE MODELS
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

ALL_BRANCHES = ['ECE', 'CSE', 'EEE', 'CIVIL', 'MECH', 'DS', 'AIML']

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

# FIXED: Removed multiple JOINs issue and ensured sorting by register_number
def get_daily_attendance(branch, semester, section, date):
    """Get daily attendance report - sorted by register_number"""
    # Start with base query joining Student once
    query = db.session.query(Attendance, Student).join(
        Student, Attendance.student_id == Student.id
    ).filter(Attendance.date == date)
    
    # Apply filters without creating additional joins
    if branch != 'all':
        query = query.filter(Student.branch == branch)
    if semester != 'all':
        query = query.filter(Student.current_semester == int(semester))
    if section != 'all':
        query = query.filter(Student.section == section)
    
    # FIXED: Sort by register_number
    query = query.order_by(Student.register_number.asc())
    
    results = query.all()
    
    # Group by student
    student_attendance = {}
    for att, student in results:
        student_id = student.id
        if student_id not in student_attendance:
            student_attendance[student_id] = {
                'student': student,
                'periods': [],
                'present_count': 0,
                'total_count': 0
            }
        student_attendance[student_id]['periods'].append({
            'period': att.period,
            'status': att.status,
            'subject': att.subject,
            'type': att.attendance_type
        })
        student_attendance[student_id]['total_count'] += 1
        if att.status == 'present':
            student_attendance[student_id]['present_count'] += 1
    
    # Return sorted by register_number
    return dict(sorted(student_attendance.items(), 
                      key=lambda x: x[1]['student'].register_number))

# FIXED: Removed multiple JOINs issue and ensured sorting by register_number
def get_monthly_attendance(branch, semester, section, month, year):
    """Get monthly attendance report - sorted by register_number"""
    # FIXED: Convert month and year to integers properly
    month = int(month)
    year = int(year)
    
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    # Build base query - FIXED: Sort by register_number
    query = Student.query.filter_by(is_semester_active=True)
    
    if branch != 'all':
        query = query.filter_by(branch=branch)
    if semester != 'all':
        query = query.filter_by(current_semester=int(semester))
    if section != 'all':
        query = query.filter_by(section=section)
    
    # FIXED: Sort by register_number
    query = query.order_by(Student.register_number.asc())
    
    students = query.all()
    monthly_data = []
    
    for student in students:
        attendances = Attendance.query.filter(
            Attendance.student_id == student.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        ).all()
        
        theory_present = sum(1 for a in attendances if a.attendance_type == 'theory' and a.status == 'present')
        theory_total = sum(1 for a in attendances if a.attendance_type == 'theory')
        practical_present = sum(1 for a in attendances if a.attendance_type in ['lab', 'crt', 'workshop'] and a.status == 'present')
        practical_total = sum(1 for a in attendances if a.attendance_type in ['lab', 'crt', 'workshop'])
        
        monthly_data.append({
            'student': student,
            'theory_present': theory_present,
            'theory_total': theory_total,
            'practical_present': practical_present,
            'practical_total': practical_total,
            'overall_percentage': ((theory_present + practical_present) / (theory_total + practical_total) * 100) if (theory_total + practical_total) > 0 else 0
        })
    
    # Already sorted by register_number due to query order_by
    return monthly_data, start_date, end_date

# NEW: Semester-wise attendance for admin - FIXED: Sort by register_number
# NEW: Semester-wise attendance for admin - FIXED: Sort by register_number and date range
def get_semester_attendance(branch, semester, section):
    """Get semester-wise attendance report for admin - each student has their own timeline"""
    query = Student.query
    
    if branch != 'all':
        query = query.filter_by(branch=branch)
    if semester != 'all':
        query = query.filter_by(current_semester=int(semester))
    if section != 'all':
        query = query.filter_by(section=section)
    
    query = query.order_by(Student.register_number.asc())
    students = query.all()
    semester_data = []
    
    for student in students:
        # Each student has their OWN timeline: their registration date to their stop date
        start_date = student.semester_start_date  # When they registered
        
        # Check if this specific student's semester is stopped
        # (either by branch/semester stop or individual stop)
        end_date = datetime.now().date()
        
        # Check if branch/semester is currently stopped
        stopped = StoppedSemester.query.filter_by(
            branch=student.branch,
            semester=student.current_semester,
            is_active=True
        ).first()
        
        if stopped:
            # Semester is stopped - this student's attendance ends at stop date
            end_date = stopped.stopped_at.date()
        elif not student.is_semester_active:
            # Student's semester was stopped individually (archived)
            history = SemesterHistory.query.filter_by(
                student_id=student.id,
                semester_number=student.current_semester
            ).order_by(SemesterHistory.stopped_at.desc()).first()
            
            if history:
                end_date = history.end_date
        
        # Calculate attendance for this student's specific date range
        attendances = Attendance.query.filter(
            Attendance.student_id == student.id,
            Attendance.semester_at_time == student.current_semester,
            Attendance.date >= start_date,      # From their registration
            Attendance.date <= end_date         # To stop date or today
        ).all()
        
        theory_present = sum(1 for a in attendances if a.attendance_type == 'theory' and a.status == 'present')
        theory_total = sum(1 for a in attendances if a.attendance_type == 'theory')
        practical_present = sum(1 for a in attendances if a.attendance_type in ['lab', 'crt', 'workshop'] and a.status == 'present')
        practical_total = sum(1 for a in attendances if a.attendance_type in ['lab', 'crt', 'workshop'])
        
        total_present = theory_present + practical_present
        total_classes = theory_total + practical_total
        
        semester_data.append({
            'student': student,
            'theory_present': theory_present,
            'theory_total': theory_total,
            'theory_percentage': (theory_present / theory_total * 100) if theory_total > 0 else 0,
            'practical_present': practical_present,
            'practical_total': practical_total,
            'practical_percentage': (practical_present / practical_total * 100) if practical_total > 0 else 0,
            'total_present': total_present,
            'total_classes': total_classes,
            'overall_percentage': (total_present / total_classes * 100) if total_classes > 0 else 0,
            'start_date': start_date,  # Show individual start date
            'end_date': end_date,      # Show individual end date
            'is_active': student.is_semester_active
        })
    
    return semester_data

# FIXED: Removed multiple JOINs issue for teacher reports
def get_teacher_attendance_report(branch=None, name=None, month=None, year=None):
    """Get teacher attendance report for admin"""
    query = Teacher.query
    
    if branch and branch != 'all':
        query = query.filter_by(branch=branch)
    if name:
        query = query.filter(Teacher.name.ilike(f'%{name}%'))
    
    teachers = query.all()
    report_data = []
    
    for teacher in teachers:
        if month and year:
            # FIXED: Convert to integers
            month = int(month)
            year = int(year)
            start_date = datetime(year, month, 1).date()
            if month == 12:
                end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
            
            attendances = TeacherAttendance.query.filter(
                TeacherAttendance.teacher_id == teacher.id,
                TeacherAttendance.date >= start_date,
                TeacherAttendance.date <= end_date
            ).all()
        else:
            attendances = TeacherAttendance.query.filter_by(teacher_id=teacher.id).all()
        
        present_days = sum(1 for a in attendances if a.status == 'present')
        
        report_data.append({
            'teacher': teacher,
            'present_days': present_days,
            'total_days': len(attendances),
            'attendances': attendances
        })
    
    return report_data

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
        
        # Check if this branch/semester is currently stopped
        branch = form.branch.data
        semester = int(form.semester.data)
        
        stopped = StoppedSemester.query.filter_by(
            branch=branch,
            semester=semester,
            is_active=True
        ).first()
        
        if stopped:
            flash(f'Semester {semester} for {branch} is currently closed. Please contact administration.', 'danger')
            return redirect(url_for('register_student'))
        
        # ✅ Semester is open (either never stopped or was reactivated) - allow registration
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
                branch=branch,
                current_semester=semester,
                section=form.section.data,
                phone=form.phone.data,
                semester_start_date=datetime.now().date(),  # ✅ Their own start date
                is_semester_active=True  # ✅ Active for this new student only
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        
        if user and check_password_hash(user.password_hash, form.password.data):
            # Check if role matches
            if user.role != form.role.data:
                flash(f'Invalid role selected. You are registered as a {user.role}.', 'danger')
                return redirect(url_for('login'))
            
            login_user(user)
            flash('Login successful!', 'success')
            
            # Redirect based on role
            if user.role == 'admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'teacher':
                return redirect(url_for('teacher_dashboard'))
            else:  # student
                return redirect(url_for('student_dashboard'))
        else:
            flash('Invalid email or password.', 'danger')
    
    return render_template_string(LOGIN_HTML, form=form)

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
    
    # ✅ FIXED: Pass TEACHER_ROLES to template
    return render_template_string(REGISTER_TEACHER_HTML, form=form, TEACHER_ROLES=TEACHER_ROLES)

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

# Student Daily Report - Only their own attendance
@app.route('/student/reports/daily')
@login_required
def student_daily_report():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    student = current_user.student
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    attendances = Attendance.query.filter_by(
        student_id=student.id,
        date=report_date
    ).order_by(Attendance.period).all()
    
    return render_template_string(STUDENT_DAILY_REPORT_HTML, 
                                  student=student, 
                                  attendances=attendances, 
                                  date=report_date)

# Student Monthly Report - Only their own attendance
@app.route('/student/reports/monthly')
@login_required
def student_monthly_report():
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    student = current_user.student
    month = int(request.args.get('month', datetime.now().month))
    year = int(request.args.get('year', datetime.now().year))
    
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    attendances = Attendance.query.filter(
        Attendance.student_id == student.id,
        Attendance.date >= start_date,
        Attendance.date <= end_date
    ).order_by(Attendance.date, Attendance.period).all()
    
    # Calculate statistics
    total_present = sum(1 for a in attendances if a.status == 'present')
    total_classes = len(attendances)
    
    return render_template_string(STUDENT_MONTHLY_REPORT_HTML,
                                  student=student,
                                  attendances=attendances,
                                  month=month,
                                  year=year,
                                  month_name=datetime(year, month, 1).strftime('%B'),
                                  total_present=total_present,
                                  total_classes=total_classes,
                                  percentage=(total_present/total_classes*100) if total_classes > 0 else 0)

# Student Semester Report - Only their own attendance
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
    
    return render_template_string(
        TEACHER_DASHBOARD_HTML,
        teacher=teacher,
        today_status=today_status,
        yearly_data=yearly_data,
        today=today
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
    
    # Check if semester is stopped for this student's branch/semester
    if is_semester_stopped(student.branch, student.current_semester) or not student.is_semester_active:
        return jsonify({'error': 'Attendance marking is closed for this semester'}), 403
    
    try:
        marked_count = 0
        for period in periods:
            # Check if attendance already exists for this period
            existing = Attendance.query.filter_by(
                student_id=student_id,
                date=today,
                period=int(period)
            ).first()
            
            if existing:
                # Update existing attendance
                existing.status = status
                existing.marked_by = teacher.id
                existing.marked_at = datetime.utcnow()
                existing.subject = subject
                existing.attendance_type = attendance_type
            else:
                # Create new attendance record
                attendance = Attendance(
                    student_id=student_id,
                    date=today,
                    period=int(period),
                    status=status,
                    marked_by=teacher.id,
                    subject=subject,
                    semester_at_time=student.current_semester,
                    attendance_type=attendance_type
                )
                db.session.add(attendance)
            marked_count += 1
        
        db.session.commit()
        
        # Check for low attendance and send email if needed
        sem_data = get_comprehensive_attendance(student)
        if sem_data['overall_percentage'] < 75:
            send_low_attendance_email(student, sem_data['overall_percentage'])
        
        return jsonify({
            'success': True, 
            'message': f'Attendance marked for {marked_count} period(s)',
            'student_name': student.name
        })
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Mark student attendance error: {e}")
        return jsonify({'error': 'Failed to mark attendance'}), 500

@app.route('/teacher/get-students')
@login_required
def get_students_for_attendance():
    if current_user.role != 'teacher':
        return jsonify({'error': 'Unauthorized'}), 403
    
    branch = request.args.get('branch')
    semester = request.args.get('semester')
    section = request.args.get('section')
    
    if not all([branch, semester, section]):
        return jsonify({'error': 'Missing parameters'}), 400
    
    # Check if teacher's branch matches or is admin/examination
    teacher = current_user.teacher
    if teacher.branch not in ['ADMIN', 'EXAMINATION'] and teacher.branch != branch:
        return jsonify({'error': 'Not authorized for this branch'}), 403
    
    # FIXED: Sort by register_number
    students = Student.query.filter_by(
        branch=branch,
        current_semester=int(semester),
        section=section,
        is_semester_active=True
    ).order_by(Student.register_number.asc()).all()
    
    student_list = [{
        'id': s.id,
        'name': s.name,
        'register_number': s.register_number,
        'phone': s.phone or '-'
    } for s in students]
    
    return jsonify({'students': student_list})

@app.route('/teacher/attendance-interface')
@login_required
def teacher_attendance_interface():
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    teacher = current_user.teacher
    today = datetime.now().date()
    
    # Check if teacher has marked attendance today
    teacher_att = TeacherAttendance.query.filter_by(
        teacher_id=teacher.id, date=today
    ).first()
    
    if not teacher_att or not teacher_att.check_in:
        flash('Please mark your attendance first', 'warning')
        return redirect(url_for('teacher_dashboard'))
    
    # Get subjects for dropdown
    subjects = Subject.query.filter_by(
        branch=teacher.branch if teacher.branch not in ['ADMIN', 'EXAMINATION'] else 'CSE'
    ).all()
    
    # Get branches based on teacher role
    if teacher.branch == 'ADMIN':
        allowed_branches = BRANCHES
    elif teacher.branch == 'EXAMINATION':
        allowed_branches = BRANCHES
    else:
        allowed_branches = [(teacher.branch, teacher.branch)]
    
    return render_template_string(
        TEACHER_ATTENDANCE_INTERFACE_HTML,
        teacher=teacher,
        today=today,
        subjects=subjects,
        branches=allowed_branches,
        teacher_att=teacher_att
    )

@app.route('/teacher/reports/daily')
@login_required
def teacher_daily_report():
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    teacher = current_user.teacher
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    # Get teacher's own attendance for the day
    attendance = TeacherAttendance.query.filter_by(
        teacher_id=teacher.id,
        date=report_date
    ).first()
    
    return render_template_string(
        TEACHER_DAILY_REPORT_HTML,
        teacher=teacher,
        attendance=attendance,
        date=report_date
    )

@app.route('/teacher/reports/monthly')
@login_required
def teacher_monthly_report():
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    teacher = current_user.teacher
    month = int(request.args.get('month', datetime.now().month))
    year = int(request.args.get('year', datetime.now().year))
    
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
    else:
        end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
    
    attendances = TeacherAttendance.query.filter(
        TeacherAttendance.teacher_id == teacher.id,
        TeacherAttendance.date >= start_date,
        TeacherAttendance.date <= end_date
    ).order_by(TeacherAttendance.date).all()
    
    total_present = sum(1 for a in attendances if a.status == 'present')
    
    return render_template_string(
        TEACHER_MONTHLY_REPORT_HTML,
        teacher=teacher,
        attendances=attendances,
        month=month,
        year=year,
        month_name=datetime(year, month, 1).strftime('%B'),
        total_present=total_present,
        total_days=len(attendances)
    )

@app.route('/teacher/reports/yearly')
@login_required
def teacher_yearly_report():
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    teacher = current_user.teacher
    year = int(request.args.get('year', datetime.now().year))
    
    yearly_data = get_teacher_yearly_attendance(teacher, year)
    
    return render_template_string(
        TEACHER_YEARLY_REPORT_HTML,
        teacher=teacher,
        yearly_data=yearly_data,
        year=year
    )

# ============================================
# ADMIN ROUTES
# ============================================

@app.route('/admin/dashboard')
@login_required
@admin_required
def admin_dashboard():
    total_students = Student.query.count()
    total_teachers = Teacher.query.count()
    active_semesters = Student.query.filter_by(is_semester_active=True).count()
    stopped_semesters = StoppedSemester.query.filter_by(is_active=True).count()
    
    today = datetime.now().date()
    today_teacher_attendance = TeacherAttendance.query.filter_by(date=today).count()
    
    recent_logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).limit(10).all()
    
    return render_template_string(
        ADMIN_DASHBOARD_HTML,
        total_students=total_students,
        total_teachers=total_teachers,
        active_semesters=active_semesters,
        stopped_semesters=stopped_semesters,
        today_teacher_attendance=today_teacher_attendance,
        recent_logs=recent_logs,
        today=today
    )

@app.route('/admin/stop-semester', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_stop_semester():
    form = StopSemesterForm()
    
    if form.validate_on_submit():
        branch = form.branch.data
        semester = int(form.semester.data)
        
        # Check if already stopped
        existing = StoppedSemester.query.filter_by(
            branch=branch, semester=semester, is_active=True
        ).first()
        
        if existing:
            flash('This semester is already stopped', 'warning')
            return redirect(url_for('admin_stop_semester'))
        
        try:
            # Create stop record
            stop_record = StoppedSemester(
                branch=branch,
                semester=semester,
                stopped_by=current_user.id,
                is_active=True
            )
            db.session.add(stop_record)
            
            # Update all students in this branch/semester
            students = Student.query.filter_by(
                branch=branch,
                current_semester=semester,
                is_semester_active=True
            ).all()
            
            for student in students:
                # Save semester history
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
                
                # Deactivate semester for student
                student.is_semester_active = False
            
            # Log action
            log = AdminLog(
                admin_id=current_user.id,
                action=f"Stopped semester {semester} for branch {branch}"
            )
            db.session.add(log)
            
            db.session.commit()
            flash(f'Successfully stopped Semester {semester} for {branch}', 'success')
            return redirect(url_for('admin_dashboard'))
            
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Stop semester error: {e}")
            flash('Failed to stop semester', 'danger')
    
    # Get list of stopped semesters
    stopped_list = StoppedSemester.query.filter_by(is_active=True).order_by(
        StoppedSemester.stopped_at.desc()
    ).all()
    
    return render_template_string(
        ADMIN_STOP_SEMESTER_HTML,
        form=form,
        stopped_list=stopped_list
    )

@app.route('/admin/reactivate-semester/<int:stop_id>', methods=['POST'])
@login_required
@admin_required
def admin_reactivate_semester(stop_id):
    stop_record = StoppedSemester.query.get_or_404(stop_id)
    
    try:
        # Just mark the stop record as inactive - allows NEW registrations
        stop_record.is_active = False
        
        # ❌ REMOVED: Don't reactivate existing students
        # Their semester is already complete (archived in SemesterHistory)
        
        # Log action
        log = AdminLog(
            admin_id=current_user.id,
            action=f"Reactivated semester {stop_record.semester} for branch {stop_record.branch} - allowing new registrations only"
        )
        db.session.add(log)
        
        db.session.commit()
        flash(f'Semester {stop_record.semester} for {stop_record.branch} is now open for NEW registrations only. Existing students have completed their semester.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Reactivate semester error: {e}")
        flash('Failed to reactivate semester', 'danger')
    
    return redirect(url_for('admin_stop_semester'))

@app.route('/admin/manage-subjects', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_manage_subjects():
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
            flash('Subject added successfully', 'success')
            return redirect(url_for('admin_manage_subjects'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Add subject error: {e}")
            flash('Failed to add subject', 'danger')
    
    subjects = Subject.query.order_by(Subject.branch, Subject.semester, Subject.code).all()
    return render_template_string(
        ADMIN_MANAGE_SUBJECTS_HTML,
        form=form,
        subjects=subjects
    )

@app.route('/admin/delete-subject/<int:subject_id>', methods=['POST'])
@login_required
@admin_required
def admin_delete_subject(subject_id):
    subject = Subject.query.get_or_404(subject_id)
    try:
        db.session.delete(subject)
        db.session.commit()
        flash('Subject deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Delete subject error: {e}")
        flash('Failed to delete subject', 'danger')
    return redirect(url_for('admin_manage_subjects'))

# FIXED: Updated admin student reports with semester option - SORTED BY REGISTER NUMBER
@app.route('/admin/student-reports')
@login_required
@admin_required
def admin_student_reports():
    branches = ['all'] + [b[0] for b in BRANCHES]
    semesters = ['all'] + list(range(1, 9))
    sections = ['all', 'A', 'B', 'C']
    
    report_type = request.args.get('report_type', 'daily')
    branch = request.args.get('branch', 'all')
    semester = request.args.get('semester', 'all')
    section = request.args.get('section', 'all')
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    month = request.args.get('month', datetime.now().month)
    year = request.args.get('year', datetime.now().year)
    
    try:
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except:
        report_date = datetime.now().date()
    
    data = None
    start_date = None
    end_date = None
    
    if report_type == 'daily':
        data = get_daily_attendance(branch, semester, section, report_date)
    elif report_type == 'monthly':
        # FIXED: Ensure month and year are integers
        data, start_date, end_date = get_monthly_attendance(branch, semester, section, month, year)
    elif report_type == 'semester':
        data = get_semester_attendance(branch, semester, section)
    
    return render_template_string(
        ADMIN_STUDENT_REPORTS_HTML,
        branches=branches,
        semesters=semesters,
        sections=sections,
        report_type=report_type,
        selected_branch=branch,
        selected_semester=semester,
        selected_section=section,
        date=report_date,
        month=month,
        year=year,
        data=data,
        start_date=start_date,
        end_date=end_date
    )

# FIXED: Updated admin teacher reports route
@app.route('/admin/teacher-reports')
@login_required
@admin_required
def admin_teacher_reports():
    branches = ['all'] + [b[0] for b in BRANCHES] + ['ADMIN', 'EXAMINATION']
    
    branch = request.args.get('branch', 'all')
    name = request.args.get('name', '')
    month = request.args.get('month')
    year = request.args.get('year')
    
    data = get_teacher_attendance_report(
        branch if branch != 'all' else None,
        name if name else None,
        month,
        year
    )
    
    return render_template_string(
        ADMIN_TEACHER_REPORTS_HTML,
        branches=branches,
        selected_branch=branch,
        name=name,
        month=month,
        year=year,
        data=data
    )

# FIXED: Export attendance - removed openpyxl dependency issue
@app.route('/admin/export-attendance')
@login_required
@admin_required
def admin_export_attendance():
    report_type = request.args.get('report_type', 'daily')
    branch = request.args.get('branch', 'all')
    semester = request.args.get('semester', 'all')
    section = request.args.get('section', 'all')
    
    # Create CSV instead of Excel (no openpyxl dependency)
    import csv
    import io
    
    output = io.StringIO()
    writer = csv.writer(output)
    
    if report_type == 'daily':
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        data = get_daily_attendance(branch, semester, section, report_date)
        
        writer.writerow(['Register Number', 'Name', 'Branch', 'Semester', 'Section', 'Periods Present', 'Total Periods', 'Percentage'])
        
        for student_id, info in data.items():
            student = info['student']
            percentage = (info['present_count'] / info['total_count'] * 100) if info['total_count'] > 0 else 0
            
            writer.writerow([
                student.register_number,
                student.name,
                student.branch,
                student.current_semester,
                student.section,
                info['present_count'],
                info['total_count'],
                f"{percentage:.2f}%"
            ])
    
    elif report_type == 'monthly':
        month = int(request.args.get('month', datetime.now().month))
        year = int(request.args.get('year', datetime.now().year))
        data, start_date, end_date = get_monthly_attendance(branch, semester, section, month, year)
        
        writer.writerow(['Register Number', 'Name', 'Branch', 'Semester', 'Section', 'Theory Present', 'Theory Total', 'Practical Present', 'Practical Total', 'Overall %'])
        
        for item in data:
            student = item['student']
            writer.writerow([
                student.register_number,
                student.name,
                student.branch,
                student.current_semester,
                student.section,
                item['theory_present'],
                item['theory_total'],
                item['practical_present'],
                item['practical_total'],
                f"{item['overall_percentage']:.2f}%"
            ])
    
    elif report_type == 'semester':
        data = get_semester_attendance(branch, semester, section)
        
        writer.writerow(['Register Number', 'Name', 'Branch', 'Semester', 'Section', 'Theory %', 'Practical %', 'Overall %'])
        
        for item in data:
            student = item['student']
            writer.writerow([
                student.register_number,
                student.name,
                student.branch,
                student.current_semester,
                student.section,
                f"{item['theory_percentage']:.2f}%",
                f"{item['practical_percentage']:.2f}%",
                f"{item['overall_percentage']:.2f}%"
            ])
    
    output.seek(0)
    
    filename = f"attendance_{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )

@app.route('/admin/create-admin', methods=['POST'])
@login_required
@admin_required
def admin_create_admin():
    email = request.form.get('email')
    password = request.form.get('password')
    
    if not email or not password:
        flash('Email and password required', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    if User.query.filter_by(email=email).first():
        flash('Email already exists', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        user = User(
            email=email,
            password_hash=generate_password_hash(password),
            role='admin'
        )
        db.session.add(user)
        
        log = AdminLog(
            admin_id=current_user.id,
            action=f"Created new admin account: {email}"
        )
        db.session.add(log)
        
        db.session.commit()
        flash('Admin account created successfully', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Create admin error: {e}")
        flash('Failed to create admin account', 'danger')
    
    return redirect(url_for('admin_dashboard'))

# ============================================
# HTML TEMPLATES (Inline for Railway.app deployment)
# ============================================

INDEX_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SVIST Attendance System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: white;
            padding: 3rem;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 500px;
            width: 90%;
        }
        h1 { color: #333; margin-bottom: 1rem; font-size: 2rem; }
        .subtitle { color: #666; margin-bottom: 2rem; }
        .btn {
            display: block;
            width: 100%;
            padding: 1rem;
            margin: 0.5rem 0;
            border: none;
            border-radius: 10px;
            font-size: 1.1rem;
            cursor: pointer;
            transition: all 0.3s;
            text-decoration: none;
            color: white;
        }
        .btn-primary { background: #667eea; }
        .btn-secondary { background: #764ba2; }
        .btn-success { background: #48bb78; }
        .btn:hover { transform: translateY(-2px); box-shadow: 0 5px 15px rgba(0,0,0,0.2); }
        .logo { font-size: 4rem; margin-bottom: 1rem; }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">🎓</div>
        <h1>SVIST Attendance System</h1>
        <p class="subtitle">Sree Vahini Institute of Science and Technology</p>
        <a href="{{ url_for('login') }}" class="btn btn-primary">Login</a>
        <a href="{{ url_for('register_student') }}" class="btn btn-secondary">Register as Student</a>
        <a href="{{ url_for('register_teacher') }}" class="btn btn-success">Register as Teacher</a>
    </div>
</body>
</html>
"""

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Login - SVIST Attendance</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .container {
            background: white;
            padding: 2.5rem;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 450px;
        }
        h2 { color: #333; margin-bottom: 1.5rem; text-align: center; }
        .form-group { margin-bottom: 1.5rem; }
        label { display: block; margin-bottom: 0.5rem; color: #555; font-weight: 500; }
        input, select {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 1rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background 0.3s;
        }
        .btn:hover { background: #5568d3; }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-danger { background: #fed7d7; color: #c53030; border: 1px solid #fc8181; }
        .alert-success { background: #c6f6d5; color: #22543d; border: 1px solid #9ae6b4; }
        .alert-info { background: #bee3f8; color: #2a4365; border: 1px solid #90cdf4; }
        .back-link {
            display: block;
            text-align: center;
            margin-top: 1rem;
            color: #667eea;
            text-decoration: none;
        }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h2>🔐 Login</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">
                <label>Email</label>
                {{ form.email(class="form-control", placeholder="Enter your email") }}
            </div>
            <div class="form-group">
                <label>Password</label>
                {{ form.password(class="form-control", placeholder="Enter your password") }}
            </div>
            <div class="form-group">
                <label>Login As</label>
                {{ form.role(class="form-control") }}
            </div>
            <button type="submit" class="btn">Login</button>
        </form>
        <a href="{{ url_for('index') }}" class="back-link">← Back to Home</a>
    </div>
</body>
</html>
"""

REGISTER_STUDENT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Student Registration - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 2rem 1rem;
        }
        .container {
            background: white;
            padding: 2.5rem;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 600px;
            margin: 0 auto;
        }
        h2 { color: #333; margin-bottom: 1.5rem; text-align: center; }
        .form-group { margin-bottom: 1.25rem; }
        label { display: block; margin-bottom: 0.5rem; color: #555; font-weight: 500; }
        input, select {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background 0.3s;
            margin-top: 1rem;
        }
        .btn:hover { background: #38a169; }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-danger { background: #fed7d7; color: #c53030; }
        .alert-success { background: #c6f6d5; color: #22543d; }
        .back-link {
            display: block;
            text-align: center;
            margin-top: 1rem;
            color: #667eea;
            text-decoration: none;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        @media (max-width: 480px) {
            .grid-2 { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h2>🎓 Student Registration</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">
                <label>Full Name</label>
                {{ form.name(placeholder="Enter your full name") }}
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>Register Number</label>
                    {{ form.register_number(placeholder="e.g., 20B91A0001") }}
                </div>
                <div class="form-group">
                    <label>Phone Number</label>
                    {{ form.phone(placeholder="Your phone number") }}
                </div>
            </div>
            <div class="form-group">
                <label>Email</label>
                {{ form.email(placeholder="your.email@example.com", type="email") }}
            </div>
            <div class="form-group">
                <label>Password</label>
                {{ form.password(placeholder="Min 6 characters", type="password") }}
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>Branch</label>
                    {{ form.branch() }}
                </div>
                <div class="form-group">
                    <label>Semester</label>
                    {{ form.semester() }}
                </div>
            </div>
            <div class="form-group">
                <label>Section</label>
                {{ form.section() }}
            </div>
            <button type="submit" class="btn">Register</button>
        </form>
        <a href="{{ url_for('index') }}" class="back-link">← Back to Home</a>
    </div>
</body>
</html>
"""

REGISTER_TEACHER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Registration - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 2rem 1rem;
        }
        .container {
            background: white;
            padding: 2.5rem;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 600px;
            margin: 0 auto;
        }
        h2 { color: #333; margin-bottom: 1.5rem; text-align: center; }
        .form-group { margin-bottom: 1.25rem; }
        label { display: block; margin-bottom: 0.5rem; color: #555; font-weight: 500; }
        input, select {
            width: 100%;
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            font-size: 1rem;
            transition: border-color 0.3s;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #667eea;
        }
        .btn {
            width: 100%;
            padding: 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1rem;
            cursor: pointer;
            transition: background 0.3s;
            margin-top: 1rem;
        }
        .btn:hover { background: #38a169; }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-danger { background: #fed7d7; color: #c53030; }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        @media (max-width: 480px) {
            .grid-2 { grid-template-columns: 1fr; }
        }
    </style>
    <script>
        const rolesData = {{ TEACHER_ROLES|tojson }};
        function updateRoles() {
            const category = document.getElementById('staff_category').value;
            const roleSelect = document.getElementById('role');
            roleSelect.innerHTML = '';
            if (rolesData[category]) {
                rolesData[category].forEach(role => {
                    const option = document.createElement('option');
                    option.value = role;
                    option.textContent = role;
                    roleSelect.appendChild(option);
                });
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <h2>👨‍🏫 Teacher Registration</h2>
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        <form method="POST">
            {{ form.hidden_tag() }}
            <div class="form-group">
                <label>Full Name</label>
                {{ form.name(placeholder="Enter your full name") }}
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>Employee ID</label>
                    {{ form.employee_id(placeholder="e.g., EMP001") }}
                </div>
                <div class="form-group">
                    <label>Qualification</label>
                    {{ form.qualification(placeholder="e.g., M.Tech, Ph.D") }}
                </div>
            </div>
            <div class="form-group">
                <label>Email</label>
                {{ form.email(placeholder="your.email@svist.edu.in", type="email") }}
            </div>
            <div class="form-group">
                <label>Password</label>
                {{ form.password(placeholder="Min 6 characters", type="password") }}
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>Branch</label>
                    {{ form.branch() }}
                </div>
                <div class="form-group">
                    <label>Staff Category</label>
                    {{ form.staff_category(id="staff_category", onchange="updateRoles()") }}
                </div>
            </div>
            <div class="form-group">
                <label>Role</label>
                {{ form.role(id="role") }}
            </div>
            <button type="submit" class="btn">Register</button>
        </form>
        <a href="{{ url_for('index') }}" style="display:block;text-align:center;margin-top:1rem;color:#667eea;text-decoration:none;">← Back to Home</a>
    </div>
    <script>updateRoles();</script>
</body>
</html>
"""

STUDENT_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Student Dashboard - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .navbar h1 { font-size: 1.5rem; }
        .nav-links a {
            color: white;
            text-decoration: none;
            margin-left: 1.5rem;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            transition: background 0.3s;
        }
        .nav-links a:hover { background: rgba(255,255,255,0.2); }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card h3 {
            color: #333;
            margin-bottom: 1rem;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 0.5rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 10px;
            text-align: center;
        }
        .stat-box h4 { font-size: 2rem; margin-bottom: 0.5rem; }
        .stat-box p { opacity: 0.9; }
        .warning {
            background: #fed7d7;
            color: #c53030;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            border-left: 4px solid #fc8181;
        }
        .info {
            background: #bee3f8;
            color: #2a4365;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            border-left: 4px solid #90cdf4;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        th {
            background: #f7fafc;
            font-weight: 600;
            color: #4a5568;
        }
        .status-present { color: #38a169; font-weight: 600; }
        .status-absent { color: #e53e3e; font-weight: 600; }
        .btn {
            display: inline-block;
            padding: 0.5rem 1rem;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 5px;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
            transition: background 0.3s;
        }
        .btn:hover { background: #5568d3; }
        .semester-inactive {
            background: #fed7d7;
            border: 2px solid #fc8181;
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
            color: #c53030;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>🎓 SVIST Attendance</h1>
        <div class="nav-links">
            <a href="{{ url_for('student_daily_report') }}">Daily Report</a>
            <a href="{{ url_for('student_monthly_report') }}">Monthly Report</a>
            <a href="{{ url_for('student_semester_report') }}">Semester Report</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </nav>
    
    <div class="container">
        {% if semester_stopped %}
        <div class="semester-inactive">
            ⚠️ Your semester attendance has been closed by administration. Contact your department for assistance.
        </div>
        {% endif %}
        
        <div class="stats-grid">
            <div class="stat-box">
                <h4>{{ "%.1f"|format(sem_data['overall_percentage']) }}%</h4>
                <p>Overall Attendance</p>
            </div>
            <div class="stat-box">
                <h4>{{ sem_data['theory_present'] }}/{{ sem_data['theory_total'] }}</h4>
                <p>Theory Classes</p>
            </div>
            <div class="stat-box">
                <h4>{{ sem_data['practical_present'] }}/{{ sem_data['practical_total'] }}</h4>
                <p>Practical Classes</p>
            </div>
            <div class="stat-box">
                <h4>{{ student.current_semester }}</h4>
                <p>Current Semester</p>
            </div>
        </div>
        
        {% if sem_data['overall_percentage'] < 75 %}
        <div class="warning">
            ⚠️ Your attendance is below 75% ({{ "%.1f"|format(sem_data['overall_percentage']) }}%). Please attend classes regularly to avoid academic penalties.
        </div>
        {% endif %}
        
        <div class="card">
            <h3>Today's Attendance ({{ today.strftime('%d %b %Y') }})</h3>
            {% if today_attendance %}
            <table>
                <thead>
                    <tr>
                        <th>Period</th>
                        <th>Subject</th>
                        <th>Type</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for att in today_attendance %}
                    <tr>
                        <td>{{ att.period }}</td>
                        <td>{{ att.subject or '-' }}</td>
                        <td>{{ att.attendance_type.title() }}</td>
                        <td class="status-{{ att.status }}">{{ att.status.title() }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p>No attendance records for today.</p>
            {% endif %}
        </div>
        
        <div class="card">
            <h3>Subject-wise Attendance</h3>
            <table>
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th>Type</th>
                        <th>Present</th>
                        <th>Total</th>
                        <th>Percentage</th>
                    </tr>
                </thead>
                <tbody>
                    {% for subject, data in sem_data['subject_wise'].items() %}
                    <tr>
                        <td>{{ subject }}</td>
                        <td>{{ data['type'].title() }}</td>
                        <td>{{ data['present'] }}</td>
                        <td>{{ data['total'] }}</td>
                        <td>{{ "%.1f"|format(data['percentage']) }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        {% if past_semesters %}
        <div class="card">
            <h3>Past Semester History</h3>
            <table>
                <thead>
                    <tr>
                        <th>Semester</th>
                        <th>Section</th>
                        <th>Duration</th>
                        <th>Theory %</th>
                        <th>Practical %</th>
                        <th>Overall %</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sem in past_semesters %}
                    <tr>
                        <td>{{ sem.semester_number }}</td>
                        <td>{{ sem.section }}</td>
                        <td>{{ sem.start_date.strftime('%d/%m/%Y') }} - {{ sem.end_date.strftime('%d/%m/%Y') }}</td>
                        <td>{{ "%.1f"|format((sem.present_theory_classes/sem.total_theory_classes*100) if sem.total_theory_classes else 0) }}%</td>
                        <td>{{ "%.1f"|format((sem.present_lab_classes/sem.total_lab_classes*100) if sem.total_lab_classes else 0) }}%</td>
                        <td>{{ "%.1f"|format(sem.attendance_percentage) }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        <div class="card">
            <h3>Quick Links</h3>
            <a href="{{ url_for('student_daily_report') }}" class="btn">View Daily Report</a>
            <a href="{{ url_for('student_monthly_report') }}" class="btn">View Monthly Report</a>
            <a href="{{ url_for('student_semester_report') }}" class="btn">View Full Semester Report</a>
        </div>
    </div>
</body>
</html>
"""

# NEW: Student Daily Report with Print and PDF buttons
STUDENT_DAILY_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .container {
            max-width: 800px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h2 { color: #333; margin-bottom: 1.5rem; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 1rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .status-present { color: #38a169; font-weight: 600; }
        .status-absent { color: #e53e3e; font-weight: 600; }
        .back-link {
            display: inline-block;
            margin-top: 1rem;
            color: #667eea;
            text-decoration: none;
        }
        .date-form {
            margin-bottom: 1.5rem;
            display: flex;
            gap: 1rem;
            align-items: center;
        }
        input[type="date"] {
            padding: 0.5rem;
            border: 2px solid #e2e8f0;
            border-radius: 5px;
        }
        button, .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
        }
        .btn-print { background: #48bb78; }
        .btn-pdf { background: #ed8936; }
        .action-btns {
            margin-bottom: 1.5rem;
        }
        @media print {
            .navbar, .action-btns, .date-form, .back-link { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📅 Daily Attendance Report</h1>
        <a href="{{ url_for('logout') }}" style="color:white;text-decoration:none;">Logout</a>
    </nav>
    <div class="container">
        <div class="card">
            <h2>Attendance for {{ date.strftime('%d %B %Y') }}</h2>
            <form class="date-form" method="get">
                <input type="date" name="date" value="{{ date.strftime('%Y-%m-%d') }}">
                <button type="submit">View</button>
            </form>
            
            <div class="action-btns">
                <button class="btn-print" onclick="window.print()">🖨️ Print</button>
                <a href="{{ url_for('download_pdf', report_type='daily', date=date.strftime('%Y-%m-%d')) }}" class="btn-pdf">📄 Download PDF</a>
            </div>
            
            {% if attendances %}
            <table>
                <thead>
                    <tr>
                        <th>Period</th>
                        <th>Subject</th>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Marked At</th>
                    </tr>
                </thead>
                <tbody>
                    {% for att in attendances %}
                    <tr>
                        <td>{{ att.period }}</td>
                        <td>{{ att.subject or '-' }}</td>
                        <td>{{ att.attendance_type.title() }}</td>
                        <td class="status-{{ att.status }}">{{ att.status.title() }}</td>
                        <td>{{ att.marked_at.strftime('%H:%M') if att.marked_at else '-' }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <p>No attendance records found for this date.</p>
            {% endif %}
            <a href="{{ url_for('student_dashboard') }}" class="back-link">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

# NEW: Student Monthly Report with Print and PDF buttons
STUDENT_MONTHLY_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Monthly Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 10px;
            text-align: center;
        }
        .stat h3 { font-size: 2rem; margin-bottom: 0.5rem; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .status-present { color: #38a169; font-weight: 600; }
        .status-absent { color: #e53e3e; font-weight: 600; }
        .month-form {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        select, button {
            padding: 0.5rem;
            border: 2px solid #e2e8f0;
            border-radius: 5px;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            cursor: pointer;
        }
        .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 1rem;
        }
        .btn-pdf { background: #ed8936; }
        @media print {
            .navbar, .month-form, .btn-print, .btn-pdf { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📊 Monthly Attendance Report</h1>
    </nav>
    <div class="container">
        <div class="card">
            <h2>{{ month_name }} {{ year }}</h2>
            <form class="month-form" method="get">
                <select name="month">
                    {% for i in range(1, 13) %}
                    <option value="{{ i }}" {% if i == month %}selected{% endif %}>{{ datetime(2000, i, 1).strftime('%B') }}</option>
                    {% endfor %}
                </select>
                <select name="year">
                    {% for y in range(2020, 2027) %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>{{ y }}</option>
                    {% endfor %}
                </select>
                <button type="submit">View</button>
            </form>
            
            <button class="btn-print" onclick="window.print()">🖨️ Print</button>
            <a href="{{ url_for('download_pdf', report_type='monthly', month=month, year=year) }}" class="btn-pdf">📄 Download PDF</a>
            
            <div class="stats">
                <div class="stat">
                    <h3>{{ total_present }}</h3>
                    <p>Present</p>
                </div>
                <div class="stat">
                    <h3>{{ total_classes }}</h3>
                    <p>Total Classes</p>
                </div>
                <div class="stat">
                    <h3>{{ "%.1f"|format(percentage) }}%</h3>
                    <p>Attendance %</p>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Period</th>
                        <th>Subject</th>
                        <th>Type</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for att in attendances %}
                    <tr>
                        <td>{{ att.date.strftime('%d %b %Y') }}</td>
                        <td>{{ att.period }}</td>
                        <td>{{ att.subject or '-' }}</td>
                        <td>{{ att.attendance_type.title() }}</td>
                        <td class="status-{{ att.status }}">{{ att.status.title() }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            <a href="{{ url_for('student_dashboard') }}" style="display:inline-block;margin-top:1rem;color:#667eea;text-decoration:none;">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

# NEW: Student Semester Report with Print and PDF buttons
STUDENT_SEMESTER_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Semester Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .main-stats {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 1rem;
            margin-bottom: 2rem;
        }
        .stat-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 10px;
            text-align: center;
        }
        .stat-box h3 { font-size: 1.8rem; margin-bottom: 0.5rem; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; font-weight: 600; }
        .progress-bar {
            background: #e2e8f0;
            border-radius: 10px;
            overflow: hidden;
            height: 20px;
        }
        .progress-fill {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            height: 100%;
            transition: width 0.3s;
        }
        .low { background: #fc8181; }
        .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 1.5rem;
        }
        .btn-pdf { background: #ed8936; }
        @media print {
            .navbar, .btn-print, .btn-pdf { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📚 Semester Attendance Report</h1>
    </nav>
    <div class="container">
        <div class="card">
            <h2>Semester {{ student.current_semester }} - Comprehensive Report</h2>
            <p style="color:#666;margin-bottom:1.5rem;">Period: {{ sem_data['start_date'].strftime('%d %b %Y') }} - {{ sem_data['end_date'].strftime('%d %b %Y') }}</p>
            
            <button class="btn-print" onclick="window.print()">🖨️ Print</button>
            <a href="{{ url_for('download_pdf', report_type='semester') }}" class="btn-pdf">📄 Download PDF</a>
            
            <div class="main-stats">
                <div class="stat-box">
                    <h3>{{ "%.1f"|format(sem_data['overall_percentage']) }}%</h3>
                    <p>Overall</p>
                </div>
                <div class="stat-box">
                    <h3>{{ "%.1f"|format(sem_data['theory_percentage']) }}%</h3>
                    <p>Theory</p>
                </div>
                <div class="stat-box">
                    <h3>{{ "%.1f"|format(sem_data['practical_percentage']) }}%</h3>
                    <p>Practical</p>
                </div>
                <div class="stat-box">
                    <h3>{{ sem_data['present_periods'] }}/{{ sem_data['total_periods'] }}</h3>
                    <p>Total</p>
                </div>
            </div>
            
            <h3 style="margin:1.5rem 0 1rem;">Subject-wise Breakdown</h3>
            <table>
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th>Type</th>
                        <th>Attendance</th>
                        <th>Progress</th>
                    </tr>
                </thead>
                <tbody>
                    {% for subject, data in sem_data['subject_wise'].items() %}
                    <tr>
                        <td>{{ subject }}</td>
                        <td>{{ data['type'].title() }}</td>
                        <td>{{ data['present'] }}/{{ data['total'] }} ({{ "%.1f"|format(data['percentage']) }}%)</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill {% if data['percentage'] < 75 %}low{% endif %}" style="width: {{ data['percentage'] }}%"></div>
                            </div>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            
            <h3 style="margin:1.5rem 0 1rem;">Monthly Breakdown</h3>
            <table>
                <thead>
                    <tr>
                        <th>Month</th>
                        <th>Theory</th>
                        <th>Practical</th>
                        <th>Combined %</th>
                    </tr>
                </thead>
                <tbody>
                    {% for month_key, data in sem_data['monthly_breakdown'].items()|sort %}
                    <tr>
                        <td>{{ data['month_name'] }}</td>
                        <td>{{ data['theory_present'] }}/{{ data['theory_total'] }}</td>
                        <td>{{ data['practical_present'] }}/{{ data['practical_total'] }}</td>
                        <td>
                            {% set total = data['theory_total'] + data['practical_total'] %}
                            {% set present = data['theory_present'] + data['practical_present'] %}
                            {{ "%.1f"|format((present/total*100) if total else 0) }}%
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            
            <a href="{{ url_for('student_dashboard') }}" style="display:inline-block;margin-top:1.5rem;color:#667eea;text-decoration:none;">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

TEACHER_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Dashboard - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .nav-links a {
            color: white;
            text-decoration: none;
            margin-left: 1.5rem;
        }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .attendance-box {
            background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
            color: white;
            padding: 2rem;
            border-radius: 15px;
            text-align: center;
            margin-bottom: 1.5rem;
        }
        .attendance-box.checked-out {
            background: linear-gradient(135deg, #ed8936 0%, #dd6b20 100%);
        }
        .attendance-box.not-marked {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .btn {
            display: inline-block;
            padding: 1rem 2rem;
            background: white;
            color: #333;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
            margin-top: 1rem;
            cursor: pointer;
            border: none;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }
        .stat-card {
            background: #f7fafc;
            padding: 1.5rem;
            border-radius: 10px;
            text-align: center;
        }
        .stat-card h3 {
            font-size: 2rem;
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        #location-status {
            margin-top: 1rem;
            font-size: 0.9rem;
            opacity: 0.9;
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>👨‍🏫 Teacher Dashboard</h1>
        <div class="nav-links">
            <a href="{{ url_for('teacher_attendance_interface') }}">Mark Student Attendance</a>
            <a href="{{ url_for('teacher_daily_report') }}">Daily Report</a>
            <a href="{{ url_for('teacher_monthly_report') }}">Monthly Report</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </nav>
    
    <div class="container">
        {% if today_status and today_status.check_out %}
        <div class="attendance-box checked-out">
            <h2>✅ Checked Out</h2>
            <p>Check-in: {{ today_status.check_in.strftime('%H:%M') }} | Check-out: {{ today_status.check_out.strftime('%H:%M') }}</p>
            <p>Have a great day!</p>
        </div>
        {% elif today_status and today_status.check_in %}
        <div class="attendance-box checked-out">
            <h2>🟢 Checked In</h2>
            <p>Check-in time: {{ today_status.check_in.strftime('%H:%M') }}</p>
            <button class="btn" onclick="markAttendance()">Check Out</button>
            <p id="location-status">Location verified ✓</p>
        </div>
        {% else %}
        <div class="attendance-box not-marked">
            <h2>📍 Mark Your Attendance</h2>
            <p>{{ today.strftime('%A, %d %B %Y') }}</p>
            <button class="btn" onclick="markAttendance()">Check In</button>
            <p id="location-status">Getting location...</p>
        </div>
        {% endif %}
        
        <div class="card">
            <h3>Yearly Attendance Summary ({{ yearly_data['year'] }})</h3>
            <div class="stats-grid">
                <div class="stat-card">
                    <h3>{{ yearly_data['total_days_present'] }}</h3>
                    <p>Days Present</p>
                </div>
                <div class="stat-card">
                    <h3>{{ yearly_data['working_days'] }}</h3>
                    <p>Working Days</p>
                </div>
                <div class="stat-card">
                    <h3>{{ "%.1f"|format(yearly_data['percentage']) }}%</h3>
                    <p>Attendance Rate</p>
                </div>
            </div>
        </div>
        
        <div class="card">
            <h3>Quick Actions</h3>
            <a href="{{ url_for('teacher_attendance_interface') }}" class="btn" style="background:#667eea;color:white;margin-right:0.5rem;">Mark Student Attendance</a>
            <a href="{{ url_for('teacher_yearly_report') }}" class="btn" style="background:#764ba2;color:white;">View Yearly Report</a>
        </div>
    </div>
    
    <script>
        let latitude = null;
        let longitude = null;
        
        // Get location on page load
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                (position) => {
                    latitude = position.coords.latitude;
                    longitude = position.coords.longitude;
                    document.getElementById('location-status').textContent = 'Location acquired ✓';
                },
                (error) => {
                    document.getElementById('location-status').textContent = 'Location access denied ✗';
                }
            );
        }
        
        function markAttendance() {
            if (!latitude || !longitude) {
                alert('Please allow location access to mark attendance');
                return;
            }
            
            fetch('/teacher/mark-attendance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': '{{ csrf_token() }}'
                },
                body: JSON.stringify({latitude, longitude})
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    location.reload();
                } else {
                    alert(data.error || 'Failed to mark attendance');
                }
            })
            .catch(error => {
                alert('Error: ' + error);
            });
        }
    </script>
</body>
</html>
"""

TEACHER_ATTENDANCE_INTERFACE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mark Student Attendance - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .filters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        select, input {
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            width: 100%;
        }
        .student-list {
            max-height: 500px;
            overflow-y: auto;
        }
        .student-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #e2e8f0;
        }
        .student-info h4 { margin-bottom: 0.25rem; }
        .student-info p { color: #666; font-size: 0.9rem; }
        .attendance-actions {
            display: flex;
            gap: 0.5rem;
        }
        .btn {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 500;
        }
        .btn-present { background: #48bb78; color: white; }
        .btn-absent { background: #f56565; color: white; }
        .btn-period {
            padding: 0.25rem 0.5rem;
            margin: 0.25rem;
            border: 2px solid #e2e8f0;
            background: white;
            cursor: pointer;
            border-radius: 4px;
        }
        .btn-period.selected {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        .subject-select {
            margin-bottom: 1rem;
        }
        .success-msg {
            background: #c6f6d5;
            color: #22543d;
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
            display: none;
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📝 Mark Student Attendance</h1>
    </nav>
    <div class="container">
        <div class="card">
            <div class="success-msg" id="success-msg">Attendance marked successfully!</div>
            
            <div class="filters">
                <div>
                    <label>Branch</label>
                    <select id="branch" onchange="loadStudents()">
                        {% for code, name in branches %}
                        <option value="{{ code }}">{{ name }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label>Semester</label>
                    <select id="semester" onchange="loadStudents()">
                        {% for i in range(1, 9) %}
                        <option value="{{ i }}">Semester {{ i }}</option>
                        {% endfor %}
                    </select>
                </div>
                <div>
                    <label>Section</label>
                    <select id="section" onchange="loadStudents()">
                        <option value="A">A</option>
                        <option value="B">B</option>
                        <option value="C">C</option>
                    </select>
                </div>
                <div class="subject-select">
                    <label>Subject</label>
                    <select id="subject">
                        {% for subj in subjects %}
                        <option value="{{ subj.name }}">{{ subj.code }} - {{ subj.name }}</option>
                        {% endfor %}
                    </select>
                </div>
            </div>
            
            <div>
                <label>Select Periods:</label>
                <div id="periods">
                    {% for i in range(1, 9) %}
                    <button class="btn-period" onclick="togglePeriod(this, {{ i }})">{{ i }}</button>
                    {% endfor %}
                </div>
            </div>
            
            <div style="margin-top:1rem;">
                <label>Attendance Type:</label>
                <select id="attendance_type">
                    <option value="theory">Theory</option>
                    <option value="lab">Lab</option>
                    <option value="crt">CRT</option>
                    <option value="workshop">Workshop</option>
                </select>
            </div>
        </div>
        
        <div class="card">
            <h3>Students</h3>
            <div class="student-list" id="student-list">
                <p>Select branch, semester and section to load students</p>
            </div>
        </div>
    </div>
    
    <script>
        let selectedPeriods = [];
        
        function togglePeriod(btn, period) {
            if (selectedPeriods.includes(period)) {
                selectedPeriods = selectedPeriods.filter(p => p !== period);
                btn.classList.remove('selected');
            } else {
                selectedPeriods.push(period);
                btn.classList.add('selected');
            }
        }
        
        function loadStudents() {
            const branch = document.getElementById('branch').value;
            const semester = document.getElementById('semester').value;
            const section = document.getElementById('section').value;
            
            fetch(`/teacher/get-students?branch=${branch}&semester=${semester}&section=${section}`)
                .then(response => response.json())
                .then(data => {
                    const list = document.getElementById('student-list');
                    if (data.students && data.students.length > 0) {
                        list.innerHTML = data.students.map(s => `
                            <div class="student-item" data-id="${s.id}">
                                <div class="student-info">
                                    <h4>${s.name}</h4>
                                    <p>${s.register_number} | ${s.phone}</p>
                                </div>
                                <div class="attendance-actions">
                                    <button class="btn btn-present" onclick="markStudent(${s.id}, 'present')">Present</button>
                                    <button class="btn btn-absent" onclick="markStudent(${s.id}, 'absent')">Absent</button>
                                </div>
                            </div>
                        `).join('');
                    } else {
                        list.innerHTML = '<p>No students found</p>';
                    }
                });
        }
        
        function markStudent(studentId, status) {
            if (selectedPeriods.length === 0) {
                alert('Please select at least one period');
                return;
            }
            
            const subject = document.getElementById('subject').value;
            const attendanceType = document.getElementById('attendance_type').value;
            
            fetch('/teacher/mark-student-attendance', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': '{{ csrf_token() }}'
                },
                body: JSON.stringify({
                    student_id: studentId,
                    periods: selectedPeriods,
                    status: status,
                    subject: subject,
                    attendance_type: attendanceType
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const msg = document.getElementById('success-msg');
                    msg.textContent = `Marked ${status} for ${data.student_name}`;
                    msg.style.display = 'block';
                    setTimeout(() => msg.style.display = 'none', 3000);
                } else {
                    alert(data.error || 'Failed to mark attendance');
                }
            });
        }
        
        // Load students on page load
        loadStudents();
    </script>
</body>
</html>
"""

# NEW: Teacher Daily Report with Print and PDF buttons
TEACHER_DAILY_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Daily Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 800px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .status-box {
            text-align: center;
            padding: 2rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
        }
        .status-present {
            background: #c6f6d5;
            color: #22543d;
        }
        .status-absent {
            background: #fed7d7;
            color: #c53030;
        }
        .time-display {
            font-size: 3rem;
            font-weight: bold;
            margin: 1rem 0;
        }
        .date-form {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        input, button {
            padding: 0.5rem;
            border: 2px solid #e2e8f0;
            border-radius: 5px;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            cursor: pointer;
        }
        .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 1rem;
        }
        .btn-pdf { background: #ed8936; }
        @media print {
            .navbar, .date-form, .btn-print, .btn-pdf { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📅 Daily Attendance Report</h1>
    </nav>
    <div class="container">
        <div class="card">
            <h2>Attendance for {{ date.strftime('%d %B %Y') }}</h2>
            <form class="date-form" method="get">
                <input type="date" name="date" value="{{ date.strftime('%Y-%m-%d') }}">
                <button type="submit">View</button>
            </form>
            
            <button class="btn-print" onclick="window.print()">🖨️ Print</button>
            <a href="{{ url_for('download_pdf_teacher', report_type='daily', date=date.strftime('%Y-%m-%d')) }}" class="btn-pdf">📄 Download PDF</a>
            
            {% if attendance %}
            <div class="status-box {% if attendance.status == 'present' %}status-present{% else %}status-absent{% endif %}">
                <h3>Status: {{ attendance.status.title() }}</h3>
                {% if attendance.check_in %}
                <div class="time-display">{{ attendance.check_in.strftime('%H:%M') }}</div>
                <p>Check-in Time</p>
                {% endif %}
                {% if attendance.check_out %}
                <p style="margin-top:1rem;">Check-out: {{ attendance.check_out.strftime('%H:%M') }}</p>
                {% endif %}
                {% if attendance.location_verified %}
                <p style="margin-top:1rem;">✓ Location Verified</p>
                {% endif %}
            </div>
            {% else %}
            <div class="status-box status-absent">
                <h3>No attendance record found</h3>
                <p>You did not mark attendance on this date</p>
            </div>
            {% endif %}
            
            <a href="{{ url_for('teacher_dashboard') }}" style="color:#667eea;text-decoration:none;">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

# NEW: Teacher Monthly Report with Print and PDF buttons
TEACHER_MONTHLY_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Monthly Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        .stat {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1.5rem;
            border-radius: 10px;
            text-align: center;
        }
        .stat h3 { font-size: 2rem; margin-bottom: 0.5rem; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .month-form {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        select, button {
            padding: 0.5rem;
            border: 2px solid #e2e8f0;
            border-radius: 5px;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            cursor: pointer;
        }
        .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 1rem;
        }
        .btn-pdf { background: #ed8936; }
        @media print {
            .navbar, .month-form, .btn-print, .btn-pdf { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📊 Monthly Attendance Report</h1>
    </nav>
    <div class="container">
        <div class="card">
            <h2>{{ month_name }} {{ year }}</h2>
            <form class="month-form" method="get">
                <select name="month">
                    {% for i in range(1, 13) %}
                    <option value="{{ i }}" {% if i == month %}selected{% endif %}>{{ datetime(2000, i, 1).strftime('%B') }}</option>
                    {% endfor %}
                </select>
                <select name="year">
                    {% for y in range(2020, 2027) %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>{{ y }}</option>
                    {% endfor %}
                </select>
                <button type="submit">View</button>
            </form>
            
            <button class="btn-print" onclick="window.print()">🖨️ Print</button>
            <a href="{{ url_for('download_pdf_teacher', report_type='monthly', month=month, year=year) }}" class="btn-pdf">📄 Download PDF</a>
            
            <div class="stats">
                <div class="stat">
                    <h3>{{ total_present }}</h3>
                    <p>Days Present</p>
                </div>
                <div class="stat">
                    <h3>{{ total_days }}</h3>
                    <p>Total Records</p>
                </div>
                <div class="stat">
                    <h3>{{ "%.1f"|format((total_present/total_days*100) if total_days else 0) }}%</h3>
                    <p>Attendance Rate</p>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Check In</th>
                        <th>Check Out</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for att in attendances %}
                    <tr>
                        <td>{{ att.date.strftime('%d %b %Y') }}</td>
                        <td>{{ att.check_in.strftime('%H:%M') if att.check_in else '-' }}</td>
                        <td>{{ att.check_out.strftime('%H:%M') if att.check_out else '-' }}</td>
                        <td>{{ att.status.title() }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            
            <a href="{{ url_for('teacher_dashboard') }}" style="display:inline-block;margin-top:1rem;color:#667eea;text-decoration:none;">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

# NEW: Teacher Yearly Report with Print and PDF buttons
TEACHER_YEARLY_REPORT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Yearly Report - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .year-form {
            display: flex;
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        select, button {
            padding: 0.5rem;
            border: 2px solid #e2e8f0;
            border-radius: 5px;
        }
        button {
            background: #667eea;
            color: white;
            border: none;
            cursor: pointer;
        }
        .month-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 1rem;
        }
        .month-card {
            background: #f7fafc;
            padding: 1.5rem;
            border-radius: 10px;
            border-left: 4px solid #667eea;
        }
        .month-card h4 {
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        .btn-print, .btn-pdf {
            padding: 0.5rem 1rem;
            background: #48bb78;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            margin-right: 0.5rem;
            margin-bottom: 1.5rem;
        }
        .btn-pdf { background: #ed8936; }
        @media print {
            .navbar, .year-form, .btn-print, .btn-pdf { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📈 Yearly Attendance Report</h1>
    </nav>
    <div class="container">
        <div class="card">
            <h2>Year {{ year }}</h2>
            <form class="year-form" method="get">
                <select name="year">
                    {% for y in range(2020, 2027) %}
                    <option value="{{ y }}" {% if y == year %}selected{% endif %}>{{ y }}</option>
                    {% endfor %}
                </select>
                <button type="submit">View</button>
            </form>
            
            <button class="btn-print" onclick="window.print()">🖨️ Print</button>
            <a href="{{ url_for('download_pdf_teacher', report_type='yearly', year=year) }}" class="btn-pdf">📄 Download PDF</a>
            
            <div style="margin-bottom:1.5rem;">
                <p><strong>Registration Date:</strong> {{ yearly_data['start_date'].strftime('%d %b %Y') }}</p>
                <p><strong>Total Days Present:</strong> {{ yearly_data['total_days_present'] }}</p>
                <p><strong>Working Days:</strong> {{ yearly_data['working_days'] }}</p>
                <p><strong>Attendance Rate:</strong> {{ "%.1f"|format(yearly_data['percentage']) }}%</p>
            </div>
            
            <h3 style="margin-bottom:1rem;">Monthly Breakdown</h3>
            <div class="month-grid">
                {% for month_key, data in yearly_data['monthly_breakdown'].items()|sort %}
                <div class="month-card">
                    <h4>{{ data['month_name'] }}</h4>
                    <p>Days Present: {{ data['days_present'] }}</p>
                    <p>Check-ins: {{ data['check_ins']|length }}</p>
                </div>
                {% endfor %}
            </div>
            
            <a href="{{ url_for('teacher_dashboard') }}" style="display:inline-block;margin-top:1.5rem;color:#667eea;text-decoration:none;">← Back to Dashboard</a>
        </div>
    </div>
</body>
</html>
"""

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Admin Dashboard - SVIST</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: white;
            padding: 1rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .nav-links a {
            color: white;
            text-decoration: none;
            margin-left: 1.5rem;
        }
        .container {
            max-width: 1400px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: white;
            padding: 1.5rem;
            border-radius: 15px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            border-left: 4px solid #667eea;
        }
        .stat-card h3 {
            font-size: 2.5rem;
            color: #667eea;
            margin-bottom: 0.5rem;
        }
        .stat-card p { color: #666; }
        .card {
            background: white;
            border-radius: 15px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card h3 {
            margin-bottom: 1rem;
            color: #333;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 0.5rem;
        }
        .btn {
            display: inline-block;
            padding: 0.75rem 1.5rem;
            background: #667eea;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            margin-right: 0.5rem;
            margin-bottom: 0.5rem;
        }
        .btn-danger { background: #f56565; }
        .btn-success { background: #48bb78; }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>⚙️ Admin Dashboard</h1>
        <div class="nav-links">
            <a href="{{ url_for('admin_stop_semester') }}">Stop Semester</a>
            <a href="{{ url_for('admin_manage_subjects') }}">Subjects</a>
            <a href="{{ url_for('admin_student_reports') }}">Student Reports</a>
            <a href="{{ url_for('admin_teacher_reports') }}">Teacher Reports</a>
            <a href="{{ url_for('logout') }}">Logout</a>
        </div>
    </nav>
    
    <div class="container">
        <div class="stats-grid">
            <div class="stat-card">
                <h3>{{ total_students }}</h3>
                <p>Total Students</p>
            </div>
            <div class="stat-card">
                <h3>{{ total_teachers }}</h3>
                <p>Total Teachers</p>
            </div>
            <div class="stat-card">
                <h3>{{ active_semesters }}</h3>
                <p>Active Semesters</p>
            </div>
            <div class="stat-card">
                <h3>{{ today_teacher_attendance }}</h3>
                <p>Teachers Present Today</p>
            </div>
        </div>
        
        <div class="card">
            <h3>Quick Actions</h3>
            <a href="{{ url_for('admin_stop_semester') }}" class="btn btn-danger">Stop Semester</a>
            <a href="{{ url_for('admin_manage_subjects') }}" class="btn">Manage Subjects</a>
            <a href="{{ url_for('admin_student_reports') }}" class="btn btn-success">Student Reports</a>
            <a href="{{ url_for('admin_teacher_reports') }}" class="btn">Teacher Reports</a>
        </div>
        
        <div class="card">
            <h3>Create New Admin</h3>
            <form method="post" action="{{ url_for('admin_create_admin') }}">
                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                <div style="display:grid;grid-template-columns:1fr 1fr auto;gap:1rem;align-items:end;">
                    <div>
                        <label>Email</label>
                        <input type="email" name="email" required style="width:100%;padding:0.5rem;border:2px solid #e2e8f0;border-radius:5px;">
                    </div>
                    <div>
                        <label>Password</label>
                        <input type="password" name="password" required style="width:100%;padding:0.5rem;border:2px solid #e2e8f0;border-radius:5px;">
                    </div>
                    <button type="submit" class="btn" style="margin:0;">Create Admin</button>
                </div>
            </form>
        </div>
        
        <div class="card">
            <h3>Recent Activity</h3>
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for log in recent_logs %}
                    <tr>
                        <td>{{ log.timestamp.strftime('%d %b %Y %H:%M') }}</td>
                        <td>{{ log.action }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""

ADMIN_STOP_SEMESTER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Stop Semester - Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1000px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .form-group {
            margin-bottom: 1rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            color: #555;
        }
        select, button {
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            width: 100%;
        }
        button {
            background: #f56565;
            color: white;
            border: none;
            cursor: pointer;
            font-weight: 600;
            margin-top: 1rem;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .btn-reactivate {
            background: #48bb78;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            cursor: pointer;
        }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-success { background: #c6f6d5; color: #22543d; }
        .alert-danger { background: #fed7d7; color: #c53030; }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>🛑 Stop Semester</h1>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="card">
            <h3 style="margin-bottom:1rem;">Stop Semester Attendance</h3>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;">
                    <div class="form-group">
                        <label>Branch</label>
                        {{ form.branch() }}
                    </div>
                    <div class="form-group">
                        <label>Semester</label>
                        {{ form.semester() }}
                    </div>
                </div>
                <button type="submit">Stop Semester</button>
            </form>
            <p style="margin-top:1rem;color:#666;font-size:0.9rem;">
                This will freeze attendance for all students in the selected branch and semester.
                Their current attendance data will be archived.
            </p>
        </div>
        
        <div class="card">
            <h3>Stopped Semesters</h3>
            <table>
                <thead>
                    <tr>
                        <th>Branch</th>
                        <th>Semester</th>
                        <th>Stopped At</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for stop in stopped_list %}
                    <tr>
                        <td>{{ stop.branch }}</td>
                        <td>{{ stop.semester }}</td>
                        <td>{{ stop.stopped_at.strftime('%d %b %Y %H:%M') }}</td>
                        <td>
                            <form method="post" action="{{ url_for('admin_reactivate_semester', stop_id=stop.id) }}" style="display:inline;">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                <button type="submit" class="btn-reactivate">Reactivate</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <a href="{{ url_for('admin_dashboard') }}" style="color:#667eea;text-decoration:none;">← Back to Dashboard</a>
    </div>
</body>
</html>
"""

ADMIN_MANAGE_SUBJECTS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Manage Subjects - Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1200px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }
        input, select {
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            width: 100%;
        }
        button {
            padding: 0.75rem 1.5rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .btn-delete {
            background: #f56565;
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 5px;
            cursor: pointer;
        }
        .alert {
            padding: 1rem;
            border-radius: 8px;
            margin-bottom: 1rem;
        }
        .alert-success { background: #c6f6d5; color: #22543d; }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📚 Manage Subjects</h1>
    </nav>
    <div class="container">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <div class="card">
            <h3 style="margin-bottom:1rem;">Add New Subject</h3>
            <form method="POST">
                {{ form.hidden_tag() }}
                <div class="form-grid">
                    <div>
                        <label>Subject Code</label>
                        {{ form.code(placeholder="e.g., 20CS1101") }}
                    </div>
                    <div>
                        <label>Subject Name</label>
                        {{ form.name(placeholder="e.g., Data Structures") }}
                    </div>
                    <div>
                        <label>Branch</label>
                        {{ form.branch() }}
                    </div>
                    <div>
                        <label>Semester</label>
                        {{ form.semester() }}
                    </div>
                    <div>
                        <label>Type</label>
                        {{ form.subject_type() }}
                    </div>
                </div>
                <button type="submit" style="margin-top:1rem;">Add Subject</button>
            </form>
        </div>
        
        <div class="card">
            <h3>All Subjects</h3>
            <table>
                <thead>
                    <tr>
                        <th>Code</th>
                        <th>Name</th>
                        <th>Branch</th>
                        <th>Semester</th>
                        <th>Type</th>
                        <th>Action</th>
                    </tr>
                </thead>
                <tbody>
                    {% for subject in subjects %}
                    <tr>
                        <td>{{ subject.code }}</td>
                        <td>{{ subject.name }}</td>
                        <td>{{ subject.branch }}</td>
                        <td>{{ subject.semester }}</td>
                        <td>{{ subject.subject_type.title() }}</td>
                        <td>
                            <form method="post" action="{{ url_for('admin_delete_subject', subject_id=subject.id) }}" style="display:inline;">
                                <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
                                <button type="submit" class="btn-delete">Delete</button>
                            </form>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <a href="{{ url_for('admin_dashboard') }}" style="color:#667eea;text-decoration:none;">← Back to Dashboard</a>
    </div>
</body>
</html>
"""

# FIXED: Updated admin student reports template with Print, PDF, and semester option
# All reports now sorted by register_number
ADMIN_STUDENT_REPORTS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Student Reports - Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1400px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .filters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        select, input {
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            width: 100%;
        }
        .btn {
            padding: 0.75rem 1.5rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
        }
        .btn-success { background: #48bb78; }
        .btn-print { background: #4299e1; }
        .btn-pdf { background: #ed8936; }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        .low-attendance { color: #e53e3e; font-weight: 600; }
        .action-btns {
            margin-bottom: 1.5rem;
        }
        @media print {
            .navbar, .filters, form, .action-btns { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>📊 Student Attendance Reports</h1>
    </nav>
    <div class="container">
        <div class="card">
            <form method="get">
                <div class="filters">
                    <div>
                        <label>Report Type</label>
                        <select name="report_type" onchange="this.form.submit()">
                            <option value="daily" {% if report_type == 'daily' %}selected{% endif %}>Daily</option>
                            <option value="monthly" {% if report_type == 'monthly' %}selected{% endif %}>Monthly</option>
                            <option value="semester" {% if report_type == 'semester' %}selected{% endif %}>Semester</option>
                        </select>
                    </div>
                    <div>
                        <label>Branch</label>
                        <select name="branch">
                            {% for b in branches %}
                            <option value="{{ b }}" {% if b == selected_branch %}selected{% endif %}>{{ b.upper() }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>Semester</label>
                        <select name="semester">
                            {% for s in semesters %}
                            <option value="{{ s }}" {% if s|string == selected_semester %}selected{% endif %}>{{ s if s != 'all' else 'All' }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>Section</label>
                        <select name="section">
                            {% for sec in sections %}
                            <option value="{{ sec }}" {% if sec == selected_section %}selected{% endif %}>{{ sec.upper() }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% if report_type == 'daily' %}
                    <div>
                        <label>Date</label>
                        <input type="date" name="date" value="{{ date.strftime('%Y-%m-%d') }}">
                    </div>
                    {% elif report_type == 'monthly' %}
                    <div>
                        <label>Month</label>
                        <select name="month">
                            {% for i in range(1, 13) %}
                            <option value="{{ i }}" {% if i == month|int %}selected{% endif %}>{{ datetime(2000, i, 1).strftime('%B') }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>Year</label>
                        <select name="year">
                            {% for y in range(2020, 2027) %}
                            <option value="{{ y }}" {% if y == year|int %}selected{% endif %}>{{ y }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    {% endif %}
                </div>
                <button type="submit" class="btn">Generate Report</button>
                <a href="{{ url_for('admin_export_attendance', report_type=report_type, branch=selected_branch, semester=selected_semester, section=selected_section, date=date.strftime('%Y-%m-%d') if report_type == 'daily' else None, month=month if report_type == 'monthly' else None, year=year if report_type == 'monthly' else None) }}" class="btn btn-success">Export CSV</a>
            </form>
        </div>
        
        {% if data %}
        <div class="card">
            <h3>Report Results (Sorted by Register Number)</h3>
            <div class="action-btns">
                <button class="btn btn-print" onclick="window.print()">🖨️ Print</button>
                <a href="{{ url_for('download_pdf_admin', report_type=report_type, branch=selected_branch, semester=selected_semester, section=selected_section, date=date.strftime('%Y-%m-%d') if report_type == 'daily' else None, month=month if report_type == 'monthly' else None, year=year if report_type == 'monthly' else None) }}" class="btn btn-pdf">📄 Download PDF</a>
            </div>
            {% if report_type == 'daily' %}
            <table>
                <thead>
                    <tr>
                        <th>Register No</th>
                        <th>Name</th>
                        <th>Branch</th>
                        <th>Sem</th>
                        <th>Sec</th>
                        <th>Periods</th>
                        <th>Present</th>
                        <th>Total</th>
                        <th>%</th>
                    </tr>
                </thead>
                <tbody>
                    {% for student_id, info in data.items() %}
                    <tr>
                        <td>{{ info['student'].register_number }}</td>
                        <td>{{ info['student'].name }}</td>
                        <td>{{ info['student'].branch }}</td>
                        <td>{{ info['student'].current_semester }}</td>
                        <td>{{ info['student'].section }}</td>
                        <td>{{ info['periods']|length }}</td>
                        <td>{{ info['present_count'] }}</td>
                        <td>{{ info['total_count'] }}</td>
                        <td class="{% if (info['present_count']/info['total_count']*100) < 75 %}low-attendance{% endif %}">
                            {{ "%.1f"|format((info['present_count']/info['total_count']*100) if info['total_count'] else 0) }}%
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% elif report_type == 'monthly' %}
            <table>
                <thead>
                    <tr>
                        <th>Register No</th>
                        <th>Name</th>
                        <th>Branch</th>
                        <th>Sem</th>
                        <th>Sec</th>
                        <th>Theory</th>
                        <th>Practical</th>
                        <th>Overall %</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in data %}
                    <tr>
                        <td>{{ item['student'].register_number }}</td>
                        <td>{{ item['student'].name }}</td>
                        <td>{{ item['student'].branch }}</td>
                        <td>{{ item['student'].current_semester }}</td>
                        <td>{{ item['student'].section }}</td>
                        <td>{{ item['theory_present'] }}/{{ item['theory_total'] }}</td>
                        <td>{{ item['practical_present'] }}/{{ item['practical_total'] }}</td>
                        <td class="{% if item['overall_percentage'] < 75 %}low-attendance{% endif %}">
                            {{ "%.1f"|format(item['overall_percentage']) }}%
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% elif report_type == 'semester' %}
            <table>
                <thead>
                    <tr>
                        <th>Register No</th>
                        <th>Name</th>
                        <th>Branch</th>
                        <th>Sem</th>
                        <th>Sec</th>
                        <th>Theory %</th>
                        <th>Practical %</th>
                        <th>Overall %</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in data %}
                    <tr>
                        <td>{{ item['student'].register_number }}</td>
                        <td>{{ item['student'].name }}</td>
                        <td>{{ item['student'].branch }}</td>
                        <td>{{ item['student'].current_semester }}</td>
                        <td>{{ item['student'].section }}</td>
                        <td>{{ "%.1f"|format(item['theory_percentage']) }}%</td>
                        <td>{{ "%.1f"|format(item['practical_percentage']) }}%</td>
                        <td class="{% if item['overall_percentage'] < 75 %}low-attendance{% endif %}">
                            {{ "%.1f"|format(item['overall_percentage']) }}%
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
        </div>
        {% endif %}
        
        <a href="{{ url_for('admin_dashboard') }}" style="color:#667eea;text-decoration:none;">← Back to Dashboard</a>
    </div>
</body>
</html>
"""

ADMIN_TEACHER_REPORTS_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Teacher Reports - Admin</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f7fafc;
            min-height: 100vh;
        }
        .navbar {
            background: linear-gradient(135deg, #1a202c 0%, #2d3748 100%);
            color: white;
            padding: 1rem 2rem;
        }
        .container {
            max-width: 1400px;
            margin: 2rem auto;
            padding: 0 1rem;
        }
        .card {
            background: white;
            border-radius: 15px;
            padding: 2rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .filters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
            margin-bottom: 1.5rem;
        }
        input, select {
            padding: 0.75rem;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            width: 100%;
        }
        button {
            padding: 0.75rem 1.5rem;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            cursor: pointer;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 1rem;
        }
        th, td {
            padding: 0.75rem;
            border-bottom: 1px solid #e2e8f0;
        }
        th { background: #f7fafc; }
        
        /* ACTION BUTTONS - FIXED TO MATCH EACH OTHER */
        .action-buttons {
            display: flex;
            gap: 10px;
            align-items: center;
            margin-bottom: 1.5rem;
        }

        .btn-action {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid transparent;
            text-decoration: none;
            line-height: 1.4;
            height: 36px;
        }

        /* Print Button - Gray style */
        .btn-print {
            background: #f3f4f6;
            color: #374151;
            border-color: #d1d5db;
        }

        .btn-print:hover {
            background: #e5e7eb;
            border-color: #9ca3af;
        }

        /* Download PDF Button - NOW MATCHES PRINT BUTTON STYLE */
        .btn-download {
            background: #f3f4f6;
            color: #dc2626;
            border-color: #d1d5db;
        }

        .btn-download:hover {
            background: #fee2e2;
            border-color: #fca5a5;
        }

        /* Icons */
        .btn-action svg {
            width: 14px;
            height: 14px;
            flex-shrink: 0;
        }
        
        @media print {
            .navbar, .filters, form, .action-buttons { display: none; }
            .card { box-shadow: none; }
        }
    </style>
</head>
<body>
    <nav class="navbar">
        <h1>👨‍🏫 Teacher Attendance Reports</h1>
    </nav>
    <div class="container">
        <div class="card">
            <form method="get">
                <div class="filters">
                    <div>
                        <label>Branch</label>
                        <select name="branch">
                            {% for b in branches %}
                            <option value="{{ b }}" {% if b == selected_branch %}selected{% endif %}>{{ b.upper() }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>Teacher Name</label>
                        <input type="text" name="name" value="{{ name or '' }}" placeholder="Search by name">
                    </div>
                    <div>
                        <label>Month (optional)</label>
                        <select name="month">
                            <option value="">All</option>
                            {% for i in range(1, 13) %}
                            <option value="{{ i }}" {% if month|int == i %}selected{% endif %}>{{ datetime(2000, i, 1).strftime('%B') }}</option>
                            {% endfor %}
                        </select>
                    </div>
                    <div>
                        <label>Year (optional)</label>
                        <select name="year">
                            <option value="">All</option>
                            {% for y in range(2020, 2027) %}
                            <option value="{{ y }}" {% if year|int == y %}selected{% endif %}>{{ y }}</option>
                            {% endfor %}
                        </select>
                    </div>
                </div>
                <button type="submit">Generate Report</button>
            </form>
        </div>
        
        {% if data %}
        <div class="card">
            <h3>Teacher Attendance</h3>
            <div class="action-buttons">
                <button class="btn-action btn-print" onclick="window.print()">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"></path>
                    </svg>
                    Print
                </button>
                <a href="{{ url_for('download_pdf_admin_teacher', branch=selected_branch, name=name, month=month, year=year) }}" class="btn-action btn-download">
                    <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    Download PDF
                </a>
            </div>
            <table>
                <thead>
                    <tr>
                        <th>Employee ID</th>
                        <th>Name</th>
                        <th>Branch</th>
                        <th>Role</th>
                        <th>Present Days</th>
                        <th>Total Days</th>
                        <th>Percentage</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in data %}
                    <tr>
                        <td>{{ item['teacher'].employee_id }}</td>
                        <td>{{ item['teacher'].name }}</td>
                        <td>{{ item['teacher'].branch }}</td>
                        <td>{{ item['teacher'].role }}</td>
                        <td>{{ item['present_days'] }}</td>
                        <td>{{ item['total_days'] }}</td>
                        <td>{{ "%.1f"|format((item['present_days']/item['total_days']*100) if item['total_days'] else 0) }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
        
        <a href="{{ url_for('admin_dashboard') }}" style="color:#667eea;text-decoration:none;">← Back to Dashboard</a>
    </div>
</body>
</html>
"""


# ============================================
# PDF GENERATION ROUTES
# ============================================

# Student PDF download routes
@app.route('/download-pdf/student')
@login_required
def download_pdf():
    """Generate PDF for student reports"""
    if current_user.role != 'student':
        return redirect(url_for('login'))
    
    report_type = request.args.get('report_type', 'daily')
    student = current_user.student
    
    # Create HTML content for PDF
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #667eea; text-align: center; }}
            h2 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #667eea; color: white; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; margin-bottom: 10px; }}
            .info {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🎓 SVIST Attendance System</div>
            <h1>Sree Vahini Institute of Science and Technology</h1>
            <p>Student Attendance Report</p>
        </div>
        
        <div class="info">
            <p><strong>Student Name:</strong> {student.name}</p>
            <p><strong>Register Number:</strong> {student.register_number}</p>
            <p><strong>Branch:</strong> {student.branch}</p>
            <p><strong>Semester:</strong> {student.current_semester}</p>
            <p><strong>Section:</strong> {student.section}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%d %b %Y %H:%M')}</p>
        </div>
    """
    
    if report_type == 'daily':
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        attendances = Attendance.query.filter_by(student_id=student.id, date=report_date).order_by(Attendance.period).all()
        
        html_content += f"<h2>Daily Report - {report_date.strftime('%d %B %Y')}</h2>"
        html_content += "<table><thead><tr><th>Period</th><th>Subject</th><th>Type</th><th>Status</th></tr></thead><tbody>"
        
        for att in attendances:
            html_content += f"<tr><td>{att.period}</td><td>{att.subject or '-'}</td><td>{att.attendance_type.title()}</td><td>{att.status.title()}</td></tr>"
        
        html_content += "</tbody></table>"
    
    elif report_type == 'monthly':
        month = int(request.args.get('month', datetime.now().month))
        year = int(request.args.get('year', datetime.now().year))
        
        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
        
        attendances = Attendance.query.filter(
            Attendance.student_id == student.id,
            Attendance.date >= start_date,
            Attendance.date <= end_date
        ).order_by(Attendance.date, Attendance.period).all()
        
        total_present = sum(1 for a in attendances if a.status == 'present')
        total_classes = len(attendances)
        percentage = (total_present/total_classes*100) if total_classes > 0 else 0
        
        html_content += f"<h2>Monthly Report - {datetime(year, month, 1).strftime('%B %Y')}</h2>"
        html_content += f"<p><strong>Total Present:</strong> {total_present} | <strong>Total Classes:</strong> {total_classes} | <strong>Percentage:</strong> {percentage:.1f}%</p>"
        html_content += "<table><thead><tr><th>Date</th><th>Period</th><th>Subject</th><th>Type</th><th>Status</th></tr></thead><tbody>"
        
        for att in attendances:
            html_content += f"<tr><td>{att.date.strftime('%d %b %Y')}</td><td>{att.period}</td><td>{att.subject or '-'}</td><td>{att.attendance_type.title()}</td><td>{att.status.title()}</td></tr>"
        
        html_content += "</tbody></table>"
    
    elif report_type == 'semester':
        sem_data = get_comprehensive_attendance(student)
        
        html_content += f"<h2>Semester Report - Semester {student.current_semester}</h2>"
        html_content += f"<p><strong>Period:</strong> {sem_data['start_date'].strftime('%d %b %Y')} - {sem_data['end_date'].strftime('%d %b %Y')}</p>"
        html_content += f"<p><strong>Overall Attendance:</strong> {sem_data['overall_percentage']:.1f}%</p>"
        html_content += f"<p><strong>Theory:</strong> {sem_data['theory_present']}/{sem_data['theory_total']} ({sem_data['theory_percentage']:.1f}%)</p>"
        html_content += f"<p><strong>Practical:</strong> {sem_data['practical_present']}/{sem_data['practical_total']} ({sem_data['practical_percentage']:.1f}%)</p>"
        
        html_content += "<h3>Subject-wise Breakdown</h3>"
        html_content += "<table><thead><tr><th>Subject</th><th>Type</th><th>Present</th><th>Total</th><th>Percentage</th></tr></thead><tbody>"
        
        for subject, data in sem_data['subject_wise'].items():
            html_content += f"<tr><td>{subject}</td><td>{data['type'].title()}</td><td>{data['present']}</td><td>{data['total']}</td><td>{data['percentage']:.1f}%</td></tr>"
        
        html_content += "</tbody></table>"
    
    html_content += "</body></html>"
    
    # Generate PDF using pdfkit or return HTML for browser print
    # For now, return HTML with print dialog
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html'
    return response

# Teacher PDF download routes
@app.route('/download-pdf/teacher')
@login_required
def download_pdf_teacher():
    """Generate PDF for teacher reports"""
    if current_user.role != 'teacher':
        return redirect(url_for('login'))
    
    report_type = request.args.get('report_type', 'daily')
    teacher = current_user.teacher
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #667eea; text-align: center; }}
            h2 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #667eea; color: white; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; margin-bottom: 10px; }}
            .info {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🎓 SVIST Attendance System</div>
            <h1>Sree Vahini Institute of Science and Technology</h1>
            <p>Teacher Attendance Report</p>
        </div>
        
        <div class="info">
            <p><strong>Teacher Name:</strong> {teacher.name}</p>
            <p><strong>Employee ID:</strong> {teacher.employee_id}</p>
            <p><strong>Branch:</strong> {teacher.branch}</p>
            <p><strong>Role:</strong> {teacher.role}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%d %b %Y %H:%M')}</p>
        </div>
    """
    
    if report_type == 'daily':
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        attendance = TeacherAttendance.query.filter_by(teacher_id=teacher.id, date=report_date).first()
        
        html_content += f"<h2>Daily Report - {report_date.strftime('%d %B %Y')}</h2>"
        
        if attendance:
            html_content += f"<p><strong>Status:</strong> {attendance.status.title()}</p>"
            if attendance.check_in:
                html_content += f"<p><strong>Check-in:</strong> {attendance.check_in.strftime('%H:%M')}</p>"
            if attendance.check_out:
                html_content += f"<p><strong>Check-out:</strong> {attendance.check_out.strftime('%H:%M')}</p>"
            html_content += f"<p><strong>Location Verified:</strong> {'Yes' if attendance.location_verified else 'No'}</p>"
        else:
            html_content += "<p>No attendance record found for this date.</p>"
    
    elif report_type == 'monthly':
        month = int(request.args.get('month', datetime.now().month))
        year = int(request.args.get('year', datetime.now().year))
        
        start_date = datetime(year, month, 1).date()
        if month == 12:
            end_date = datetime(year + 1, 1, 1).date() - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1).date() - timedelta(days=1)
        
        attendances = TeacherAttendance.query.filter(
            TeacherAttendance.teacher_id == teacher.id,
            TeacherAttendance.date >= start_date,
            TeacherAttendance.date <= end_date
        ).order_by(TeacherAttendance.date).all()
        
        total_present = sum(1 for a in attendances if a.status == 'present')
        
        html_content += f"<h2>Monthly Report - {datetime(year, month, 1).strftime('%B %Y')}</h2>"
        html_content += f"<p><strong>Days Present:</strong> {total_present} | <strong>Total Records:</strong> {len(attendances)}</p>"
        html_content += "<table><thead><tr><th>Date</th><th>Check In</th><th>Check Out</th><th>Status</th></tr></thead><tbody>"
        
        for att in attendances:
            check_in = att.check_in.strftime('%H:%M') if att.check_in else '-'
            check_out = att.check_out.strftime('%H:%M') if att.check_out else '-'
            html_content += f"<tr><td>{att.date.strftime('%d %b %Y')}</td><td>{check_in}</td><td>{check_out}</td><td>{att.status.title()}</td></tr>"
        
        html_content += "</tbody></table>"
    
    elif report_type == 'yearly':
        year = int(request.args.get('year', datetime.now().year))
        yearly_data = get_teacher_yearly_attendance(teacher, year)
        
        html_content += f"<h2>Yearly Report - {year}</h2>"
        html_content += f"<p><strong>Registration Date:</strong> {yearly_data['start_date'].strftime('%d %b %Y')}</p>"
        html_content += f"<p><strong>Days Present:</strong> {yearly_data['total_days_present']}</p>"
        html_content += f"<p><strong>Working Days:</strong> {yearly_data['working_days']}</p>"
        html_content += f"<p><strong>Attendance Rate:</strong> {yearly_data['percentage']:.1f}%</p>"
        
        html_content += "<h3>Monthly Breakdown</h3>"
        html_content += "<table><thead><tr><th>Month</th><th>Days Present</th></tr></thead><tbody>"
        
        for month_key, data in sorted(yearly_data['monthly_breakdown'].items()):
            html_content += f"<tr><td>{data['month_name']}</td><td>{data['days_present']}</td></tr>"
        
        html_content += "</tbody></table>"
    
    html_content += "</body></html>"
    
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html'
    return response

# Admin PDF download routes
@app.route('/download-pdf/admin/students')
@login_required
@admin_required
def download_pdf_admin():
    """Generate PDF for admin student reports"""
    report_type = request.args.get('report_type', 'daily')
    branch = request.args.get('branch', 'all')
    semester = request.args.get('semester', 'all')
    section = request.args.get('section', 'all')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #667eea; text-align: center; }}
            h2 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 12px; }}
            th, td {{ padding: 8px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #667eea; color: white; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; margin-bottom: 10px; }}
            .info {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🎓 SVIST Attendance System</div>
            <h1>Sree Vahini Institute of Science and Technology</h1>
            <p>Admin Student Attendance Report</p>
        </div>
        
        <div class="info">
            <p><strong>Report Type:</strong> {report_type.title()}</p>
            <p><strong>Branch:</strong> {branch.upper()}</p>
            <p><strong>Semester:</strong> {semester}</p>
            <p><strong>Section:</strong> {section.upper()}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%d %b %Y %H:%M')}</p>
        </div>
    """
    
    if report_type == 'daily':
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        report_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        data = get_daily_attendance(branch, semester, section, report_date)
        
        html_content += f"<h2>Daily Report - {report_date.strftime('%d %B %Y')}</h2>"
        html_content += "<table><thead><tr><th>Register No</th><th>Name</th><th>Branch</th><th>Sem</th><th>Sec</th><th>Present</th><th>Total</th><th>%</th></tr></thead><tbody>"
        
        for student_id, info in data.items():
            student = info['student']
            percentage = (info['present_count'] / info['total_count'] * 100) if info['total_count'] > 0 else 0
            html_content += f"<tr><td>{student.register_number}</td><td>{student.name}</td><td>{student.branch}</td><td>{student.current_semester}</td><td>{student.section}</td><td>{info['present_count']}</td><td>{info['total_count']}</td><td>{percentage:.1f}%</td></tr>"
        
        html_content += "</tbody></table>"
    
    elif report_type == 'monthly':
        month = int(request.args.get('month', datetime.now().month))
        year = int(request.args.get('year', datetime.now().year))
        data, start_date, end_date = get_monthly_attendance(branch, semester, section, month, year)
        
        html_content += f"<h2>Monthly Report - {datetime(year, month, 1).strftime('%B %Y')}</h2>"
        html_content += "<table><thead><tr><th>Register No</th><th>Name</th><th>Branch</th><th>Sem</th><th>Sec</th><th>Theory</th><th>Practical</th><th>Overall %</th></tr></thead><tbody>"
        
        for item in data:
            student = item['student']
            html_content += f"<tr><td>{student.register_number}</td><td>{student.name}</td><td>{student.branch}</td><td>{student.current_semester}</td><td>{student.section}</td><td>{item['theory_present']}/{item['theory_total']}</td><td>{item['practical_present']}/{item['practical_total']}</td><td>{item['overall_percentage']:.1f}%</td></tr>"
        
        html_content += "</tbody></table>"
    
    elif report_type == 'semester':
        data = get_semester_attendance(branch, semester, section)
        
        html_content += f"<h2>Semester Report</h2>"
        html_content += "<table><thead><tr><th>Register No</th><th>Name</th><th>Branch</th><th>Sem</th><th>Sec</th><th>Theory %</th><th>Practical %</th><th>Overall %</th></tr></thead><tbody>"
        
        for item in data:
            student = item['student']
            html_content += f"<tr><td>{student.register_number}</td><td>{student.name}</td><td>{student.branch}</td><td>{student.current_semester}</td><td>{student.section}</td><td>{item['theory_percentage']:.1f}%</td><td>{item['practical_percentage']:.1f}%</td><td>{item['overall_percentage']:.1f}%</td></tr>"
        
        html_content += "</tbody></table>"
    
    html_content += "</body></html>"
    
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html'
    return response

@app.route('/download-pdf/admin/teachers')
@login_required
@admin_required
def download_pdf_admin_teacher():
    """Generate PDF for admin teacher reports"""
    branch = request.args.get('branch', 'all')
    name = request.args.get('name', '')
    month = request.args.get('month')
    year = request.args.get('year')
    
    data = get_teacher_attendance_report(
        branch if branch != 'all' else None,
        name if name else None,
        month,
        year
    )
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; }}
            h1 {{ color: #667eea; text-align: center; }}
            h2 {{ color: #333; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ padding: 10px; border: 1px solid #ddd; text-align: left; }}
            th {{ background-color: #667eea; color: white; }}
            .header {{ text-align: center; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; margin-bottom: 10px; }}
            .info {{ margin-bottom: 20px; }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">🎓 SVIST Attendance System</div>
            <h1>Sree Vahini Institute of Science and Technology</h1>
            <p>Admin Teacher Attendance Report</p>
        </div>
        
        <div class="info">
            <p><strong>Branch:</strong> {branch.upper()}</p>
            <p><strong>Name Filter:</strong> {name or 'All'}</p>
            <p><strong>Month:</strong> {month if month else 'All'}</p>
            <p><strong>Year:</strong> {year if year else 'All'}</p>
            <p><strong>Generated:</strong> {datetime.now().strftime('%d %b %Y %H:%M')}</p>
        </div>
        
        <h2>Teacher Attendance</h2>
        <table>
            <thead>
                <tr>
                    <th>Employee ID</th>
                    <th>Name</th>
                    <th>Branch</th>
                    <th>Role</th>
                    <th>Present Days</th>
                    <th>Total Days</th>
                    <th>Percentage</th>
                </tr>
            </thead>
            <tbody>
    """
    
    for item in data:
        teacher = item['teacher']
        percentage = (item['present_days'] / item['total_days'] * 100) if item['total_days'] > 0 else 0
        html_content += f"<tr><td>{teacher.employee_id}</td><td>{teacher.name}</td><td>{teacher.branch}</td><td>{teacher.role}</td><td>{item['present_days']}</td><td>{item['total_days']}</td><td>{percentage:.1f}%</td></tr>"
    
    html_content += """
            </tbody>
        </table>
    </body>
    </html>
    """
    
    response = make_response(html_content)
    response.headers['Content-Type'] = 'text/html'
    return response

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found_error(error):
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page Not Found</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #e53e3e; }
            a { color: #667eea; }
        </style>
    </head>
    <body>
        <h1>404 - Page Not Found</h1>
        <p>The page you are looking for does not exist.</p>
        <a href="/">Go Home</a>
    </body>
    </html>
    """), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Internal Server Error</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #e53e3e; }
            a { color: #667eea; }
        </style>
    </head>
    <body>
        <h1>500 - Internal Server Error</h1>
        <p>Something went wrong on our end. Please try again later.</p>
        <a href="/">Go Home</a>
    </body>
    </html>
    """), 500

# ============================================
# APPLICATION ENTRY POINT
# ============================================

if __name__ == '__main__':
    # Create tables if they don't exist
    with app.app_context():
        try:
            db.create_all()
            print("Database tables created successfully!")
            
            # Create default admin if no admin exists
            admin_exists = User.query.filter_by(role='admin').first()
            if not admin_exists:
                default_admin = User(
                    email='admin@svist.edu.in',
                    password_hash=generate_password_hash('admin123'),
                    role='admin'
                )
                db.session.add(default_admin)
                db.session.commit()
                print("Default admin created: admin@svist.edu.in / admin123")
                
        except Exception as e:
            print(f"Database initialization error: {e}")
    
    # Run the application
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true')