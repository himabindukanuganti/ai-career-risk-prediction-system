"""
Enhanced NLP Resume Parser
PyMuPDF + python-docx + regex + spaCy
"""

import re
import io
from pathlib import Path
from typing import List
from dataclasses import dataclass, field

# ---------------------------
# Load NLP model
# ---------------------------
try:
    import spacy
    nlp = spacy.load("en_core_web_lg")
except Exception:
    nlp = None

# ---------------------------
# PDF parser
# ---------------------------
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# ---------------------------
# DOCX parser
# ---------------------------
try:
    import docx as python_docx
except ImportError:
    python_docx = None


# ---------------------------
# Skill taxonomy
# ---------------------------
ONET_SKILL_TAXONOMY = {
    "python": "Programming",
    "java": "Programming",
    "javascript": "Programming",
    "typescript": "Programming",
    "c++": "Programming",
    "sql": "Database",
    "mysql": "Database",
    "postgresql": "Database",
    "mongodb": "Database",

    "excel": "Data Analysis",
    "pandas": "Data Analysis",
    "numpy": "Data Analysis",
    "statistics": "Analytics",
    "power bi": "Data Visualization",
    "tableau": "Data Visualization",
    "matplotlib": "Data Visualization",

    "machine learning": "AI/ML",
    "deep learning": "AI/ML",
    "tensorflow": "AI/ML",
    "pytorch": "AI/ML",
    "scikit-learn": "AI/ML",
    "nlp": "AI/ML",

    "flask": "Backend",
    "django": "Backend",
    "git": "DevOps",
    "docker": "DevOps",
    "kubernetes": "DevOps",

    "aws": "Cloud",
    "azure": "Cloud",

    "agile": "Management",
    "leadership": "Soft Skills"
}


ROLE_BENCHMARKS = {
    "data analyst": [
        "sql", "python", "tableau",
        "excel", "statistics", "power bi"
    ],
    "data engineer": [
        "python", "sql", "spark",
        "kafka", "airflow", "aws", "docker"
    ],
    "software engineer": [
        "python", "java", "sql",
        "git", "docker"
    ]
}


# ---------------------------
# Data models
# ---------------------------
@dataclass
class ExtractedSkill:
    name: str
    category: str
    level: str = "Intermediate"
    score: float = 0.5


@dataclass
class ParsedResume:
    name: str = ""
    email: str = ""
    phone: str = ""
    skills: List[ExtractedSkill] = field(default_factory=list)
    total_years_exp: float = 0.0
    confidence: float = 0.0
    skill_gaps: List[str] = field(default_factory=list)


# ---------------------------
# Text Extraction
# ---------------------------
def extract_text(file_bytes: bytes, filename: str) -> str:
    ext = Path(filename).suffix.lower()

    try:
        if ext == ".pdf" and fitz:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            text = []
            for page in doc:
                text.append(page.get_text("text"))
            return "\n".join(text)

        elif ext in [".docx", ".doc"] and python_docx:
            doc = python_docx.Document(io.BytesIO(file_bytes))
            text = []
            for para in doc.paragraphs:
                if para.text.strip():
                    text.append(para.text)
            return "\n".join(text)

        else:
            return file_bytes.decode("utf-8", errors="ignore")

    except Exception as e:
        print("Text extraction error:", e)
        return ""


# ---------------------------
# Normalize text
# ---------------------------
def normalize_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    return text


# ---------------------------
# Extract skills
# ---------------------------
def extract_skills(text: str) -> List[ExtractedSkill]:
    normalized = normalize_text(text)
    found = []
    seen = set()

    for skill, category in ONET_SKILL_TAXONOMY.items():
        pattern = r'\b' + re.escape(skill) + r'\b'
        if re.search(pattern, normalized):
            if skill not in seen:
                seen.add(skill)
                found.append(
                    ExtractedSkill(
                        name=skill.title(),
                        category=category
                    )
                )
    return found


# ---------------------------
# Email
# ---------------------------
def extract_email(text: str) -> str:
    match = re.search(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
        text
    )
    return match.group(0) if match else ""


# ---------------------------
# Phone
# ---------------------------
def extract_phone(text: str) -> str:
    match = re.search(
        r'(\+91[\-\s]?)?[6-9]\d{9}',
        text
    )
    return match.group(0) if match else ""


# ---------------------------
# Name using spaCy
# ---------------------------
def extract_name(text: str) -> str:
    if not nlp:
        return ""

    doc = nlp(text[:300])
    for ent in doc.ents:
        if ent.label_ == "PERSON":
            return ent.text
    return ""


# ---------------------------
# Experience
# ---------------------------
def extract_experience(text: str) -> float:
    match = re.search(
        r'(\d+)\+?\s+years?\s+(of\s+)?(experience|exp)',
        text,
        re.IGNORECASE
    )
    return float(match.group(1)) if match else 0.0


# ---------------------------
# Skill gaps
# ---------------------------
def compute_skill_gaps(skills, target_role):
    benchmark = ROLE_BENCHMARKS.get(target_role.lower(), [])
    user_skills = {s.name.lower() for s in skills}

    gaps = []
    for skill in benchmark:
        if skill.lower() not in user_skills:
            gaps.append(skill)
    return gaps


# ---------------------------
# Confidence
# ---------------------------
def calculate_confidence(name, email, skills, years):
    score = 0
    if name:
        score += 0.20
    if email:
        score += 0.25
    if len(skills) > 0:
        score += 0.35
    if years > 0:
        score += 0.20

    return round(score, 2)


# ---------------------------
# Main parser
# ---------------------------
def parse_resume(file_bytes: bytes, filename: str, target_role="") -> ParsedResume:
    text = extract_text(file_bytes, filename)

    print("---- EXTRACTED TEXT ----")
    print(text[:1000])

    name = extract_name(text)
    email = extract_email(text)
    phone = extract_phone(text)
    years = extract_experience(text)
    skills = extract_skills(text)

    gaps = []
    if target_role:
        gaps = compute_skill_gaps(skills, target_role)

    confidence = calculate_confidence(
        name,
        email,
        skills,
        years
    )

    return ParsedResume(
        name=name,
        email=email,
        phone=phone,
        skills=skills,
        total_years_exp=years,
        confidence=confidence,
        skill_gaps=gaps
    )


# ---------------------------
# Example test
# ---------------------------
if __name__ == "__main__":
    filename = "resume.pdf"

    with open(filename, "rb") as f:
        file_data = f.read()

    result = parse_resume(
        file_data,
        filename,
        target_role="data analyst"
    )

    print("\n===== PARSED RESULT =====")
    print("Name:", result.name)
    print("Email:", result.email)
    print("Phone:", result.phone)
    print("Experience:", result.total_years_exp)
    print("Confidence:", result.confidence)

    print("\nSkills Found:")
    for skill in result.skills:
        print("-", skill.name, "|", skill.category)

    print("\nMissing Skills:")
    print(result.skill_gaps)