import io
import unittest
from ml_engine.parser import clean_text, extract_skills
from ml_engine.analyzer import calculate_match_score, identify_skill_gap
from ml_engine.classifier import predict_career_domain, calculate_ats_score

class TestMLNLPComponents(unittest.TestCase):
    
    def setUp(self):
        self.sample_resume = """
        John Doe
        Software Engineer
        Email: john.doe@email.com | Phone: 123-456-7890 | LinkedIn: linkedin.com/in/johndoe
        
        EXPERIENCE:
        Software Engineer at Acme Corp (2020 - Present)
        - Built backend APIs using Python, Flask, and PostgreSQL.
        - Deployed microservices on AWS using Docker and Kubernetes.
        - Practiced Agile Scrum development within a team.
        
        EDUCATION:
        B.S. in Computer Science - Tech University (2016 - 2020)
        
        SKILLS:
        Python, Java, JavaScript, HTML, CSS, React, Flask, PostgreSQL, Docker, AWS, Git
        """
        
        self.sample_jd = """
        We are seeking a Backend Engineer with strong proficiency in Python and Flask.
        Experience with PostgreSQL, Docker, and AWS is required.
        Knowledge of Kubernetes, CI/CD, and Redis is a plus.
        Must have good communication and teamwork skills.
        """

    def test_clean_text(self):
        text = "Hello World! Learning Python at 2026."
        cleaned = clean_text(text)
        self.assertIn("learning", cleaned)
        self.assertIn("python", cleaned)
        # Stopwords removed
        self.assertNotIn("at", cleaned.split())

    def test_extract_skills(self):
        skills = extract_skills(self.sample_resume)
        self.assertIn("python", skills)
        self.assertIn("flask", skills)
        self.assertIn("docker", skills)
        self.assertIn("react", skills)
        self.assertIn("git", skills)

    def test_calculate_match_score(self):
        score = calculate_match_score(self.sample_resume, self.sample_jd)
        self.assertTrue(0.0 <= score <= 100.0)
        # Should have a reasonably good score due to overlapping terms
        self.assertGreater(score, 10.0)

    def test_identify_skill_gap(self):
        gap = identify_skill_gap(self.sample_resume, self.sample_jd)
        self.assertIn("python", gap["matched_skills"])
        self.assertIn("flask", gap["matched_skills"])
        # Should find missing skills from JD not in resume (like CI/CD, Redis)
        self.assertIn("redis", gap["missing_skills"])
        self.assertIn("ci/cd", gap["missing_skills"])

    def test_predict_career_domain(self):
        domain = predict_career_domain(self.sample_resume)
        # Should detect Software Engineering or Backend Development
        self.assertIn(domain, ["Software Engineering", "Backend Development"])

    def test_calculate_ats_score(self):
        gap = identify_skill_gap(self.sample_resume, self.sample_jd)
        ats_score = calculate_ats_score(self.sample_resume, gap["matched_skills"], gap["missing_skills"])
        self.assertTrue(0 <= ats_score <= 100)
        # Should be relatively high due to having contact info, experience, education, skills, and good match
        self.assertGreater(ats_score, 60)

if __name__ == '__main__':
    unittest.main()
