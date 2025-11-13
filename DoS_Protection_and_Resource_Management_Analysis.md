# DoS Protection and Resource Management Analysis - Onyx

## Summary
This analysis covers the Denial of Service (DoS) protection mechanisms and resource management in the Onyx codebase, identifying both protective measures and potential vulnerabilities.

### Critical Findings
The codebase has some resource limits but has several concerning DoS vectors that could be exploited.

---

## 1. RATE LIMITING

### Current Implementation
- **Location**: `/home/user/onyx/backend/onyx/server/middleware/rate_limiting.py`
- **Type**: Redis-backed rate limiting using FastAPILimiter
- **Scope**: IP + User-Agent based per request
- **Configuration**:
  - `RATE_LIMIT_MAX_REQUESTS`: Configurable (env var)
  - `RATE_LIMIT_WINDOW_SECONDS`: Configurable (env var)
  - `AUTH_RATE_LIMITING_ENABLED`: Only when both are set

### Issues
1. **Limited Scope**: Rate limiting is only applied to auth endpoints, NOT to general API endpoints
2. **Default Disabled**: Requires explicit configuration to enable
3. **No Per-User Rate Limiting for Chat/Search**: Chat and search endpoints have no rate limiting

---

## 2. FILE UPLOAD LIMITS

### Current Implementation
- **Endpoint**: `/admin/connector/file/upload` (curator/admin only)
- **Location**: `/home/user/onyx/backend/onyx/server/documents/connector.py:538-543`

### DoS Vectors Found

#### Vector 2.1: Unlimited File Upload Size
- **File**: `/home/user/onyx/backend/onyx/server/documents/connector.py:539-543`
- **Issue**: No size limit on uploaded files in `upload_files_api()`
- **Code**:
```python
@router.post("/admin/connector/file/upload")
def upload_files_api(
    files: list[UploadFile],  # NO SIZE LIMIT
    _: User = Depends(current_curator_or_admin_user),
) -> FileUploadResponse:
    return upload_files(files, FileOrigin.OTHER)
```
- **Exploit**: Admin can upload arbitrarily large files, causing disk space exhaustion
- **Impact**: Disk space DoS, server crash

#### Vector 2.2: Zip File Extraction Without Limits
- **File**: `/home/user/onyx/backend/onyx/server/documents/connector.py:476-499`
- **Issue**: Zip files are extracted without checking for zip bombs
- **Code**:
```python
with zipfile.ZipFile(file.file, "r") as zf:
    zip_metadata = extract_zip_metadata(zf)
    for file_info in zf.namelist():  # NO LIMIT on extracted size
        if zf.getinfo(file_info).is_dir():
            continue
        sub_file_bytes = zf.read(file_info)  # Can be arbitrarily large
```
- **Exploit**: Upload a zip bomb (e.g., 42.zip: 42MB compressed, 4.3PB uncompressed)
- **Impact**: Memory exhaustion, server crash

#### Vector 2.3: Multiple File Uploads
- **Issue**: No limits on number of files in single upload
- **Exploit**: Upload 10,000+ files to exhaust disk/database
- **Impact**: Disk space and database DoS

---

## 3. WEB CONNECTOR - UNLIMITED RECURSIVE CRAWLING

### Critical DoS Vector Found

#### Vector 3.1: Unlimited URL Discovery in Recursive Mode
- **File**: `/home/user/onyx/backend/onyx/connectors/web/connector.py:673-727`
- **Issue**: Infinite loop with unbounded URL queue
- **Code**:
```python
while session_ctx.to_visit:  # NO MAXIMUM LIMIT
    initial_url = session_ctx.to_visit.pop()
    if initial_url in session_ctx.visited_links:
        continue
    session_ctx.visited_links.add(initial_url)
    
    if self.recursive:
        internal_links = get_internal_links(base_url, initial_url, soup)
        for link in internal_links:
            if link not in session_ctx.visited_links:
                session_ctx.to_visit.append(link)  # UNLIMITED ADDITIONS
```
- **Exploit**: Create a website with dynamically generated links (e.g., `example.com/page?id=1`, `example.com/page?id=2`, ..., `example.com/page?id=999999`)
- **Result**: Crawler will fetch millions of pages, consuming CPU, memory, and bandwidth indefinitely
- **Impact**: 
  - Worker DoS (Celery worker hangs)
  - Memory exhaustion
  - Bandwidth exhaustion
  - Database connection exhaustion
  - Server crash

#### Vector 3.2: No Timeout on Recursive Crawling
- **File**: `/home/user/onyx/backend/onyx/connectors/web/connector.py:660-735`
- **Issue**: `load_from_state()` has no timeout mechanism
- **Impact**: Crawler can run for hours without interruption

#### Vector 3.3: Playwright Browser Resource Exhaustion
- **Issue**: Creates one Playwright browser context per connector run
- **File**: `/home/user/onyx/backend/onyx/connectors/web/connector.py:272-348`
- **Impact**: Memory leak if crawler hangs

---

## 4. CELERY BACKGROUND TASKS - RATE LIMITING & RESOURCE EXHAUSTION

