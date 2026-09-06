# CloudBox - Mini Cloud Storage Backend & Frontend

A production-grade, fully asynchronous cloud storage backend (Dropbox/Google Drive architecture) built with **FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL (`asyncpg`)**, **AWS S3 (`aioboto3`)**, and **AWS SQS / Lambda**, accompanied by a clean, modern responsive frontend dashboard.

---

## 🏛️ System Architecture

```
                                  +-------------------------------------------------------+
                                  |                     Client Browser                    |
                                  |  - Single Page Application (Dashboard & Share Viewer) |
                                  |  - Computes SHA-256 & Uploads directly to S3          |
                                  +---------------------------+---------------------------+
                                                              |
                                            1. Request Ticket | 3. Direct Upload (PUT) /
                                            & Metadata API    |    Download (GET)
                                                              v
+-----------------------+              +--------------------------------+               +-----------------------+
|    AWS API Gateway    | <----------> |     AWS S3 Storage Bucket      | <-----------> |   SQS Worker Lambda   |
| (HTTP API Entrypoint) |              |  - Raw Content Blobs           |               | - Thumbnail Generator |
+-----------+-----------+              |  - Image Thumbnails            |               | - Hash/Scan Validator |
            |                          +--------------------------------+               +-----------+-----------+
            |                                         ^                                             ^
            v                                         | aioboto3                                    |
+-----------------------+                             |                                             | SQS Trigger
| FastAPI Lambda (App)  | ----------------------------+                                             |
|  - Auth & JWT         |
|  - Folders Hierarchy  | ----------------------------------+                                       |
|  - Versioning & Quota |                                   | SQS Enqueue                           |
|  - Share Token Engine | ------------------------------+   v                                       |
+-----------+-----------+                               | +-------------------+                     |
            |                                           +-> Background Queue  +---------------------+
            v (Pooled Connection)                         | (AWS SQS / Tasks) |
+-----------------------+                                 +-------------------+
|     AWS RDS Proxy     |
+-----------+-----------+
            |
            v
+-----------------------+
|  PostgreSQL Database  |
|  - Users & Quotas     |
|  - Folders Tree       |
|  - Files & Versions   |
|  - ContentBlobs (Dedupe)|
|  - SharedLinks        |
+-----------------------+
```

---

## 🚀 Key Features & Engineering Highlights

1. **Direct-to-S3 Presigned Uploads (Bypassing Lambda 6MB Ceiling)**:
   - File bytes stream directly from the client to AWS S3 using presigned PUT URLs, completely bypassing the 6MB API Gateway and Lambda payload limits.
   - Fallback direct multipart upload endpoint is available for small files and local testing.
2. **Hash-based Content Deduplication**:
   - Files are indexed using SHA-256 digests in a `ContentBlob` table. If multiple users upload identical content or make duplicate copies, S3 stores only a single copy with reference counting (`ref_count`).
3. **Self-Referential Hierarchical Folders**:
   - Recursive folder tree structure with materialized path indexing, circular reference prevention, breadcrumbs generation, and cascading operations.
4. **Storage Quotas per User**:
   - Real-time tracking of used storage bytes versus allocated quota with automated upload rejection (HTTP 413) upon exceeding limits.
5. **Public & Private Share Links**:
   - Secure URL-safe token generation for sharing files or folders with customizable permissions (`view` / `download`) and configurable TTL expiration.
6. **Decoupled SQS Background Worker Pipeline**:
   - Asynchronous worker Lambda consumes events from AWS SQS to perform image thumbnail generation (using Pillow) and virus-scan/integrity verification.
7. **Serverless & RDS Proxy Ready**:
   - Mangum ASGI adapter handles API Gateway routing. SQLAlchemy async engine is configured with connection recycling and `NullPool` option for AWS RDS Proxy.
8. **Modern Single Page Application**:
   - Responsive UI featuring JWT authentication, visual quota meter, folder tree navigation, live upload progress bar, and public share preview.

---

## 🛠️ Tech Stack

- **Web Framework**: FastAPI 0.111+ (Python 3.11)
- **Database**: PostgreSQL with async SQLAlchemy 2.0 and `asyncpg` driver
- **Object Storage**: AWS S3 with `aioboto3`
- **Background Tasks**: AWS SQS + Worker Lambda
- **Authentication**: JWT (`python-jose`) + `passlib[bcrypt]`
- **Serverless Adapter**: `mangum`
- **Database Migrations**: `alembic`
- **Image Processing**: `Pillow`
- **Testing**: `pytest`, `pytest-asyncio`, `httpx`, `aiosqlite`
- **Frontend**: Vanilla JS (ES6+), Modern Responsive CSS

---

## 📂 Project Directory Layout

