import os
import json
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from config import Config
from database import db, User, Resume, Analysis
from ml_engine import (
    parse_resume_file,
    calculate_match_score,
    identify_skill_gap,
    predict_career_domain,
    calculate_ats_score,
    get_career_recommendations
)

app = Flask(__name__)
app.config.from_object(Config)

# Initialize database
db.init_app(app)

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_user():
    user = None
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
    return dict(current_user=user)

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        confirm_password = request.form.get('confirm_password', '').strip()
        
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return render_template('auth/register.html')
            
        if password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template('auth/register.html')
            
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Username already exists.', 'danger')
            return render_template('auth/register.html')
            
        user = User(username=username)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please log in.', 'success')
        return redirect(url_for('login'))
        
    return render_template('auth/register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password.', 'danger')
            
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user_id = session['user_id']
    recent_analyses = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.created_at.desc()).limit(5).all()
    all_analyses = Analysis.query.filter_by(user_id=user_id).all()
    
    # Calculate stats
    total_analyses = len(all_analyses)
    avg_match_score = round(sum(a.match_score for a in all_analyses) / total_analyses, 1) if total_analyses > 0 else 0
    avg_ats_score = round(sum(a.ats_score for a in all_analyses) / total_analyses, 1) if total_analyses > 0 else 0
    
    # Career domain distribution
    domains = {}
    for a in all_analyses:
        domains[a.domain] = domains.get(a.domain, 0) + 1
        
    # Match score trend over time (last 10)
    trend_analyses = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.created_at.asc()).limit(10).all()
    trend_labels = [a.created_at.strftime('%m/%d %H:%M') for a in trend_analyses]
    trend_scores = [a.match_score for a in trend_analyses]
    trend_ats = [a.ats_score for a in trend_analyses]
    
    return render_template(
        'dashboard.html',
        recent_analyses=recent_analyses,
        total_analyses=total_analyses,
        avg_match_score=avg_match_score,
        avg_ats_score=avg_ats_score,
        domain_distribution=domains,
        trend_labels=trend_labels,
        trend_scores=trend_scores,
        trend_ats=trend_ats
    )

@app.route('/analyze', methods=['GET', 'POST'])
@login_required
def analyze():
    user_id = session['user_id']
    
    # Fetch existing resumes for quick selections
    existing_resumes = Resume.query.filter_by(user_id=user_id).order_by(Resume.uploaded_at.desc()).all()
    
    if request.method == 'POST':
        job_title = request.form.get('job_title', '').strip()
        job_desc = request.form.get('job_description', '').strip()
        resume_source = request.form.get('resume_source', 'upload')  # 'upload' or 'existing'
        
        if not job_title or not job_desc:
            flash('Job title and job description are required.', 'danger')
            return render_template('analyze.html', existing_resumes=existing_resumes)
            
        resume_text = ""
        filename = ""
        resume_obj = None
        
        if resume_source == 'existing':
            resume_id = request.form.get('existing_resume_id')
            if resume_id:
                resume_obj = db.session.get(Resume, resume_id)
                if resume_obj and resume_obj.user_id == user_id:
                    resume_text = resume_obj.file_content_text
                    filename = resume_obj.filename
                else:
                    flash('Invalid resume selected.', 'danger')
                    return render_template('analyze.html', existing_resumes=existing_resumes)
            else:
                flash('Please select an existing resume.', 'danger')
                return render_template('analyze.html', existing_resumes=existing_resumes)
        else:
            # File Upload Source
            if 'resume_file' not in request.files:
                flash('No file part uploaded.', 'danger')
                return render_template('analyze.html', existing_resumes=existing_resumes)
                
            file = request.files['resume_file']
            if file.filename == '':
                flash('No file selected.', 'danger')
                return render_template('analyze.html', existing_resumes=existing_resumes)
                
            if file and allowed_file(file.filename):
                filename = file.filename
                # Read stream without saving local file first, to parse
                file_bytes = file.read()
                file_stream = io.BytesIO(file_bytes)
                
                # Parse
                resume_text = parse_resume_file(file_stream, filename)
                if not resume_text:
                    flash('Failed to extract text from resume. Ensure it is a readable PDF or DOCX file.', 'danger')
                    return render_template('analyze.html', existing_resumes=existing_resumes)
                
                # Save to database
                resume_obj = Resume(
                    user_id=user_id,
                    filename=filename,
                    file_content_text=resume_text
                )
                db.session.add(resume_obj)
                db.session.commit()
            else:
                flash('Invalid file extension. Only PDF and DOCX are allowed.', 'danger')
                return render_template('analyze.html', existing_resumes=existing_resumes)
                
        # Perform Skill Gap & Machine Learning analysis
        match_score = calculate_match_score(resume_text, job_desc)
        gap_results = identify_skill_gap(resume_text, job_desc)
        predicted_domain = predict_career_domain(resume_text)
        ats_score = calculate_ats_score(resume_text, gap_results['matched_skills'], gap_results['missing_skills'])
        
        # Save analysis
        analysis = Analysis(
            user_id=user_id,
            resume_id=resume_obj.id,
            job_title=job_title,
            job_description=job_desc,
            match_score=match_score,
            domain=predicted_domain,
            matched_skills=json.dumps(gap_results['matched_skills']),
            missing_skills=json.dumps(gap_results['missing_skills']),
            ats_score=ats_score
        )
        db.session.add(analysis)
        db.session.commit()
        
        flash('Analysis completed successfully!', 'success')
        return redirect(url_for('results', analysis_id=analysis.id))
        
    return render_template('analyze.html', existing_resumes=existing_resumes)

