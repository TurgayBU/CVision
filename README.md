# CVision

CVision is a **Flask** web application that lets users upload their CVs for AI-powered analysis, automatically extract and match job postings against those CVs, and run interview simulations based on those matches. The analysis and recommendation engine runs on the **Groq API** (llama-3.3-70b-versatile).

## Features

- **User accounts**: Registration, login, logout, password reset; session-based authentication.
- **CV upload and parsing**: Text extraction from PDF/DOC/DOCX files, with OCR support for scanned documents.
- **AI-powered CV analysis**: Automatic extraction of skills, experience, education, languages, and address, saved to the database.
- **Job posting analysis**: Fetches content from a listing URL and uses AI to extract position, company, required/preferred skills, and more.
- **Job recommendations**: Scores the CV against stored job listings and uses a min-heap to surface the top 3 matches.
- **Interview simulator**: AI generates interview questions from the job listing + CV data, evaluates the user's answers, and saves sessions.
- **Dashboard and settings**: Profile updates, password changes, and CV/account deletion.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, Flask, Flask-CORS |
| Database | MySQL (`mysql-connector-python`) |
| AI | Groq API (`llama-3.3-70b-versatile`) |
| CV Parsing | PyPDF2, python-docx, pytesseract (OCR), pdf2image |
| Web Scraping | requests, BeautifulSoup4 |
| Frontend | Jinja2 templates (HTML/CSS/JS) |

## Project Structure

```
CVision/
├── main.py                  # Flask app and main routes (auth, dashboard, CV, settings)
├── config.py                # Database and application configuration
├── extract_cv.py            # Text extraction from CV files (PDF/DOCX/OCR)
├── cv_ai_extract.py         # CV analysis logic via Groq AI
├── job_analyzer.py          # Fetches and analyzes job posting pages with AI
├── job_recommendation.py    # Min-heap based job recommendation algorithm
├── job_routes.py            # Job-related API routes (Blueprint)
├── interview_engine.py      # Interview question generation and answer evaluation
├── interview_routes.py      # Interview API routes (Blueprint)
├── templates/                # Jinja2 HTML templates
│   ├── index.html                # Login page
│   ├── dashboard_main.html       # Dashboard
│   ├── cv_and_link_upload.html   # CV upload
│   ├── cv_analysis.html          # CV analysis results
│   ├── job_extractor.html        # Job posting extraction
│   ├── job_detail.html           # Job posting / match detail report
│   └── interview.html            # Interview simulator UI
└── requirements.txt           # Python dependencies
```

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/TurgayBU/CVision.git
cd CVision
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Set up the database

Create a MySQL database named `cvision`, then create the tables below (add the schema as a `.sql` file in the repo, e.g. `database/schema.sql`, and import it with `mysql -u root -p cvision < database/schema.sql`):

| Table | Purpose |
|---|---|
| `users` | User accounts (username, email, hashed password, name/surname) |
| `cv_text` | Raw text extracted from uploaded CVs |
| `cv_analyses` | AI-extracted CV analysis results (address, skills, experience, education, languages) |
| `job_analyses` | AI-extracted job posting analysis results (title, company, skills, salary, etc.) |
| `saved_jobs` | Job postings saved by the user (raw text/URL) |
| `question_categories` | Interview question categories |
| `questions` | Interview question bank |
| `user_answers` | User answers to interview questions |
| `feedback` | AI feedback on an answer (score, strengths, improvements) |
| `is_answered` | Tracks whether a user has answered a given question |

> `users` must be created first — `cv_text`, `cv_analyses`, `saved_jobs`, and `is_answered`/`user_answers` all reference it with a foreign key (several with `ON DELETE CASCADE`). `question_categories` must exist before `questions`, and `questions`/`user_answers` before `is_answered`/`feedback`.

### 4. Configuration

Update the `DB_CONFIG` (host, username, password) and `api_key` (Groq API key) fields in `config.py` with your own values.

> ⚠️ **Security note**: The database password and Groq API key are currently hardcoded directly into `config.py`, and the repo also has a committed `.env` file with populated values. Moving these to environment variables and adding `.env` to `.gitignore` would prevent sensitive credentials from being exposed in the public repo.

### 5. Run the app

```bash
python main.py
```

By default the app runs at `http://localhost:5000` (the port can be changed via the `PORT` variable in `config.py`).

## API Endpoints (summary)

| Area | Endpoints |
|---|---|
| Auth | `/api/login`, `/api/register`, `/api/logout`, `/api/forgot-password`, `/api/check-session` |
| CV | `/upload`, `/api/upload-cv-links`, `/analyze-cv`, `/save-cv-analysis`, `/api/user-cvs`, `/api/cv-details/<id>`, `/api/cv-stats` |
| Job postings | `/api/analyze-job`, `/api/user-jobs`, `/api/job-detail/<id>` (GET/PATCH), `/api/job-recommendations` |
| Interview | `/api/interview/start`, `/api/interview/answer`, `/api/interview/finalize`, `/api/interview/session/<id>`, `/api/interview/sessions` |
| Settings | `/api/settings/profile`, `/api/settings/password`, `/api/settings/delete-cvs`, `/api/settings/delete-account` |

## Developers

1. [TurgayBU](https://github.com/TurgayBU)
2. [BeratErmis](https://github.com/BeratErmis)
