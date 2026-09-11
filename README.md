# CloudBox - Enterprise Cloud Storage Platform ☁️

[![Tests](https://img.shields.io/badge/Tests-76%2F76%20Passing-brightgreen?style=flat-square)](https://github.com/vanshmadaan/cloudbox)
[![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![AWS Serverless](https://img.shields.io/badge/AWS-Lambda%20%7C%20S3%20%7C%20SQS%20%7C%20SES-FF9900?style=flat-square&logo=amazon-aws)](https://aws.amazon.com/)
[![License](https://img.shields.io/badge/License-MIT-purple?style=flat-square)](LICENSE)

A production-grade, distributed, fully asynchronous cloud storage platform (Dropbox / Google Drive architecture) built with **FastAPI**, **SQLAlchemy 2.0 (async)**, **PostgreSQL (`asyncpg`)**, **AWS S3 (`aioboto3`)**, **AWS SQS / SES**, and **AWS Lambda / API Gateway**, powered by a custom **distributed rate-limiting engine** and a sleek, responsive Single Page Application.

---

## 🌐 Live Production Deployment

* **Live Web App**: [https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com](https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com)
* **Interactive API Documentation (Swagger UI)**: [https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com/docs](https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com/docs)
* **System Health Probe**: [https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com/api/v1/health](https://4mudvzo4nb.execute-api.us-east-1.amazonaws.com/api/v1/health)

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
|  - Rate Limiter       |
|  - Auth & JWT         | ----------------------------------+                                       |
|  - Password Reset OTP |                                   | SQS Enqueue                           |
|  - Folders Hierarchy  | ------------------------------+   v                                       |
|  - Versioning & Quota |                               | +-------------------+                     |
|  - Share Token Engine |                               +-> Background Queue  +---------------------+
+-----------+-----------+                                 | (AWS SQS / Tasks) |
            |                                             +-------------------+
            v (Pooled Connection)
+-----------------------+              +--------------------------------+
|     AWS RDS Proxy     |              |     Amazon SES (Email OTP)     |
+-----------+-----------+              |  - 6-digit password reset OTP  |
            |                          +--------------------------------+
            v
+-----------------------+              +--------------------------------+
|  PostgreSQL Database  |              | Distributed Redis / Memory     |
|  - Users & Quotas     |              |  - Atomic Lua Token Bucket     |
|  - Folders Tree       |              |  - In-Memory Circuit Breaker   |
|  - Files & Versions   |              +--------------------------------+
|  - ContentBlobs (Dedupe)
|  - SharedLinks        |
|  - PasswordResetOtps  |
+-----------------------+
```

---

## 🚀 Key Features & Engineering Highlights

### 1. Distributed Rate Limiter (`ratelimit-core`)
- **Dual-Backend Architecture**:
  - **Production (`RedisStorageBackend`)**: Atomic token bucket replenishment via pre-compiled Redis Lua scripts across distributed AWS Lambda instances with an in-memory circuit breaker.
  - **Local Development (`MemoryStorageBackend`)**: Thread-safe, asyncio-safe in-memory backend with automatic background TTL cleanup for zero-dependency local runs and tests.
- **RFC-Compliant Headers**: Injects `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` into HTTP responses.
- **Granular Quota Defense**:
  - *Global Baseline*: 120 req/min per IP with burst protection.
  * *Authentication*: 5 req/min on `/auth/login` to prevent credential brute-forcing.
  * *Password Reset*: 3 req/10 min on `/forgot-password/send-otp` to protect Amazon SES quotas and prevent OTP guessing.
  * *Upload Initiation*: 20 req/min on `/files/upload-url` to prevent presigned URL flooding.

### 2. Direct-to-S3 Presigned Uploads (Bypassing Lambda 6MB Ceiling)
- Large files stream directly from the browser to AWS S3 using short-lived (1-hour) presigned PUT URLs, completely bypassing the 6MB API Gateway / Lambda payload limit.
- Fallback direct multipart upload endpoint is available for small payloads and local environments.

### 3. Hash-Based Content Deduplication
- Files are indexed by SHA-256 checksums in a normalized `ContentBlob` table. If multiple users upload the exact same file, Amazon S3 stores only a single physical copy with reference counting (`ref_count`), slashing storage costs while maintaining strict logical privacy.
- When all references are permanently deleted, S3 blobs are safely pruned.

### 4. Self-Referential Hierarchical Folders
- Recursive folder tree structure with materialized path traversal, circular reference detection (preventing nesting a folder into its own descendant), breadcrumb generation, and cascading deletion.

### 5. Trash Bin & 14-Day Retention Lifecycle
- Soft-deletion mechanism allows users to send files and folders to the Trash bin.
- One-click file restoration, "Restore All", and "Empty Trash" functionality.
- Automated 14-day retention purge background job.

### 6. Password Reset with 6-Digit Email OTP (Amazon SES)
- Secure password recovery using 6-digit cryptographically generated verification codes dispatched via Amazon SES.
- OTPs are stored hashed (`bcrypt`) with a strict 5-minute TTL, single-use consumption flags, and 3-attempt brute-force lockouts.

### 7. Storage Quotas & Admin Governance
- Real-time tracking of used storage bytes vs. allocated quota with automated upload rejection (`HTTP 413 Payload Too Large`).
- Dedicated RBAC Admin Console (`/admin`) to inspect system-wide storage metrics, search and sort users, edit user quotas, and execute per-user S3 storage wipes or account deletions.

### 8. Public & Private File Sharing
- Secure URL-safe tokens for sharing files or folders with customizable permissions (`view` / `download`) and optional expiration timestamps. Public viewer allows anonymous file previews and folder navigation.

### 9. Decoupled AWS SQS Background Worker
- Asynchronous worker Lambda processes SQS events to generate image thumbnails with Pillow and verify content integrity.

---

## 🛠️ Tech Stack

| Category | Technology |
| :--- | :--- |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) 0.111+ (Python 3.11) |
| **Database & ORM** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (Async), [PostgreSQL](https://www.postgresql.org/) with `asyncpg` |
| **Object Storage** | [AWS S3](https://aws.amazon.com/s3/) via `aioboto3` & `boto3` |
| **Serverless Stack** | [AWS Lambda](https://aws.amazon.com/lambda/), [HTTP API Gateway v2](https://aws.amazon.com/api-gateway/), [AWS SAM](https://aws.amazon.com/serverless/sam/) |
| **Background Tasks** | [AWS SQS](https://aws.amazon.com/sqs/) + Python Worker Lambda |
| **Transactional Email**| [Amazon SES](https://aws.amazon.com/ses/) |
| **Database Proxy** | [AWS RDS Proxy](https://aws.amazon.com/rds/proxy/) with SQLAlchemy `NullPool` |
| **Rate Limiter** | `ratelimit-core` (Token Bucket, Redis Lua Scripts, In-Memory Circuit Breaker) |
| **Security & Auth** | JWT (`python-jose`), `passlib[bcrypt]`, RBAC |
| **Image Processing** | [Pillow](https://python-pillow.org/) |
| **Testing** | `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `aiosqlite` |
| **Frontend** | Vanilla ES6+ JavaScript, Modern Responsive CSS (Zero heavy frameworks) |

---

## 📂 Project Directory Layout

```
cloud-storage-backend/
├── app/
│   ├── api/
│   │   ├── deps.py                  # Dependency injection (DB, Auth, Storage, SQS, Rate Limiting)
│   │   └── v1/
│   │       ├── api.py               # Aggregates v1 router
│   │       └── endpoints/
│   │           ├── admin.py         # /admin/stats, /admin/users, /wipe-storage, /users/{id}
│   │           ├── auth.py          # /signup, /login, /me, /quota, /forgot-password
│   │           ├── files.py         # /upload-url, /complete-upload, /download, /trash, /restore
│   │           ├── folders.py       # /tree, /breadcrumbs, CRUD, trash lifecycle
│   │           ├── shares.py        # /shares, /shares/public/{token}
│   │           └── health.py        # /health probe
│   ├── core/
│   │   ├── config.py                # Pydantic BaseSettings & environment config
│   │   ├── rate_limit.py            # Central rate limiter factory & route dependencies
│   │   ├── security.py              # Password hashing & JWT token operations
│   │   ├── exceptions.py            # Domain exceptions (NotFoundError, QuotaExceededError, etc.)
│   │   └── logging.py               # Structured log formatting
│   ├── db/
│   │   ├── base.py                  # Declarative Base
│   │   └── session.py               # Async engine and session factory
│   ├── models/                      # SQLAlchemy 2.0 ORM Models
│   │   ├── user.py                  # User entity & quota
│   │   ├── folder.py                # Self-referential Folder tree
│   │   ├── file.py                  # File entity
│   │   ├── blob.py                  # ContentBlob for deduplication
│   │   ├── share.py                 # SharedLink tokens
│   │   └── password_reset_otp.py    # 6-digit OTP verification records
│   ├── schemas/                     # Pydantic v2 schemas
│   ├── services/                    # Business logic layer (Auth, Files, Folders, Shares, Email, SQS)
│   ├── storage/                     # Storage abstraction layer (Base, S3 aioboto3, Local)
│   ├── worker/                      # AWS SQS Worker Lambda & Tasks
│   └── main.py                      # FastAPI initialization, Rate Limiting, CORS, Mangum handler
├── ratelimit_core/                  # High-performance distributed rate limiter engine
├── static/                          # Modern Frontend Single Page App
│   ├── index.html                   # HTML dashboard
│   ├── app.js                       # Frontend client logic & state management
│   └── style.css                    # Modern responsive design
├── tests/                           # 76 automated pytest async tests
│   ├── test_admin.py
│   ├── test_auth.py
│   ├── test_e2e_full_app.py
│   ├── test_files.py
│   ├── test_folders.py
│   ├── test_health.py
│   ├── test_rate_limiter.py
│   ├── test_shares.py
│   └── test_worker.py
├── template.yaml                    # AWS SAM Serverless deployment template
├── samconfig.toml                   # SAM CLI deployment parameters
├── requirements.txt                 # Production dependencies
├── requirements-dev.txt             # Development & testing dependencies
└── .env.example                     # Environment variables template
```

---

## ⚡ Quickstart Guide (Local Development)

### 1. Prerequisites
- Python 3.11+
- Virtual environment (`venv` or `conda`)
- Optional: Docker & Docker Compose

### 2. Environment Setup
```bash
# Clone repository
git clone https://github.com/vanshmadaan/cloudbox.git
cd cloudbox

# Create and activate virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements-dev.txt

# Configure environment variables
cp .env.example .env
```

### 3. Run Locally with In-Memory Database & Local Storage
By default, you can run CloudBox with zero external AWS dependencies:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
* **Dashboard**: [http://localhost:8000](http://localhost:8000)
* **Interactive API Docs**: [http://localhost:8000/api/v1/docs](http://localhost:8000/api/v1/docs)

---

## 🧪 Running Automated Tests

CloudBox includes a comprehensive test suite of **76 automated tests** covering unit, integration, and end-to-end flows:

```bash
# Run all tests
pytest tests/ -v

# Run with test coverage
pytest --cov=app tests/
```

**Test Breakdown:**
- `test_admin.py`: 8 tests (user quotas, storage wipe, account deletion)
- `test_auth.py`: 14 tests (signup, login, forms, profile, OTP reset)
- `test_e2e_full_app.py`: 1 test (complete client lifecycle)
- `test_files.py`: 21 tests (upload, dedupe, preview, search, download, soft delete)
- `test_folders.py`: 18 tests (nesting, tree exploration, cycle prevention, trash)
- `test_health.py`: 1 test (system health status check)
- `test_rate_limiter.py`: 6 tests (fallback, global headers, 429 triggers, health bypass, route limits)
- `test_shares.py`: 7 tests (public tokens, expiration, permissions, anonymous access)
- `test_worker.py`: 1 test (asynchronous thumbnail generation)

---

## ☁️ Deploying to AWS Serverless

CloudBox is packaged and deployed using the **AWS Serverless Application Model (SAM)**:

```bash
# 1. Build application artifacts inside Docker container (ARM64 Python 3.11)
sam build --use-container

# 2. Deploy to AWS
sam deploy --guided \
  --parameter-overrides \
    DatabaseUrl="postgresql+asyncpg://user:password@your-rds-proxy:5432/cloudstorage" \
    JwtSecretKey="your-strong-production-jwt-secret-key" \
    SesSenderEmail="your-verified-email@domain.com"
```

---

## 🔒 Security Best Practices

1. **Zero Raw Passwords**: Passwords and password reset OTPs are hashed using `bcrypt` with cryptographic salt.
2. **Strict Multi-Tenant Isolation**: Database queries enforce user ownership on every file, folder, and operation.
3. **S3 Private Access**: Direct public access to the S3 bucket is blocked. Files are accessed strictly through time-limited presigned URLs.
4. **Rate Limiting Protection**: Distributed token bucket defense prevents DDoS, brute-force attacks, and presigned URL spam.
5. **Deduplication Privacy**: Shared underlying blobs are abstracted; users can never identify or access another tenant's files.
6. **Input Sanitization**: Client rendering applies XSS escaping, and SQLAlchemy ORM parameterization eliminates SQL injection risks.

---

## 📄 License
This project is licensed under the MIT License.
