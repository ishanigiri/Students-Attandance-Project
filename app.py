from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import pandas as pd
import io
import smtplib
from email.message import EmailMessage
import secrets
import json
import os
from sqlalchemy import func, and_

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.permanent_session_lifetime = timedelta(days=5)

db = SQLAlchemy(app)

# Models
class Teacher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    students = db.relationship('Student', backref='teacher', lazy=True)

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    roll_number = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('teacher.id'), nullable=False)
    attendances = db.relationship('Attendance', backref='student', lazy=True)
    
    def attendance_percentage(self):
        total_records = Attendance.query.filter_by(student_id=self.id).count()
        if total_records == 0:
            return 0
        present_records = Attendance.query.filter_by(student_id=self.id, status='Present').count()
        return round((present_records / total_records) * 100, 2)

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    status = db.Column(db.String(10), nullable=False)  # Present, Absent, Late
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    remark = db.Column(db.String(200))

# Create database tables
with app.app_context():
    db.create_all()

# Routes
@app.route('/')
def index():
    if 'teacher_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        teacher = Teacher.query.filter_by(email=email).first()
        
        if teacher and check_password_hash(teacher.password, password):
            session.permanent = True
            session['teacher_id'] = teacher.id
            session['teacher_name'] = teacher.name
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        existing_teacher = Teacher.query.filter_by(email=email).first()
        if existing_teacher:
            flash('Email already registered', 'danger')
            return redirect(url_for('register'))
        
        hashed_password = generate_password_hash(password)
        new_teacher = Teacher(name=name, email=email, password=hashed_password)
        
        db.session.add(new_teacher)
        db.session.commit()
        
        flash('Registration successful! Please login.', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/dashboard')
def dashboard():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    teacher_id = session['teacher_id']
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    
    # Get recent attendance data
    today = datetime.utcnow().date()
    week_ago = today - timedelta(days=7)
    
    # Calculate daily attendance stats for the past week
    daily_stats = []
    for i in range(7):
        date = today - timedelta(days=i)
        total = Attendance.query.join(Student).filter(
            Student.teacher_id == teacher_id,
            Attendance.date == date
        ).count()
        
        present = Attendance.query.join(Student).filter(
            Student.teacher_id == teacher_id,
            Attendance.date == date,
            Attendance.status == 'Present'
        ).count()
        
        absent = Attendance.query.join(Student).filter(
            Student.teacher_id == teacher_id,
            Attendance.date == date,
            Attendance.status == 'Absent'
        ).count()
        
        late = Attendance.query.join(Student).filter(
            Student.teacher_id == teacher_id,
            Attendance.date == date,
            Attendance.status == 'Late'
        ).count()
        
        if total > 0:
            present_percent = round((present / total) * 100, 2)
        else:
            present_percent = 0
            
        daily_stats.append({
            'date': date.strftime('%Y-%m-%d'),
            'total': total,
            'present': present,
            'absent': absent,
            'late': late,
            'present_percent': present_percent
        })
    
    # Get students with low attendance (below 75%)
    low_attendance_students = []
    for student in students:
        percentage = student.attendance_percentage()
        if percentage < 75:
            low_attendance_students.append({
                'id': student.id,
                'name': student.name,
                'percentage': percentage
            })
    
    return render_template('dashboard.html', 
                          students=students, 
                          daily_stats=daily_stats, 
                          low_attendance=low_attendance_students)

@app.route('/logout')
def logout():
    session.pop('teacher_id', None)
    session.pop('teacher_name', None)
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/students')
def students():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    teacher_id = session['teacher_id']
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    
    return render_template('students.html', students=students)

@app.route('/add_student', methods=['GET', 'POST'])
def add_student():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        name = request.form['name']
        roll_number = request.form['roll_number']
        email = request.form['email']
        
        new_student = Student(
            name=name,
            roll_number=roll_number,
            email=email,
            teacher_id=session['teacher_id']
        )
        
        db.session.add(new_student)
        db.session.commit()
        
        flash('Student added successfully!', 'success')
        return redirect(url_for('students'))
    
    return render_template('add_student.html')

@app.route('/edit_student/<int:id>', methods=['GET', 'POST'])
def edit_student(id):
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    student = Student.query.get_or_404(id)
    
    # Check if the student belongs to the logged in teacher
    if student.teacher_id != session['teacher_id']:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('students'))
    
    if request.method == 'POST':
        student.name = request.form['name']
        student.roll_number = request.form['roll_number']
        student.email = request.form['email']
        
        db.session.commit()
        
        flash('Student updated successfully!', 'success')
        return redirect(url_for('students'))
    
    return render_template('edit_student.html', student=student)