### Current Configuration
- **Location**: `/home/user/onyx/backend/onyx/background/celery/configs/`
- **Concurrency Settings**:
  - `CELERY_WORKER_LIGHT_CONCURRENCY`: 24 (default)
  - `CELERY_WORKER_BACKGROUND_CONCURRENCY`: 20 (default)
  - `CELERY_WORKER_DOCPROCESSING_CONCURRENCY`: 6 (default)
  - `CELERY_WORKER_HEAVY_CONCURRENCY`: 4 (default)
  - `CELERY_BROKER_POOL_LIMIT`: 10 (default)

### DoS Vectors Found

#### Vector 4.1: Unlimited Task Queueing
- **File**: `/home/user/onyx/backend/onyx/server/documents/connector.py:1313-1370`
- **Endpoint**: POST `/admin/connector/run-once`
- **Issue**: No limit on number of tasks that can be queued
- **Code**:
```python
@router.post("/admin/connector/run-once")
def connector_run_once(
    run_info: RunConnectorRequest,  # No validation on frequency
    _: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse[int]:
    # Can be called unlimited times immediately
    num_triggers = trigger_indexing_for_cc_pair(
        credential_ids,
        connector_id,
        run_info.from_beginning,
        tenant_id,
        db_session,
    )
```
- **Exploit**: Call `/admin/connector/run-once` 1000 times per second
- **Impact**: Broker DoS, task queue overflow

#### Vector 4.2: No Task Rate Limiting
- **File**: `/home/user/onyx/backend/onyx/background/celery/configs/base.py:1-106`
- **Issue**: No `rate_limit` setting on Celery tasks
- **Impact**: Same task can be executed millions of times

#### Vector 4.3: Unlimited Index Attempts
- **File**: `/home/user/onyx/backend/onyx/server/documents/connector.py:1222` and `1610`
- **Issue**: `client_app.send_task()` called without rate limiting
- **Impact**: Unbounded indexing task queue

---

## 5. CHAT & MESSAGE LIMITS

### Current Limits
- **Max Chunks Fed to Chat**: 10.0 (configurable via `MAX_CHUNKS_FED_TO_CHAT`)
- **Num Returned Hits**: 50 (hardcoded)
- **Num Postprocessed Results**: 20 (hardcoded)

### DoS Vectors Found

#### Vector 5.1: Unlimited Chat Session Creation
- **File**: `/home/user/onyx/backend/onyx/server/query_and_chat/chat_backend.py:275-304`
- **Endpoint**: POST `/chat/create-new-session`
- **Issue**: No limit on number of chat sessions a user can create
- **Code**:
```python
@router.post("/create-new-session")
def create_new_chat_session(
    chat_session_creation_request: ChatSessionCreationRequest,
    user: User | None = Depends(current_chat_accessible_user),
    db_session: Session = Depends(get_session),
) -> CreateChatSessionID:
    new_chat_session = create_chat_session(
        db_session=db_session,
        description=chat_session_creation_request.description or "",
        user_id=user_id,
        persona_id=chat_session_creation_request.persona_id,
        project_id=chat_session_creation_request.project_id,
    )
```
- **Exploit**: Create 1 million chat sessions in a loop
- **Impact**: Database bloat, slow queries, storage exhaustion

#### Vector 5.2: No Message Size Limit in Chat
- **File**: `/home/user/onyx/backend/onyx/server/query_and_chat/chat_backend.py`
- **Issue**: No enforced limit on chat message length
- **Impact**: Users can send multi-MB messages causing database/network issues

---

## 6. USER FILE PROCESSING

### Current Limits
- **Max File Size**: 2GB (from `MAX_FILE_SIZE_BYTES` in `/home/user/onyx/backend/onyx/configs/app_configs.py:671-673`)
- **Max Document Chars**: 5,000,000 (from `MAX_DOCUMENT_CHARS`)

### DoS Vectors Found

#### Vector 6.1: Unlimited User File Uploads
- **File**: `/home/user/onyx/backend/onyx/server/features/projects/api.py:75-113`
- **Endpoint**: POST `/file/upload`
- **Issue**: No limit on number of files uploaded per request
- **Code**:
```python
def upload_user_files(
    files: list[UploadFile] = File(...),  # NO LIMIT on list size
    project_id: int | None = Form(None),
    temp_id_map: str | None = Form(None),
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> CategorizedFilesSnapshot:
```
- **Exploit**: Upload 10,000 files in one request
- **Impact**: Memory exhaustion, timeout, database overload

#### Vector 6.2: No Per-User File Limit
- **Issue**: No limit on total number of files a user can upload
- **Exploit**: Upload millions of small files over time
- **Impact**: Database table bloat, query slowdown

---

## 7. CONNECTOR CONFIGURATION LIMITS

### Current Limits
- **Max Slack Query Expansions**: 5 (from `MAX_SLACK_QUERY_EXPANSIONS`)
- **Internet Search Results**: 10 (from `NUM_INTERNET_SEARCH_RESULTS`)
- **Internet Search Chunks**: 50 (from `NUM_INTERNET_SEARCH_CHUNKS`)

### Potential Issues
- **No Limit on Connector Creation**: Users can create unlimited connectors
- **No Limit on Credential Creation**: Multiple credentials per connector