import io

@app.route('/results/<int:analysis_id>')
@login_required
def results(analysis_id):
    user_id = session['user_id']
    analysis = db.session.get(Analysis, analysis_id)
    
    if not analysis or analysis.user_id != user_id:
        flash('Analysis not found.', 'danger')
        return redirect(url_for('dashboard'))
        
    matched_skills = json.loads(analysis.matched_skills)
    missing_skills = json.loads(analysis.missing_skills)
    
    # Skill gap calculations
    gap_data = identify_skill_gap(analysis.resume.file_content_text, analysis.job_description)
    recommended_skills = gap_data['recommended_skills']
    
    # Career recommendations
    recommendations = get_career_recommendations(analysis.domain)
    
    # Calculate categories scores for Chart.js
    # (Checking which categories the matched skills belong to)
    from ml_engine.skills_data import SKILLS_DICT
    category_scores = {}
    for cat, cat_skills in SKILLS_DICT.items():
        matched_cat = [s for s in matched_skills if s in cat_skills]
        total_cat = [s for s in (matched_skills + missing_skills) if s in cat_skills]
        if total_cat:
            category_scores[cat] = {
                "matched": len(matched_cat),
                "total": len(total_cat),
                "ratio": round((len(matched_cat) / len(total_cat)) * 100, 1)
            }
            
    return render_template(
        'results.html',
        analysis=analysis,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
        recommended_skills=recommended_skills,
        recommendations=recommendations,
        category_scores=category_scores
    )

@app.route('/compare', methods=['GET', 'POST'])
@login_required
def compare():
    user_id = session['user_id']
    resumes = Resume.query.filter_by(user_id=user_id).order_by(Resume.uploaded_at.desc()).all()
    
    if request.method == 'POST':
        resume1_id = request.form.get('resume1_id')
        resume2_id = request.form.get('resume2_id')
        job_desc = request.form.get('job_description', '').strip()
        
        if not resume1_id or not resume2_id or not job_desc:
            flash('Two resumes and a job description are required for comparison.', 'danger')
            return render_template('compare.html', resumes=resumes)
            
        r1 = db.session.get(Resume, resume1_id)
        r2 = db.session.get(Resume, resume2_id)
        
        if not r1 or not r2 or r1.user_id != user_id or r2.user_id != user_id:
            flash('Invalid resumes selected.', 'danger')
            return render_template('compare.html', resumes=resumes)
            
        # Analyze resume 1
        score1 = calculate_match_score(r1.file_content_text, job_desc)
        gap1 = identify_skill_gap(r1.file_content_text, job_desc)
        ats1 = calculate_ats_score(r1.file_content_text, gap1['matched_skills'], gap1['missing_skills'])
        domain1 = predict_career_domain(r1.file_content_text)
        
        # Analyze resume 2
        score2 = calculate_match_score(r2.file_content_text, job_desc)
        gap2 = identify_skill_gap(r2.file_content_text, job_desc)
        ats2 = calculate_ats_score(r2.file_content_text, gap2['matched_skills'], gap2['missing_skills'])
        domain2 = predict_career_domain(r2.file_content_text)
        
        comparison = {
            "resume1": {
                "filename": r1.filename,
                "score": score1,
                "ats": ats1,
                "domain": domain1,
                "matched": gap1['matched_skills'],
                "missing": gap1['missing_skills']
            },
            "resume2": {
                "filename": r2.filename,
                "score": score2,
                "ats": ats2,
                "domain": domain2,
                "matched": gap2['matched_skills'],
                "missing": gap2['missing_skills']
            }
        }
        
        return render_template('compare.html', resumes=resumes, comparison=comparison, job_desc=job_desc)
        
    return render_template('compare.html', resumes=resumes)

@app.route('/history')
@login_required
def history():
    user_id = session['user_id']
    analyses = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.created_at.desc()).all()
    return render_template('history.html', analyses=analyses)

@app.route('/delete_analysis/<int:analysis_id>', methods=['POST'])
@login_required
def delete_analysis(analysis_id):
    user_id = session['user_id']
    analysis = db.session.get(Analysis, analysis_id)
    
    if analysis and analysis.user_id == user_id:
        db.session.delete(analysis)
        db.session.commit()
        flash('Analysis deleted successfully.', 'success')
    else:
        flash('Analysis not found.', 'danger')
        
    return redirect(url_for('history'))

# Run database creation inside context
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