@app.route('/delete_student/<int:id>')
def delete_student(id):
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    student = Student.query.get_or_404(id)
    
    # Check if the student belongs to the logged in teacher
    if student.teacher_id != session['teacher_id']:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('students'))
    
    # Delete associated attendance records first
    Attendance.query.filter_by(student_id=id).delete()
    
    db.session.delete(student)
    db.session.commit()
    
    flash('Student deleted successfully!', 'success')
    return redirect(url_for('students'))

@app.route('/attendance')
def attendance():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    teacher_id = session['teacher_id']
    date_str = request.args.get('date')
    
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        except ValueError:
            selected_date = datetime.utcnow().date()
    else:
        selected_date = datetime.utcnow().date()
    
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    
    # Get existing attendance records for the selected date
    attendance_records = {}
    existing_records = Attendance.query.filter_by(date=selected_date).all()
    for record in existing_records:
        attendance_records[record.student_id] = {
            'status': record.status,
            'remark': record.remark
        }
    
    return render_template('attendance.html', 
                          students=students, 
                          selected_date=selected_date,
                          attendance_records=attendance_records)

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    date_str = request.form['date']
    selected_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    teacher_id = session['teacher_id']
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    
    for student in students:
        status_key = f'status_{student.id}'
        remark_key = f'remark_{student.id}'
        
        if status_key in request.form:
            status = request.form[status_key]
            remark = request.form.get(remark_key, '')
            
            # Check if attendance record already exists for this student and date
            existing_record = Attendance.query.filter_by(
                student_id=student.id,
                date=selected_date
            ).first()
            
            if existing_record:
                # Update existing record
                existing_record.status = status
                existing_record.remark = remark
            else:
                # Create new record
                new_record = Attendance(
                    student_id=student.id,
                    date=selected_date,
                    status=status,
                    remark=remark
                )
                db.session.add(new_record)
    
    db.session.commit()
    flash('Attendance marked successfully!', 'success')
    
    # Check for low attendance and send email alerts
    check_and_send_alerts()
    
    return redirect(url_for('attendance', date=date_str))

@app.route('/student_report/<int:id>')
def student_report(id):
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    student = Student.query.get_or_404(id)
    
    # Check if the student belongs to the logged in teacher
    if student.teacher_id != session['teacher_id']:
        flash('Unauthorized access', 'danger')
        return redirect(url_for('students'))
    
    # Get all attendance records for this student
    attendance_records = Attendance.query.filter_by(student_id=id).order_by(Attendance.date.desc()).all()
    
    # Calculate attendance statistics
    total_records = len(attendance_records)
    present_count = sum(1 for record in attendance_records if record.status == 'Present')
    absent_count = sum(1 for record in attendance_records if record.status == 'Absent')
    late_count = sum(1 for record in attendance_records if record.status == 'Late')
    
    attendance_percentage = 0
    if total_records > 0:
        attendance_percentage = round((present_count / total_records) * 100, 2)
    
    # Monthly attendance data for charts
    monthly_data = {}
    for record in attendance_records:
        month = record.date.strftime('%Y-%m')
        if month not in monthly_data:
            monthly_data[month] = {'total': 0, 'present': 0, 'absent': 0, 'late': 0}
        
        monthly_data[month]['total'] += 1
        if record.status == 'Present':
            monthly_data[month]['present'] += 1
        elif record.status == 'Absent':
            monthly_data[month]['absent'] += 1
        elif record.status == 'Late':
            monthly_data[month]['late'] += 1
    
    # Calculate monthly percentages
    chart_data = []
    for month, data in monthly_data.items():
        if data['total'] > 0:
            present_percent = round((data['present'] / data['total']) * 100, 2)
            absent_percent = round((data['absent'] / data['total']) * 100, 2)
            late_percent = round((data['late'] / data['total']) * 100, 2)
            
            chart_data.append({
                'month': month,
                'present_percent': present_percent,
                'absent_percent': absent_percent,
                'late_percent': late_percent
            })
    
    return render_template('student_report.html', 
                          student=student, 
                          records=attendance_records,
                          total_records=total_records,
                          present_count=present_count,
                          absent_count=absent_count,
                          late_count=late_count,
                          attendance_percentage=attendance_percentage,
                          chart_data=json.dumps(chart_data))