---

## 8. DATABASE & QUERY LIMITS

### Current Configuration
- **PostgreSQL Connection Pool**: 40 connections (primary), 10 (read-only)
- **Pool Overflow**: 10 additional connections allowed
- **Connection Timeout**: Default OS timeout

### DoS Vectors Found

#### Vector 8.1: No Query Timeout Enforcement
- **Issue**: Long-running queries can block connections indefinitely
- **Impact**: Connection pool exhaustion

#### Vector 8.2: Pagination Limits
- **Implemented**: Some endpoints have `le=1000` on page_size
- **But**: Some endpoints have `le=100` while others are unlimited
- **File**: `/home/user/onyx/backend/onyx/server/documents/cc_pair.py:79-80, 115-116, 487-488`

---

## 9. WEB SCRAPING & INTERNET SEARCH LIMITS

### Current Limits
- **Internet Search Results**: 10 (default)
- **Internet Search Chunks**: 50 (default)
- **Web Connector Types**: recursive, single, sitemap, upload

### Potential Issues
- **No Delay Between Requests**: Web connector doesn't rate-limit requests to target site
- **No Robots.txt Checking**: Web connector ignores robots.txt
- **No User-Agent Rotation**: Uses static User-Agent

---

## 10. CONCURRENCY & CONNECTION LIMITS

### Current Configuration
- **PostgreSQL Pool Size**: 40-50 total connections
- **Redis Pool Max Connections**: 128 (from `REDIS_POOL_MAX_CONNECTIONS`)
- **Celery Broker Pool Limit**: 10 (default)

### Issues
- **No Per-IP Connection Limit**: An attacker can monopolize all connections
- **No Per-User Connection Limit**: One user can exhaust the pool

---

## 11. SYSTEM RECURSION & TIMEOUT LIMITS

### Current Configuration
- **System Recursion Limit**: 1000 (from `SYSTEM_RECURSION_LIMIT`)
- **Query Timeout**: 60 seconds (from `QA_TIMEOUT`)
- **Job Timeout**: 6 hours (from `JOB_TIMEOUT`)

### Potential Issues
- **Knowledge Graph Recursion**: Max parent recursion depth not enforced at API level
- **Vespa Timeout**: 15 seconds (from `VESPA_REQUEST_TIMEOUT`)

---

## EXPLOITATION SCENARIOS

### Scenario 1: Complete Server DoS via Web Connector
1. Create a website with infinite link generation
2. Create a web connector in recursive mode pointing to that site
3. Trigger connector run via `/admin/connector/run-once`
4. Crawler will exhaust all Celery workers, CPU, memory, and database connections
5. Service becomes unavailable

### Scenario 2: Disk Space Exhaustion
1. Admin uploads a zip bomb (42.zip - 42MB, expands to 4.3PB)
2. System runs out of disk space
3. Service crashes

### Scenario 3: Database Bloat DoS
1. Create 1 million chat sessions
2. Database grows exponentially
3. Query performance degrades to point of timeout
4. Service becomes unavailable

### Scenario 4: Celery Broker Overflow
1. Create a loop that calls `/admin/connector/run-once` 100 times/second
2. Task queue grows faster than workers can process
3. Redis memory fills up (if using Redis broker)
4. Broker fails, services crash

### Scenario 5: Connection Pool Exhaustion
1. Spawn 50+ concurrent long-running chat requests
2. All database connections in pool are consumed
3. New requests block indefinitely
4. Service appears hung

---

## SUMMARY TABLE

| Vector | Severity | Exploitability | Fix Complexity |
|--------|----------|-----------------|-----------------|
| Unlimited web crawler | **CRITICAL** | High | Medium |
| Unlimited file uploads | **CRITICAL** | High | Low |
| Zip bomb upload | **CRITICAL** | High | Low |
| Unlimited task queuing | **HIGH** | High | Medium |
| Unlimited chat sessions | **HIGH** | Medium | Low |
| No message size limit | **MEDIUM** | High | Low |
| No query timeout | **MEDIUM** | Medium | Medium |
| Unlimited connector runs | **MEDIUM** | Medium | Low |
| No per-user file limit | **MEDIUM** | Medium | Low |

---

## RECOMMENDATIONS

### Immediate (High Priority)
1. Add maximum URL limit to web connector (e.g., 10,000 URLs per run)
2. Add file upload size limit at FastAPI middleware level
3. Add zip bomb detection (check decompressed size before extraction)
4. Add rate limiting to `/admin/connector/run-once` endpoint
5. Add task deduplication to prevent duplicate tasks in queue

### Short Term (Medium Priority)
1. Implement per-user file upload quotas
2. Add message size limit in chat endpoints
3. Add timeout to web connector crawling (e.g., 30 min per run)
4. Add rate limiting to `/chat/create-new-session`
5. Implement database query timeouts

### Long Term (Low Priority)
1. Implement API-wide rate limiting (not just auth)
2. Add per-IP connection limits
3. Implement distributed rate limiting for multi-instance deployments
4. Add robots.txt and crawl-delay enforcement
5. Implement request queuing with backpressure

