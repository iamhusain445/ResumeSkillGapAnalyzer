import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'premium-resume-key-12345'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///resume_analyzer.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'uploads')
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024  # 5 MB limit
    ALLOWED_EXTENSIONS = {'pdf', 'docx'}