@app.route('/api/attendance')
def api_attendance():
    if 'teacher_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    teacher_id = session['teacher_id']
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else None
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else None
    except ValueError:
        return jsonify({'error': 'Invalid date format. Use YYYY-MM-DD'}), 400
    
    # Query for attendance data
    query = Attendance.query.join(Student).filter(Student.teacher_id == teacher_id)
    
    if start_date:
        query = query.filter(Attendance.date >= start_date)
    if end_date:
        query = query.filter(Attendance.date <= end_date)
    
    records = query.all()
    
    # Format attendance data
    attendance_data = []
    for record in records:
        student = Student.query.get(record.student_id)
        attendance_data.append({
            'id': record.id,
            'date': record.date.strftime('%Y-%m-%d'),
            'student_id': record.student_id,
            'student_name': student.name,
            'roll_number': student.roll_number,
            'status': record.status,
            'remark': record.remark
        })
    
    return jsonify(attendance_data)

@app.route('/export_attendance')
def export_attendance():
    if 'teacher_id' not in session:
        flash('Please login first', 'danger')
        return redirect(url_for('login'))
    
    teacher_id = session['teacher_id']
    format_type = request.args.get('format', 'csv')
    
    # Get all students
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    
    # Create DataFrame
    data = []
    for student in students:
        attendance_records = Attendance.query.filter_by(student_id=student.id).all()
        total_records = len(attendance_records)
        present_count = sum(1 for record in attendance_records if record.status == 'Present')
        absent_count = sum(1 for record in attendance_records if record.status == 'Absent')
        late_count = sum(1 for record in attendance_records if record.status == 'Late')
        
        attendance_percentage = 0
        if total_records > 0:
            attendance_percentage = round((present_count / total_records) * 100, 2)
        
        data.append({
            'Student Name': student.name,
            'Roll Number': student.roll_number,
            'Email': student.email,
            'Total Days': total_records,
            'Present': present_count,
            'Absent': absent_count,
            'Late': late_count,
            'Attendance %': attendance_percentage
        })
    
    df = pd.DataFrame(data)
    
    if format_type == 'csv':
        output = io.BytesIO()
        df.to_csv(output, index=False)
        output.seek(0)
        
        return send_file(
            output,
            mimetype='text/csv',
            download_name='attendance_report.csv',
            as_attachment=True
        )
    else:
        # If PDF requested but we're using a simple example without PDF generation
        flash('PDF export is not available in this demo', 'warning')
        return redirect(url_for('dashboard'))

def check_and_send_alerts():
    """Check for students with low attendance and send alerts"""
    teacher_id = session.get('teacher_id')
    if not teacher_id:
        return
    
    threshold = 75  # Alert for attendance below 75%
    teacher = Teacher.query.get(teacher_id)
    low_attendance_students = []
    
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    for student in students:
        percentage = student.attendance_percentage()
        if percentage < threshold:
            low_attendance_students.append({
                'name': student.name,
                'email': student.email,
                'percentage': percentage
            })
    
    # For demo purposes, we'll just print the alert info
    # In a real app, this would send actual emails
    if low_attendance_students:
        print(f"Alert: {len(low_attendance_students)} students have attendance below {threshold}%")
        for student in low_attendance_students:
            print(f"Student: {student['name']}, Email: {student['email']}, Attendance: {student['percentage']}%")
    
    # Uncomment and configure the email sending in a real app
    # send_attendance_alerts(teacher.email, low_attendance_students)

def send_attendance_alerts(teacher_email, students):
    """Send email alerts for low attendance students
    In a real app, configure your email settings here
    """
    # This is a placeholder for email sending functionality
    pass

if __name__ == '__main__':
    app.run(debug=True)