```
cloud-storage-backend/
├── app/
│   ├── api/
│   │   ├── deps.py                  # FastAPI dependency injection (DB, Auth, Storage, SQS)
│   │   └── v1/
│   │       ├── api.py               # Aggregates v1 routes
│   │       └── endpoints/
│   │           ├── auth.py          # /signup, /login, /me, /quota
│   │           ├── files.py         # /upload-url, /complete-upload, /download, lifecycle
│   │           ├── folders.py       # /tree, /breadcrumbs, CRUD
│   │           ├── shares.py        # /shares, /shares/public/{token}
│   │           └── health.py        # /health probe
│   ├── core/
│   │   ├── config.py                # Pydantic BaseSettings
│   │   ├── security.py              # Password hashing & JWT token operations
│   │   ├── exceptions.py            # Granular domain exceptions (NotFoundError, QuotaExceededError, etc.)
│   │   └── logging.py               # Structured log formatting
│   ├── db/
│   │   ├── base.py                  # Declarative Base
│   │   └── session.py               # Async engine and session factory
│   ├── models/                      # SQLAlchemy 2.0 ORM Models
│   │   ├── user.py                  # User entity & quota
│   │   ├── folder.py                # Self-referential Folder tree
│   │   ├── file.py                  # File entity
│   │   ├── blob.py                  # ContentBlob for deduplication
│   │   └── share.py                 # SharedLink tokens
│   ├── schemas/                     # Pydantic v2 schemas
│   ├── services/                    # Business logic layer (Auth, Files, Folders, Shares, SQS)
│   ├── storage/                     # Storage abstraction layer (Base, S3 aioboto3, Local)
│   ├── worker/                      # AWS SQS Worker Lambda & Tasks
│   └── main.py                      # FastAPI app initialization, CORS, exceptions, Mangum handler
├── static/                          # Modern Frontend Single Page App
│   ├── index.html                   # HTML dashboard
│   ├── app.js                       # Frontend client logic
│   └── style.css                    # Modern CSS styling
├── tests/                           # Complete pytest async test suite
├── alembic/                         # Database migrations
├── docker-compose.yml               # Local PostgreSQL + LocalStack
├── Dockerfile                       # App container definition
├── template.yaml                    # AWS SAM Serverless deployment template
├── requirements.txt                 # Production dependencies
├── requirements-dev.txt             # Development & testing dependencies
└── .env.example                     # Environment variables template
```

---

## ⚡ Quickstart Guide (Local Development)

### 1. Prerequisites
- Python 3.11+
- Virtual environment tool (`venv` or `conda`)
- Optional: Docker & Docker Compose

### 2. Environment Setup
```bash
# Clone or enter directory
cd cloud-storage-backend

# Create and activate virtualenv
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Create .env file
cp .env.example .env
```

### 3. Run with Local Storage & In-Memory/Local Database
By default, you can run the application with local storage emulation (no AWS account required):
```bash
# Start the FastAPI server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Open Dashboard in Browser: **http://localhost:8000**
- Interactive Swagger API Docs: **http://localhost:8000/api/v1/docs**

---

## 🐳 Running with Docker & LocalStack

To emulate the full AWS environment locally (PostgreSQL + LocalStack S3 + LocalStack SQS):

```bash
docker-compose up --build
```
This boots:
1. PostgreSQL on port `5432`
2. LocalStack (S3 + SQS) on port `4566`
3. CloudBox API Server on port `8000`

---

## 🧪 Running Automated Tests

Run the complete async test suite with Pytest:

```bash
pytest -v
```

To run with test coverage reporting:
```bash
pytest --cov=app tests/
```

---

## ☁️ Deploying to AWS Serverless (SAM / Lambda / RDS Proxy)

### Architecture on AWS:
- **FastAPI Lambda Function**: Runs behind HTTP API Gateway using `Mangum`.
- **Worker Lambda Function**: Attached to SQS queue with batch processing and partial failure reporting.
- **S3 Bucket**: Stores raw content blobs with CORS configured for presigned direct uploads.
- **RDS PostgreSQL & RDS Proxy**: Connection pooling across concurrent Lambda invocations.

### Build and Deploy using AWS SAM:
```bash
# Build the application artifacts
sam build

# Deploy to AWS
sam deploy --guided \
  --parameter-overrides \
    DatabaseUrl="postgresql+asyncpg://user:pass@your-rds-proxy-endpoint:5432/cloudstorage" \
    JwtSecretKey="your-strong-production-jwt-secret-key"
```

---

## 🔒 Security Best Practices
- Passwords hashed with `bcrypt` (12 rounds).
- JWT tokens signed with HMAC-SHA256 and expiration.
- User data isolated via foreign key constraints and per-request authenticated owner checks.
- S3 access controlled via time-limited presigned URLs with scoped permissions.
- Public shares use cryptographically secure URL-safe tokens with optional expiration dates.

