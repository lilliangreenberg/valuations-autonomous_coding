# Implementation Plan: Fix Critical Data Persistence and Analysis Issues

**Version**: 1.1
**Date**: 2026-01-30
**Status**: Ready for Implementation
**Estimated Timeline**: 2 weeks

---

## Executive Summary

The Company Valuation Intelligence Tool suffers from three critical bugs that render it non-functional:

1. **Content Storage Failure** (SEVERITY: CRITICAL)
   - **Impact**: 100% of HTML content and 56% of markdown content stored as NULL/empty
   - **Root Cause**: No validation after HTTP 200 responses, empty responses stored without detection
   - **Evidence**: Database analysis shows `content IS NULL OR content = ''` for majority of snapshots

2. **Signal Detection Failure** (SEVERITY: CRITICAL)
   - **Impact**: All companies stuck at "unknown" status with empty signals arrays
   - **Root Cause**: Content filtering logic fails on empty strings, no database fallback mechanism
   - **Evidence**: `signals = '[]'` for 100% of companies in database

3. **Unnecessary Concurrency Complexity** (SEVERITY: HIGH)
   - **Impact**: Database lock errors, race conditions, complex debugging
   - **Root Cause**: Async/concurrent implementation for batch job that doesn't need parallelism
   - **Evidence**: "database is locked" errors in logs, session management complexity

**Current State**: Application scrapes websites successfully (HTTP 200) but produces zero actionable intelligence.

**Desired State**: Reliable sequential processing with accurate status detection and comprehensive signal generation.

### ⚠️ CRITICAL: Test Suite Updates Required

**WARNING**: The initial implementation of Phase 1 failed to update the test suite when converting from async to sync. All implementations must include comprehensive test updates.

**Test Update Requirements**:

- **Phase 1**: Convert all async tests to sync (remove `async`/`await`, update `BatchProcessor` instantiation)
- **Phase 2**: Add empty content validation tests, update existing tests to verify new behavior
- **Each Phase**: Verify all tests pass before marking phase complete

**Consequences of Skipping Test Updates**:
- ❌ Test suite fails to run
- ❌ Code changes are not validated
- ❌ Regressions can be introduced without detection
- ❌ Deployment confidence is compromised

See detailed test update instructions in each phase's implementation section.

---

## Architectural Decision: Remove Concurrency

### Rationale

**Core Insight**: This is a background batch job. Processing time is irrelevant. Correctness and reliability are the ONLY priorities.

**Why Remove Async/Concurrency**:

1. **Database Lock Errors**: SQLite with `StaticPool` cannot handle concurrent writes reliably
2. **Complexity Tax**: Async code is harder to debug, maintain, and reason about
3. **False Optimization**: Batch processing 20 companies at a time doesn't benefit from concurrency
4. **Network Bottleneck**: Firecrawl API is the bottleneck, not CPU or local I/O
5. **Acceptable Performance**: 10-30 minutes for 100 companies is perfectly fine for a batch job

**Benefits of Sequential Processing**:

- **Zero database lock errors** - Single thread, single connection
- **Simpler code** - No async/await, no asyncio.gather, no session juggling
- **Easier debugging** - Linear execution flow, clear stack traces
- **Predictable behavior** - No race conditions, no timing issues
- **Reliable retries** - Simple retry logic works correctly

**Performance Impact** (NOT A CONCERN):

| Scenario | Concurrent | Sequential | Acceptable? |
|----------|-----------|------------|-------------|
| 100 companies | ~8 min (fails) | ~20 min | ✓ YES |
| 979 companies | ~60 min (fails) | ~180 min | ✓ YES |
| 5000 companies | N/A | ~15 hours | ✓ YES |

**Verdict**: **Perfect architectural decision** - eliminates all concurrency bugs, code actually works.

### New Architecture

```
Process Batch (Sequential)
├─ For each company in batch:
│  ├─ Scrape careers page (sequential)
│  ├─ Scrape about page (sequential)
│  ├─ Scrape news page (sequential)
│  ├─ Detect signals (using scraped or DB content)
│  ├─ Determine status
│  └─ Update database (single session)
└─ Commit batch results
```

**Key Changes**:
- No `async`/`await` keywords anywhere
- No `asyncio.gather()` for concurrent execution
- No concurrent workers or thread pools
- Single database session per batch
- Simple for loops replace concurrent execution

---

## Root Cause Analysis

### Bug 1: Content Storage Failure

**Symptoms**:
```sql
-- Database evidence
SELECT
  COUNT(*) as total,
  SUM(CASE WHEN content IS NULL THEN 1 ELSE 0 END) as null_content,
  SUM(CASE WHEN content = '' THEN 1 ELSE 0 END) as empty_content,
  SUM(CASE WHEN markdown IS NULL THEN 1 ELSE 0 END) as null_markdown
FROM url_snapshots;

-- Result: High percentage of NULL/empty content despite HTTP 200 responses
```

**Root Cause Chain**:

1. **Firecrawl Service** (`adaptive_scraper_service.py:225-253`)
   - Returns HTTP 200 even when content extraction fails
   - No validation that `data.get('markdown')` or `data.get('html')` is non-empty
   - Empty strings propagate through system

2. **Playwright Service** (`adaptive_scraper_service.py:255-277`)
   - Can return empty string if page is blank or blocked
   - No validation before returning result

3. **Snapshot Storage** (`adaptive_scraper_service.py:327-377`)
   - Stores whatever content is provided without validation
   - No logging of empty content storage

**Evidence from Code**:

```python
# adaptive_scraper_service.py:241-245
success_data = scrape_result.get("data", {})
return ScrapeResult(
    success=True,
    content=success_data.get("markdown", ""),  # Empty string stored
    html=success_data.get("html"),  # NULL stored
    # ...
)
```

**Impact**: Empty snapshots prevent signal detection, causing 100% "unknown" status.

### Bug 2: Signal Detection Failure

**Symptoms**:
```sql
SELECT status, COUNT(*) FROM companies GROUP BY status;
-- Result: status='unknown' for 100% of companies

SELECT COUNT(*) FROM companies WHERE signals = '[]';
-- Result: 100% have empty signals arrays
```

**Root Cause Chain**:

1. **Content Filtering** (`batch_processing_service.py:496-517`)
   ```python
   if not content or not content.strip():
       return None  # No fallback mechanism
   ```
   - Empty content from current scrape = no analysis
   - No attempt to load historical content from database

2. **Signal Aggregation** (`batch_processing_service.py:557-586, 632-673`)
   - Requires content from scrape
   - No fallback to database snapshots
   - Empty content = empty signals = "unknown" status

3. **Status Determination** (`intelligence_service.py:60-120`)
   - Depends entirely on signals array
   - Empty signals = default to "unknown"
   - No explanation generated

**Evidence from Code**:

```python
# batch_processing_service.py:508-517
def _scrape_url_adaptive(url: str, url_type: str) -> tuple[str | None, str | None]:
    result = scraper_service.scrape_url(url, url_type)
    if not result.content or not result.content.strip():
        return None, None  # NO DATABASE FALLBACK
    return result.content, result.html
```

**Impact**: Zero companies flagged for review, tool produces no actionable intelligence.

### Bug 3: Concurrency Complexity

**Symptoms**:
```
ERROR: database is locked
asyncio.exceptions.CancelledError
Session <xyz> is already closed
```

**Root Cause Chain**:

1. **SQLite Limitations**
   - `StaticPool` uses single connection
   - Concurrent writes cause "database is locked" errors
   - Even with `check_same_thread=False`, not safe for concurrent writes

2. **Async Session Management**
   - Multiple coroutines share database sessions
   - Sessions closed unexpectedly during concurrent operations
   - Complex lifecycle management prone to errors

3. **Unnecessary Complexity**
   - Batch job doesn't benefit from concurrency
   - Network I/O (Firecrawl) is bottleneck, not local processing
   - Async code harder to debug and maintain

**Evidence from Code**:

```python
# batch_processing_service.py:346
results = await asyncio.gather(*tasks)  # Concurrent execution causes locks

# database.py:56-60
StaticPool,  # Single connection shared by concurrent tasks
connect_args={"check_same_thread": False},  # Unsafe workaround
```

**Impact**: Unreliable processing, difficult debugging, production failures.

---

## Solution Architecture

### Phase 1: Remove Concurrency Infrastructure

**Objective**: Convert async/concurrent implementation to simple sequential processing.

**Changes**:

1. **Batch Processing Service** (`batch_processing_service.py`)
   - Remove all `async`/`await` keywords
   - Replace `asyncio.gather()` with simple for loops
   - Make all methods synchronous
   - Simplify database session management (single session per batch)

2. **Playwright Client** (`playwright_client.py`)
   - Remove async context managers
   - Convert to synchronous browser automation
   - Simplify lifecycle management

3. **HTTP Clients**
   - Replace `AsyncClient` with synchronous `httpx.Client` or `requests`
   - Remove async HTTP calls

4. **Database Configuration** (`database.py`)
   - Keep `StaticPool` (perfect for single-threaded access)
   - Remove `check_same_thread=False` (not needed)
   - Keep `expire_on_commit=False` (still useful)
   - Add `PRAGMA busy_timeout=5000` for safety

5. **Configuration** (`config.py`)
   - Remove `concurrency` parameter
   - Keep `batch_size=20` (for Firecrawl batch API)

**Expected Outcome**: Zero database lock errors, simpler codebase, reliable execution.

### Phase 2: Content Storage & Signal Detection Fixes

**Objective**: Detect empty content, validate storage, add database fallback mechanism.

**Multi-Layered Approach**:

#### Layer 1: Scraping Validation

**File**: `adaptive_scraper_service.py`

**Changes**:

1. **Firecrawl Validation** (Lines 225-253)
   ```python
   def _scrape_with_firecrawl(self, url: str, url_type: str) -> ScrapeResult:
       # Existing Firecrawl logic...

       # NEW: Validate content is not empty
       markdown = success_data.get("markdown", "")
       html = success_data.get("html")

       if not markdown or not markdown.strip():
           logger.warning(
               "firecrawl_empty_content",
               url=url,
               has_html=bool(html and html.strip())
           )

       return ScrapeResult(
           success=True,
           content=markdown,
           html=html,
           # ...
       )
   ```

2. **Playwright Validation** (Lines 255-277)
   ```python
   def _scrape_with_playwright(self, url: str) -> ScrapeResult:
       # Existing Playwright logic...

       content = page.content()  # HTML content

       # NEW: Validate content is not empty
       if not content or not content.strip():
           logger.warning(
               "playwright_empty_content",
               url=url,
               content_length=len(content) if content else 0
           )

       return ScrapeResult(
           success=True,
           content=content,
           # ...
       )
   ```

3. **Snapshot Storage Enhancement** (Lines 327-377)
   ```python
   def _finalize_scrape(self, result: ScrapeResult, url: str, url_type: str) -> ScrapeResult:
       # Existing snapshot creation...

       # NEW: Always store snapshot when content is empty (for debugging)
       content_empty = not result.content or not result.content.strip()

       if content_empty:
           logger.warning(
               "storing_empty_content_snapshot",
               url=url,
               url_type=url_type,
               has_html=bool(result.html)
           )

       # Store snapshot regardless (for historical tracking)
       # ...
   ```

#### Layer 2: Database Fallback Mechanism

**File**: `batch_processing_service.py`

**Changes**:

1. **New Helper Method** (After line 495)
   ```python
   def _load_content_from_db(
       self,
       company: Company,
       url_type: str
   ) -> tuple[str | None, str | None]:
       """
       Load most recent non-empty content from database snapshots.

       Fallback strategy when current scrape returns empty content.
       Prefers recent snapshots but will use older content if needed.
       """
       url_map = {
           "careers": company.careers_url,
           "about": company.about_url,
           "news": company.news_url
       }

       url = url_map.get(url_type)
       if not url:
           return None, None

       # Query for most recent non-empty snapshot
       snapshot = (
           self.session.query(URLSnapshot)
           .filter(
               URLSnapshot.company_id == company.id,
               URLSnapshot.url == url,
               URLSnapshot.content.isnot(None),
               URLSnapshot.content != ""
           )
           .order_by(URLSnapshot.scraped_at.desc())
           .first()
       )

       if snapshot:
           logger.info(
               "loaded_content_from_db",
               company=company.name,
               url_type=url_type,
               snapshot_age_days=(datetime.utcnow() - snapshot.scraped_at).days
           )
           return snapshot.content, snapshot.html

       logger.warning(
           "no_historical_content",
           company=company.name,
           url_type=url_type
       )
       return None, None
   ```

2. **Enhanced Scraping with Fallback** (Lines 496-517)
   ```python
   def _scrape_url_adaptive(
       self,
       company: Company,
       url: str,
       url_type: str
   ) -> tuple[str | None, str | None]:
       """Scrape URL with database fallback if content is empty."""

       # Attempt fresh scrape
       result = self.scraper_service.scrape_url(url, url_type)

       # Check if content is empty
       if not result.content or not result.content.strip():
           logger.warning(
               "empty_scrape_result",
               company=company.name,
               url=url,
               url_type=url_type
           )

           # NEW: Fallback to database content
           db_content, db_html = self._load_content_from_db(company, url_type)
           if db_content:
               logger.info(
                   "using_db_fallback_content",
                   company=company.name,
                   url_type=url_type
               )
               return db_content, db_html

           return None, None

       return result.content, result.html
   ```

3. **Updated Signal Detection** (Lines 557-586)
   ```python
   def _detect_acquisitions(self, company: Company) -> list[Signal]:
       """Detect acquisition signals with database fallback."""

       # Try careers page first
       careers_content = None
       if company.careers_url:
           careers_content, _ = self._scrape_url_adaptive(
               company, company.careers_url, "careers"
           )

       # NEW: Fallback to about page if careers empty
       if not careers_content and company.about_url:
           logger.info(
               "acquisition_detection_using_about_fallback",
               company=company.name
           )
           careers_content, _ = self._scrape_url_adaptive(
               company, company.about_url, "about"
           )

       # Analyze with content (from scrape or DB)
       if careers_content:
           return self.dead_website_detector.analyze_url_result(
               url=company.careers_url or company.about_url,
               url_type="careers",
               content=careers_content,
               html=None,
               error=None
           )

       return []
   ```

#### Layer 3: Empty Content Signal Type

**File**: `core/dead_website_detection.py`

**Changes**:

1. **New Signal Type** (Line 37)
   ```python
   class DeadWebsiteSignalType(str, Enum):
       # Existing types...
       EMPTY_CONTENT = "empty_content"  # NEW
   ```

2. **Detection Function** (After line 200)
   ```python
   def detect_empty_content(
       url: str,
       content: str | None,
       html: str | None
   ) -> Signal | None:
       """
       Detect when scraping succeeds (HTTP 200) but returns no usable content.

       This indicates:
       - Page blocked by anti-scraping measures
       - JavaScript-heavy site that doesn't render server-side
       - Redirect to error page that returns 200
       - Cloudflare or similar protection

       Returns negative signal (company may be operational but unscrapable).
       """

       content_empty = not content or not content.strip()
       html_empty = not html or not html.strip()

       if content_empty and html_empty:
           return Signal(
               signal_type=DeadWebsiteSignalType.EMPTY_CONTENT,
               confidence=0.7,  # Medium confidence - could be scraping issue
               description=f"Scraping {url} succeeded but returned no content. "
                          f"May indicate anti-scraping measures or JavaScript rendering issues.",
               evidence={
                   "url": url,
                   "content_length": len(content) if content else 0,
                   "html_length": len(html) if html else 0
               },
               detected_at=datetime.utcnow()
           )

       return None
   ```

3. **Integration into Analysis** (Around line 300)
   ```python
   def analyze_url_result(
       self,
       url: str,
       url_type: str,
       content: str | None = None,
       html: str | None = None,
       error: Exception | None = None
   ) -> list[Signal]:
       """Analyze URL scrape result for all signal types."""

       signals = []

       # NEW: Check for empty content first
       empty_signal = detect_empty_content(url, content, html)
       if empty_signal:
           signals.append(empty_signal)

       # Only run other detectors if we have content
       if content:
           # Existing detection logic...
           signals.extend(detect_acquisition_indicators(content))
           signals.extend(detect_dead_website_signals(content, html))
           signals.extend(detect_operational_signals(content))

       return signals
   ```

**Expected Outcome**:
- <5% of companies with empty content (valid edge cases)
- Empty content detected and flagged as negative signal
- Historical content used when current scrape fails
- >95% of snapshots have usable content

---

## Phase 1 Implementation Details: Remove Concurrency

### File 1: `batch_processing_service.py`

**Comprehensive Changes**:

```python
# BEFORE (Async/Concurrent)
class BatchProcessingService:
    async def process_batch(self, companies: list[Company]) -> BatchResult:
        tasks = [self._process_company(c) for c in companies]
        results = await asyncio.gather(*tasks)
        # ...

# AFTER (Sequential)
class BatchProcessingService:
    def process_batch(self, companies: list[Company]) -> BatchResult:
        results = []
        for company in companies:
            result = self._process_company(company)
            results.append(result)
        # ...
```

**Detailed Changes by Section**:

1. **Method Signatures** (Throughout file)
   ```python
   # Remove 'async' from ALL method definitions
   # BEFORE: async def _process_company(...)
   # AFTER:  def _process_company(...)
   ```

2. **Method Calls** (Throughout file)
   ```python
   # Remove 'await' from ALL method calls
   # BEFORE: result = await self._scrape_url_adaptive(...)
   # AFTER:  result = self._scrape_url_adaptive(...)
   ```

3. **Concurrent Execution** (Lines 346, 365, 440)
   ```python
   # BEFORE
   tasks = [self._scrape_url_adaptive(url, url_type) for url in urls]
   results = await asyncio.gather(*tasks)

   # AFTER
   results = []
   for url in urls:
       result = self._scrape_url_adaptive(url, url_type)
       results.append(result)
   ```

4. **Database Session Management**
   ```python
   # BEFORE: Complex session handling with async context managers
   async with self.session_factory() as session:
       # ...

   # AFTER: Simple session per batch
   def process_batch(self, companies: list[Company]) -> BatchResult:
       session = self.session_factory()
       try:
           # Process all companies
           for company in companies:
               # ...
           session.commit()
       except Exception as e:
           session.rollback()
           raise
       finally:
           session.close()
   ```

### File 2: `playwright_client.py`

**Complete Synchronous Conversion**:

```python
# BEFORE (Async)
from playwright.async_api import async_playwright

class PlaywrightClient:
    async def __aenter__(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch()
        return self

    async def __aexit__(self, *args):
        await self.browser.close()
        await self.playwright.stop()

    async def scrape_url(self, url: str) -> str:
        page = await self.browser.new_page()
        await page.goto(url)
        content = await page.content()
        await page.close()
        return content

# AFTER (Synchronous)
from playwright.sync_api import sync_playwright

class PlaywrightClient:
    def __enter__(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch()
        return self

    def __exit__(self, *args):
        self.browser.close()
        self.playwright.stop()

    def scrape_url(self, url: str) -> str:
        page = self.browser.new_page()
        page.goto(url)
        content = page.content()
        page.close()
        return content
```

### File 3: `adaptive_scraper_service.py`

**HTTP Client Changes**:

```python
# BEFORE (Async)
from httpx import AsyncClient

class AdaptiveScraperService:
    async def _scrape_with_firecrawl(self, url: str) -> ScrapeResult:
        async with AsyncClient() as client:
            response = await client.post(...)
        # ...

# AFTER (Synchronous)
import httpx  # or import requests

class AdaptiveScraperService:
    def _scrape_with_firecrawl(self, url: str) -> ScrapeResult:
        with httpx.Client() as client:
            response = client.post(...)
        # ...
```

### File 4: `database.py`

**Simplified Configuration**:

```python
# BEFORE
engine = create_engine(
    f"sqlite:///{db_path}",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},  # Unsafe for concurrent writes
    echo=False,
)

# AFTER
engine = create_engine(
    f"sqlite:///{db_path}",
    poolclass=StaticPool,  # Perfect for single-threaded access
    connect_args={
        "timeout": 30,  # Wait up to 30 seconds for lock (shouldn't happen)
    },
    echo=False,
)

# Set pragmas for safety
with engine.connect() as conn:
    conn.execute(text("PRAGMA busy_timeout = 5000"))  # 5 second timeout
    conn.execute(text("PRAGMA journal_mode = WAL"))  # Better concurrency (if needed later)
```

### File 5: `config.py`

**Remove Concurrency Parameters**:

```python
# BEFORE
class Config(BaseSettings):
    batch_size: int = 20
    concurrency: int = 5  # REMOVE THIS
    # ...

# AFTER
class Config(BaseSettings):
    batch_size: int = 20  # Keep for Firecrawl batch API
    # concurrency parameter removed
    # ...
```

### Testing Phase 1 Changes

**Unit Tests** (Should still pass):
```bash
pytest tests/unit/test_batch_processing_service.py -v
pytest tests/unit/test_scraper_service.py -v
pytest tests/unit/test_dead_website_detection.py -v
```

**Integration Test** (New minimal test):
```python
# tests/integration/test_sequential_processing.py
def test_sequential_batch_processing():
    """Verify sequential processing works without database locks."""

    service = BatchProcessingService(session_factory)
    companies = session.query(Company).limit(10).all()

    # Should complete without errors
    result = service.process_batch(companies)

    assert result.total_processed == 10
    assert result.errors == []  # No database lock errors
    assert all(c.status != "unknown" for c in companies)
```

**Manual Verification**:
```bash
# Process small batch
uv run valuation-tool process --limit 20

# Check logs for errors
tail -f ~/.local/share/valuation-tool/logs/valuation-tool.log | grep -i "error\|lock"

# Verify no database lock errors
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT error_log FROM processing_runs ORDER BY id DESC LIMIT 1;" | grep -i lock
```

**Success Criteria**:
- ✓ Zero "database is locked" errors
- ✓ Zero async-related errors (CancelledError, etc.)
- ✓ All existing tests pass
- ✓ Can process 20 companies end-to-end
- ✓ Simpler code (fewer lines, no async complexity)

### Fixing Phase 1 Tests (CRITICAL)

**IMPORTANT**: The original implementation failed to update tests when converting from async to sync. All tests in `test_batch_processing.py` must be updated.

**File**: `tests/unit/test_batch_processing.py`

**Required Changes**:

1. **Remove async imports** (Line 13):
   ```python
   # BEFORE
   import asyncio

   # AFTER
   # Remove this import completely
   ```

2. **Update test description** (Line 6):
   ```python
   # BEFORE
   - Parallel company processing

   # AFTER
   - Sequential company processing
   ```

3. **Fix test configuration** (Line 49):
   ```python
   # BEFORE
   return Config(
       scraper=ScraperConfig(batch_size=20, concurrency=5),
       playwright=PlaywrightConfig(delay_between_actions_ms=100),
   )

   # AFTER
   return Config(
       scraper=ScraperConfig(batch_size=20),  # Remove concurrency parameter
       playwright=PlaywrightConfig(delay_between_actions_ms=100),
   )
   ```

4. **Remove all async decorators** (3 occurrences - lines 222, 259, 438):
   ```python
   # BEFORE
   @pytest.mark.asyncio
   class TestCompanyProcessing:

   # AFTER
   class TestCompanyProcessing:
   ```

5. **Convert all test methods from async to sync** (7 test methods):
   ```python
   # BEFORE
   async def test_process_company_success(self, in_memory_db, test_config, sample_companies):
       processor = BatchProcessor(in_memory_db, test_config)
       result = await processor.process_company(company)

   # AFTER
   def test_process_company_success(self, in_memory_db, test_config, sample_companies):
       session_factory = sessionmaker(bind=in_memory_db.get_bind())
       processor = BatchProcessor(session_factory, test_config)
       result = processor.process_company(company)
   ```

6. **Fix BatchProcessor instantiation throughout file** (12 occurrences):
   ```python
   # BEFORE
   processor = BatchProcessor(in_memory_db, test_config)

   # AFTER
   session_factory = sessionmaker(bind=in_memory_db.get_bind())
   processor = BatchProcessor(session_factory, test_config)
   ```

7. **Fix broken mock in exception test** (Line 246):
   ```python
   # BEFORE
   with patch.object(
       processor.concurrent_throttler,  # This doesn't exist!
       "throttle",
       side_effect=RuntimeError("Test error"),
   ):

   # AFTER
   with patch.object(
       processor,
       "_scrape_url_adaptive",  # Mock an actual method
       side_effect=RuntimeError("Test error"),
   ):
   ```

8. **Fix factory function tests** (Lines 417-435):
   ```python
   # BEFORE
   def test_create_batch_processor(self, in_memory_db, test_config):
       processor = create_batch_processor(in_memory_db, test_config)
       assert processor.session == in_memory_db

   # AFTER
   def test_create_batch_processor(self, in_memory_db, test_config):
       session_factory = sessionmaker(bind=in_memory_db.get_bind())
       processor = create_batch_processor(session_factory, test_config)
       assert processor.session_factory == session_factory
   ```

**Additional Cleanup in Production Code**:

Remove dead code from `batch_processing_service.py`:

```python
# Lines 41-43: Remove unused import
# BEFORE
from valuation_tool.infrastructure.rate_limiter import (
    create_rate_limiter,
)

# AFTER
# Remove entire import

# Line 220: Remove unused rate limiter
# BEFORE
self.playwright_limiter = create_rate_limiter(config.playwright)

# AFTER
# Remove this line completely
```

**Verification**:

```bash
# Run syntax check
python -m py_compile tests/unit/test_batch_processing.py

# Run tests
pytest tests/unit/test_batch_processing.py -v

# Should see output like:
# test_organize_into_batches_exact_multiple PASSED
# test_process_company_success PASSED
# test_process_batch PASSED
# ... etc
```

**Common Pitfalls**:

1. ❌ **Missing session_factory creation**: Every test that creates `BatchProcessor` needs to create a `session_factory` first
2. ❌ **Leftover await keywords**: Search for `await` to ensure all are removed
3. ❌ **Leftover @pytest.mark.asyncio**: Search for `asyncio` to ensure all decorators are removed
4. ❌ **Wrong assertions**: Change `processor.session` to `processor.session_factory`
5. ❌ **Forgetting to remove asyncio import**: This will cause confusion if left in

---

## Phase 2 Implementation Details: Content & Signal Detection

### Layer 1: Scraping Validation

**File**: `adaptive_scraper_service.py`

**Change 1: Firecrawl Validation** (Lines 225-253)

```python
def _scrape_with_firecrawl(self, url: str, url_type: str) -> ScrapeResult:
    """Scrape URL using Firecrawl API with content validation."""

    try:
        response = self._call_firecrawl_api(url, url_type)

        if response.status_code == 200:
            data = response.json()
            success_data = data.get("data", {})

            # Extract content
            markdown = success_data.get("markdown", "")
            html = success_data.get("html")

            # NEW: Validate content is not empty
            content_empty = not markdown or not markdown.strip()
            html_empty = not html or not html.strip()

            if content_empty and html_empty:
                logger.warning(
                    "firecrawl_returned_empty_content",
                    url=url,
                    url_type=url_type,
                    response_success=data.get("success", False),
                    has_data=bool(success_data)
                )
            elif content_empty:
                logger.warning(
                    "firecrawl_markdown_empty",
                    url=url,
                    url_type=url_type,
                    html_length=len(html) if html else 0
                )

            return ScrapeResult(
                success=True,
                content=markdown,
                html=html,
                method="firecrawl"
            )

        # Error handling...

    except Exception as e:
        logger.error("firecrawl_exception", url=url, error=str(e))
        return ScrapeResult(success=False, content=None, error=str(e))
```

**Change 2: Playwright Validation** (Lines 255-277)

```python
def _scrape_with_playwright(self, url: str) -> ScrapeResult:
    """Scrape URL using Playwright with content validation."""

    try:
        with self.playwright_client as client:
            html = client.scrape_url(url)

            # NEW: Validate content is not empty
            if not html or not html.strip():
                logger.warning(
                    "playwright_returned_empty_content",
                    url=url,
                    content_length=len(html) if html else 0
                )

            return ScrapeResult(
                success=True,
                content=html,  # Playwright returns HTML as content
                html=html,
                method="playwright"
            )

    except Exception as e:
        logger.error("playwright_exception", url=url, error=str(e))
        return ScrapeResult(success=False, content=None, error=str(e))
```

**Change 3: Snapshot Storage Enhancement** (Lines 327-377)

```python
def _finalize_scrape(
    self,
    result: ScrapeResult,
    url: str,
    url_type: str,
    company_id: int
) -> ScrapeResult:
    """Store snapshot with empty content tracking."""

    # NEW: Check if content is empty
    content_empty = not result.content or not result.content.strip()
    html_empty = not result.html or not result.html.strip()

    if content_empty:
        logger.warning(
            "storing_empty_content_snapshot",
            url=url,
            url_type=url_type,
            company_id=company_id,
            has_html=not html_empty,
            method=result.method
        )

    # Store snapshot (even if empty, for debugging)
    snapshot = URLSnapshot(
        company_id=company_id,
        url=url,
        content=result.content,
        html=result.html,
        scraped_at=datetime.utcnow(),
        scrape_method=result.method,
        success=result.success,
        error_message=result.error
    )

    self.session.add(snapshot)
    self.session.commit()

    logger.info(
        "snapshot_stored",
        url=url,
        url_type=url_type,
        content_empty=content_empty,
        snapshot_id=snapshot.id
    )

    return result
```

### Layer 2: Database Fallback Mechanism

**File**: `batch_processing_service.py`

**Change 1: New Helper Method** (After line 495)

```python
def _load_content_from_db(
    self,
    company: Company,
    url_type: str
) -> tuple[str | None, str | None]:
    """
    Load most recent non-empty content from database snapshots.

    This is a fallback mechanism when current scraping returns empty content.
    Prefers recent snapshots but will use older content if needed.

    Args:
        company: Company to load content for
        url_type: Type of URL (careers, about, news)

    Returns:
        Tuple of (content, html) or (None, None) if no historical content
    """

    # Map URL type to company attribute
    url_map = {
        "careers": company.careers_url,
        "about": company.about_url,
        "news": company.news_url
    }

    url = url_map.get(url_type)
    if not url:
        logger.warning(
            "no_url_for_type",
            company=company.name,
            url_type=url_type
        )
        return None, None

    # Query for most recent non-empty snapshot
    snapshot = (
        self.session.query(URLSnapshot)
        .filter(
            URLSnapshot.company_id == company.id,
            URLSnapshot.url == url,
            URLSnapshot.content.isnot(None),
            URLSnapshot.content != ""
        )
        .order_by(URLSnapshot.scraped_at.desc())
        .first()
    )

    if snapshot:
        age_days = (datetime.utcnow() - snapshot.scraped_at).days
        logger.info(
            "loaded_content_from_db",
            company=company.name,
            url_type=url_type,
            snapshot_id=snapshot.id,
            snapshot_age_days=age_days,
            content_length=len(snapshot.content) if snapshot.content else 0
        )
        return snapshot.content, snapshot.html

    logger.warning(
        "no_historical_content",
        company=company.name,
        url_type=url_type,
        url=url
    )
    return None, None
```

**Change 2: Enhanced Scraping with Fallback** (Lines 496-517)

```python
def _scrape_url_adaptive(
    self,
    company: Company,
    url: str,
    url_type: str
) -> tuple[str | None, str | None]:
    """
    Scrape URL with database fallback if content is empty.

    Strategy:
    1. Attempt fresh scrape
    2. If empty, load most recent non-empty content from database
    3. If no historical content, return None

    Args:
        company: Company being processed
        url: URL to scrape
        url_type: Type of URL (careers, about, news)

    Returns:
        Tuple of (content, html) or (None, None) if unavailable
    """

    # Attempt fresh scrape
    logger.info("scraping_url", company=company.name, url=url, url_type=url_type)
    result = self.scraper_service.scrape_url(url, url_type)

    # Check if content is empty
    content_empty = not result.content or not result.content.strip()

    if result.success and content_empty:
        logger.warning(
            "empty_scrape_result",
            company=company.name,
            url=url,
            url_type=url_type,
            method=result.method
        )

        # NEW: Fallback to database content
        db_content, db_html = self._load_content_from_db(company, url_type)

        if db_content:
            logger.info(
                "using_db_fallback_content",
                company=company.name,
                url_type=url_type,
                db_content_length=len(db_content)
            )
            return db_content, db_html

        # No historical content available
        logger.warning(
            "no_content_available",
            company=company.name,
            url=url,
            url_type=url_type
        )
        return None, None

    if not result.success:
        logger.error(
            "scrape_failed",
            company=company.name,
            url=url,
            error=result.error
        )

        # Try database fallback even on errors
        db_content, db_html = self._load_content_from_db(company, url_type)
        if db_content:
            logger.info(
                "using_db_fallback_after_error",
                company=company.name,
                url_type=url_type
            )
            return db_content, db_html

        return None, None

    # Success with content
    return result.content, result.html
```

**Change 3: Updated Acquisition Detection** (Lines 557-586)

```python
def _detect_acquisitions(self, company: Company) -> list[Signal]:
    """
    Detect acquisition signals with database fallback.

    Strategy:
    1. Try careers page first (most likely to show acquisition notice)
    2. If careers empty, try about page
    3. Use database fallback for both
    """

    logger.info("detecting_acquisitions", company=company.name)

    # Try careers page first
    careers_content = None
    if company.careers_url:
        careers_content, _ = self._scrape_url_adaptive(
            company, company.careers_url, "careers"
        )

    # NEW: Fallback to about page if careers empty
    if not careers_content and company.about_url:
        logger.info(
            "acquisition_detection_using_about_fallback",
            company=company.name
        )
        careers_content, _ = self._scrape_url_adaptive(
            company, company.about_url, "about"
        )

    # Analyze with content (from fresh scrape or database)
    if careers_content:
        signals = self.dead_website_detector.analyze_url_result(
            url=company.careers_url or company.about_url,
            url_type="careers",
            content=careers_content,
            html=None,
            error=None
        )

        logger.info(
            "acquisition_signals_detected",
            company=company.name,
            signal_count=len(signals),
            signal_types=[s.signal_type for s in signals]
        )
        return signals

    logger.warning(
        "no_content_for_acquisition_detection",
        company=company.name
    )
    return []
```

**Change 4: Updated Operational Detection** (Lines 632-673)

```python
def _detect_operational(self, company: Company) -> list[Signal]:
    """
    Detect operational signals with database fallback.

    Strategy:
    1. Collect content from all available URLs
    2. Use database fallback for each URL
    3. Analyze combined content
    """

    logger.info("detecting_operational_signals", company=company.name)

    all_content = []

    # Try all URLs with fallback
    for url_type in ["careers", "about", "news"]:
        url = getattr(company, f"{url_type}_url", None)
        if url:
            content, _ = self._scrape_url_adaptive(company, url, url_type)
            if content:
                all_content.append(content)
                logger.debug(
                    "collected_content_for_operational",
                    company=company.name,
                    url_type=url_type,
                    content_length=len(content)
                )

    if not all_content:
        logger.warning(
            "no_content_for_operational_detection",
            company=company.name
        )
        return []

    # Analyze combined content
    combined = "\n\n".join(all_content)
    signals = self.dead_website_detector.analyze_url_result(
        url=company.about_url or company.careers_url,
        url_type="combined",
        content=combined,
        html=None,
        error=None
    )

    logger.info(
        "operational_signals_detected",
        company=company.name,
        signal_count=len(signals),
        signal_types=[s.signal_type for s in signals],
        total_content_length=len(combined)
    )

    return signals
```

### Layer 3: Empty Content Signal Type

**File**: `core/dead_website_detection.py`

**Change 1: New Signal Type** (Line 37)

```python
class DeadWebsiteSignalType(str, Enum):
    """Types of signals detected during analysis."""

    # Existing signal types
    HTTP_ERROR = "http_error"
    DOMAIN_EXPIRED = "domain_expired"
    PAGE_NOT_FOUND = "page_not_found"
    ACQUISITION_NOTICE = "acquisition_notice"
    REDIRECT_TO_PARENT = "redirect_to_parent"
    RECENT_JOB_POSTING = "recent_job_posting"
    RECENT_NEWS = "recent_news"
    ACTIVE_SOCIAL_MEDIA = "active_social_media"

    # NEW: Empty content signal
    EMPTY_CONTENT = "empty_content"  # Scrape succeeded but no content returned
```

**Change 2: Detection Function** (After line 200)

```python
def detect_empty_content(
    url: str,
    content: str | None,
    html: str | None
) -> Signal | None:
    """
    Detect when scraping succeeds (HTTP 200) but returns no usable content.

    This indicates one of several scenarios:
    1. Anti-scraping measures (Cloudflare, bot detection)
    2. JavaScript-heavy site that doesn't render server-side
    3. Redirect to error page that returns HTTP 200
    4. Page exists but is intentionally blank
    5. Rate limiting or temporary block

    This is treated as a NEGATIVE signal because:
    - We cannot verify the company is operational
    - May indicate website protection (suggests active company)
    - Requires manual review or alternative scraping method

    Args:
        url: URL that was scraped
        content: Extracted content (markdown or text)
        html: Raw HTML content

    Returns:
        Signal if content is empty, None otherwise
    """

    content_empty = not content or not content.strip()
    html_empty = not html or not html.strip()

    # Both content and HTML are empty
    if content_empty and html_empty:
        return Signal(
            signal_type=DeadWebsiteSignalType.EMPTY_CONTENT,
            confidence=0.7,  # Medium confidence - ambiguous cause
            description=(
                f"Scraping {url} succeeded (HTTP 200) but returned no content. "
                f"This may indicate anti-scraping protection, JavaScript rendering issues, "
                f"or a blank page. Manual review recommended."
            ),
            evidence={
                "url": url,
                "content_length": len(content) if content else 0,
                "html_length": len(html) if html else 0,
                "both_empty": True
            },
            detected_at=datetime.utcnow()
        )

    # Only markdown/text content is empty (have HTML)
    if content_empty and not html_empty:
        return Signal(
            signal_type=DeadWebsiteSignalType.EMPTY_CONTENT,
            confidence=0.5,  # Lower confidence - may be parsing issue
            description=(
                f"Scraping {url} returned HTML but content extraction failed. "
                f"May indicate complex JavaScript rendering or parsing issues."
            ),
            evidence={
                "url": url,
                "content_length": 0,
                "html_length": len(html),
                "markdown_extraction_failed": True
            },
            detected_at=datetime.utcnow()
        )

    # Have content, not empty
    return None
```

**Change 3: Integration into Analyzer** (Around line 300)

```python
def analyze_url_result(
    self,
    url: str,
    url_type: str,
    content: str | None = None,
    html: str | None = None,
    error: Exception | None = None
) -> list[Signal]:
    """
    Analyze URL scrape result for all signal types.

    Runs all detection functions and aggregates signals.
    Detects both negative signals (dead website) and positive signals (operational).

    Args:
        url: URL that was scraped
        url_type: Type of URL (careers, about, news)
        content: Extracted content (markdown or text)
        html: Raw HTML content
        error: Exception if scraping failed

    Returns:
        List of detected signals (may be empty)
    """

    signals = []

    # Handle scraping errors
    if error:
        signals.append(
            Signal(
                signal_type=DeadWebsiteSignalType.HTTP_ERROR,
                confidence=0.9,
                description=f"Failed to scrape {url}: {str(error)}",
                evidence={"url": url, "error": str(error)},
                detected_at=datetime.utcnow()
            )
        )
        return signals

    # NEW: Check for empty content FIRST (before other analysis)
    empty_signal = detect_empty_content(url, content, html)
    if empty_signal:
        signals.append(empty_signal)
        logger.warning(
            "empty_content_detected",
            url=url,
            url_type=url_type
        )

    # Only run content-based detectors if we have content
    if content and content.strip():
        # Detect acquisition indicators
        acquisition_signals = detect_acquisition_indicators(content)
        signals.extend(acquisition_signals)

        # Detect dead website signals
        dead_signals = detect_dead_website_signals(content, html)
        signals.extend(dead_signals)

        # Detect operational signals
        operational_signals = detect_operational_signals(content)
        signals.extend(operational_signals)

        logger.info(
            "signal_detection_complete",
            url=url,
            url_type=url_type,
            total_signals=len(signals),
            signal_types=[s.signal_type for s in signals]
        )
    else:
        logger.warning(
            "skipping_content_analysis",
            url=url,
            url_type=url_type,
            reason="no_content_available"
        )

    return signals
```

### Testing Phase 2 Changes

**Unit Tests** (New file: `tests/unit/test_empty_content_detection.py`):

```python
"""Unit tests for empty content detection."""

import pytest
from datetime import datetime
from valuation_tool.core.dead_website_detection import (
    detect_empty_content,
    DeadWebsiteSignalType
)


def test_detect_empty_content_both_empty():
    """Test detection when both content and HTML are empty."""

    signal = detect_empty_content(
        url="https://example.com",
        content="",
        html=""
    )

    assert signal is not None
    assert signal.signal_type == DeadWebsiteSignalType.EMPTY_CONTENT
    assert signal.confidence == 0.7
    assert "no content" in signal.description.lower()
    assert signal.evidence["both_empty"] is True


def test_detect_empty_content_none_values():
    """Test detection when content is None."""

    signal = detect_empty_content(
        url="https://example.com",
        content=None,
        html=None
    )

    assert signal is not None
    assert signal.signal_type == DeadWebsiteSignalType.EMPTY_CONTENT


def test_detect_empty_content_whitespace_only():
    """Test detection when content is only whitespace."""

    signal = detect_empty_content(
        url="https://example.com",
        content="   \n\t  ",
        html="  "
    )

    assert signal is not None
    assert signal.signal_type == DeadWebsiteSignalType.EMPTY_CONTENT


def test_detect_empty_content_markdown_extraction_failed():
    """Test when HTML exists but markdown extraction failed."""

    signal = detect_empty_content(
        url="https://example.com",
        content="",
        html="<html><body>Some content</body></html>"
    )

    assert signal is not None
    assert signal.confidence == 0.5  # Lower confidence
    assert signal.evidence["markdown_extraction_failed"] is True


def test_detect_empty_content_has_content():
    """Test no signal when content exists."""

    signal = detect_empty_content(
        url="https://example.com",
        content="About our company...",
        html="<html><body>About our company...</body></html>"
    )

    assert signal is None
```

**Integration Tests** (New file: `tests/integration/test_empty_content_detection.py`):

```python
"""Integration tests for empty content detection and database fallback."""

import pytest
from datetime import datetime, timedelta
from valuation_tool.service.batch_processing_service import BatchProcessingService
from valuation_tool.models import Company, URLSnapshot
from valuation_tool.infrastructure.database import get_session


@pytest.fixture
def company_with_empty_current_snapshot(db_session):
    """Create company with empty current snapshot but valid historical snapshot."""

    company = Company(
        name="Test Company",
        url="https://testcompany.com",
        careers_url="https://testcompany.com/careers",
        about_url="https://testcompany.com/about"
    )
    db_session.add(company)
    db_session.commit()

    # Historical snapshot with content (7 days old)
    historical_snapshot = URLSnapshot(
        company_id=company.id,
        url=company.careers_url,
        content="We are hiring! Join our team.",
        html="<html><body>We are hiring!</body></html>",
        scraped_at=datetime.utcnow() - timedelta(days=7),
        scrape_method="firecrawl",
        success=True
    )
    db_session.add(historical_snapshot)

    # Current snapshot with empty content (today)
    current_snapshot = URLSnapshot(
        company_id=company.id,
        url=company.careers_url,
        content="",  # Empty!
        html="",
        scraped_at=datetime.utcnow(),
        scrape_method="firecrawl",
        success=True
    )
    db_session.add(current_snapshot)
    db_session.commit()

    return company


def test_load_content_from_db(company_with_empty_current_snapshot, db_session):
    """Test loading historical content from database."""

    service = BatchProcessingService(session=db_session)
    company = company_with_empty_current_snapshot

    # Load content from database
    content, html = service._load_content_from_db(company, "careers")

    assert content is not None
    assert "We are hiring!" in content
    assert html is not None


def test_scrape_url_adaptive_uses_db_fallback(
    company_with_empty_current_snapshot,
    db_session,
    monkeypatch
):
    """Test that scraping falls back to database when current scrape is empty."""

    # Mock scraper to return empty content
    class MockScraperService:
        def scrape_url(self, url, url_type):
            from valuation_tool.service.adaptive_scraper_service import ScrapeResult
            return ScrapeResult(success=True, content="", html="", method="firecrawl")

    service = BatchProcessingService(session=db_session)
    service.scraper_service = MockScraperService()

    company = company_with_empty_current_snapshot

    # Should use database fallback
    content, html = service._scrape_url_adaptive(
        company, company.careers_url, "careers"
    )

    assert content is not None
    assert "We are hiring!" in content
    assert html is not None


def test_signal_generation_with_empty_content(db_session):
    """Test that empty content generates appropriate signal."""

    from valuation_tool.core.dead_website_detection import DeadWebsiteDetector

    detector = DeadWebsiteDetector()

    # Analyze empty content
    signals = detector.analyze_url_result(
        url="https://example.com/careers",
        url_type="careers",
        content="",
        html="",
        error=None
    )

    # Should have EMPTY_CONTENT signal
    assert len(signals) == 1
    assert signals[0].signal_type == "empty_content"
    assert signals[0].confidence == 0.7


def test_end_to_end_empty_content_handling(
    company_with_empty_current_snapshot,
    db_session,
    monkeypatch
):
    """Test complete flow: empty scrape → DB fallback → signal detection → status."""

    # Mock scraper to return empty content
    class MockScraperService:
        def scrape_url(self, url, url_type):
            from valuation_tool.service.adaptive_scraper_service import ScrapeResult
            return ScrapeResult(success=True, content="", html="", method="firecrawl")

    service = BatchProcessingService(session=db_session)
    service.scraper_service = MockScraperService()

    company = company_with_empty_current_snapshot

    # Process company
    result = service._process_company(company)

    # Should have used database fallback and detected signals
    assert result.signals_detected > 0
    assert company.status != "unknown"
    assert company.signals != "[]"
```

**Manual Verification**:

```bash
# Run tests
pytest tests/unit/test_empty_content_detection.py -v
pytest tests/integration/test_empty_content_detection.py -v

# Process test batch
uv run valuation-tool process --limit 100

# Check signal distribution
sqlite3 ~/.local/share/valuation-tool/companies.db <<EOF
SELECT
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM companies), 2) as percentage
FROM companies
GROUP BY status
ORDER BY count DESC;
EOF

# Check empty content snapshots
sqlite3 ~/.local/share/valuation-tool/companies.db <<EOF
SELECT
  COUNT(*) as total_snapshots,
  SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) as empty_snapshots,
  ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as empty_percentage
FROM url_snapshots;
EOF

# Check companies with signals
sqlite3 ~/.local/share/valuation-tool/companies.db <<EOF
SELECT
  COUNT(*) as total_companies,
  SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) as empty_signals,
  ROUND(SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as empty_percentage
FROM companies;
EOF

# Check EMPTY_CONTENT signals
sqlite3 ~/.local/share/valuation-tool/companies.db <<EOF
SELECT
  name,
  status,
  signals
FROM companies
WHERE signals LIKE '%empty_content%'
LIMIT 10;
EOF
```

### Fixing Phase 2 Tests

**IMPORTANT**: After implementing Phase 2 changes, update existing tests to verify new behavior.

**File 1**: `tests/unit/test_adaptive_scraper_service.py`

**Add tests for empty content validation**:

```python
def test_scrape_with_firecrawl_empty_content_warning():
    """Test that empty content from Firecrawl is logged as warning."""

    service = AdaptiveScraperService(config, db_session, firecrawl_client, playwright_client)

    # Mock Firecrawl to return empty content
    with patch.object(firecrawl_client, 'scrape_url') as mock_scrape:
        mock_scrape.return_value = {
            "success": True,
            "data": {
                "markdown": "",  # Empty!
                "html": "",
            }
        }

        # Capture logs
        with patch('logging.Logger.warning') as mock_warning:
            result = service._scrape_with_firecrawl("https://example.com", capture_screenshot=False)

            # Should log warning about empty content
            assert mock_warning.called
            assert "firecrawl_returned_empty_content" in str(mock_warning.call_args)


def test_scrape_with_firecrawl_empty_markdown_only():
    """Test that empty markdown but present HTML is handled correctly."""

    service = AdaptiveScraperService(config, db_session, firecrawl_client, playwright_client)

    # Mock Firecrawl to return empty markdown but valid HTML
    with patch.object(firecrawl_client, 'scrape_url') as mock_scrape:
        mock_scrape.return_value = {
            "success": True,
            "data": {
                "markdown": "",  # Empty markdown
                "html": "<html><body>Content here</body></html>",  # But HTML exists
            }
        }

        with patch('logging.Logger.warning') as mock_warning:
            result = service._scrape_with_firecrawl("https://example.com", capture_screenshot=False)

            # Should log warning about empty markdown
            assert mock_warning.called
            assert "firecrawl_markdown_empty" in str(mock_warning.call_args)

            # But should still return success with HTML
            assert result.success is True
            assert result.html_content is not None
```

**File 2**: `tests/unit/test_dead_website_detection.py`

**Add tests for EMPTY_CONTENT signal type**:

```python
def test_analyze_url_result_with_empty_content():
    """Test that empty content generates EMPTY_CONTENT signal."""

    from valuation_tool.core.dead_website_detection import analyze_url_result

    signals = analyze_url_result(
        url="https://example.com",
        status_code=200,
        error_message=None,
        final_url="https://example.com",
        content=""  # Empty content despite HTTP 200!
    )

    # Should generate EMPTY_CONTENT signal
    assert len(signals) > 0
    empty_content_signals = [s for s in signals if s.signal_type == "empty_content"]
    assert len(empty_content_signals) == 1
    assert empty_content_signals[0].confidence == 0.7


def test_analyze_url_result_with_none_content():
    """Test that None content generates EMPTY_CONTENT signal."""

    from valuation_tool.core.dead_website_detection import analyze_url_result

    signals = analyze_url_result(
        url="https://example.com",
        status_code=200,
        error_message=None,
        final_url="https://example.com",
        content=None  # None content
    )

    # Should generate EMPTY_CONTENT signal
    empty_content_signals = [s for s in signals if s.signal_type == "empty_content"]
    assert len(empty_content_signals) == 1
```

**File 3**: `tests/unit/test_batch_processing.py`

**Update tests to verify database fallback**:

```python
def test_process_company_uses_db_fallback_on_empty_scrape(
    self, in_memory_db, test_config, sample_companies
):
    """Test that empty scrapes trigger database fallback."""

    session_factory = sessionmaker(bind=in_memory_db.get_bind())
    processor = BatchProcessor(session_factory, test_config)
    company = sample_companies[0]

    # Create historical snapshot with content
    # ... setup code ...

    # Mock scraper to return empty content
    with patch.object(processor, '_scrape_url_adaptive') as mock_scrape:
        from valuation_tool.service.scraping_service import ScrapingResult

        mock_scrape.return_value = ScrapingResult(
            url="https://example.com",
            success=True,
            html_content="",  # Empty!
            markdown_content="",
        )

        result = processor.process_company(company)

        # Should use database fallback (verified via signals or content checks)
        assert result.status == CompanyProcessingStatus.COMPLETED
```

**Verification Checklist**:

- [ ] All new test files created (`test_empty_content_detection.py`, etc.)
- [ ] Existing adaptive scraper tests updated to verify empty content warnings
- [ ] Existing dead website detection tests updated to include EMPTY_CONTENT signal type
- [ ] Batch processing tests updated to verify database fallback behavior
- [ ] All tests are synchronous (no async/await in non-rate-limiter tests)
- [ ] Tests use `session_factory` not `session` when creating BatchProcessor
- [ ] Run full test suite: `pytest tests/unit/ -v`

**Common Pitfalls for Phase 2 Tests**:

1. ❌ **Not testing empty content edge cases**: Test "", None, and whitespace-only content
2. ❌ **Not verifying database fallback**: Mock empty scrapes and verify fallback is used
3. ❌ **Not testing signal generation**: Verify that EMPTY_CONTENT signals are created with correct confidence
4. ❌ **Forgetting to update existing tests**: Existing tests may fail if they expect old behavior
5. ❌ **Not testing warning logs**: Use `patch('logging.Logger.warning')` to verify warnings are logged

**Success Criteria Phase 2**:
- ✓ <10% of companies with status="unknown"
- ✓ <5% of snapshots with empty content (valid edge cases only)
- ✓ >95% of companies have non-empty signals arrays
- ✓ EMPTY_CONTENT signal detected and logged appropriately
- ✓ Database fallback used when current scrape is empty
- ✓ All tests pass

---

## Deployment Plan

### Phase 1 Deployment (Week 1, Days 1-2)

**Objective**: Deploy concurrency removal changes, verify stability.

**Steps**:

1. **Create Feature Branch**
   ```bash
   git checkout -b refactor/remove-concurrency-fix-signals
   ```

2. **Implement Changes**
   - Convert all async code to synchronous
   - Remove asyncio dependencies
   - Simplify database configuration
   - Update configuration

3. **Run Tests**
   ```bash
   # Unit tests
   pytest tests/unit/ -v

   # Integration tests
   pytest tests/integration/ -v

   # Type checking
   mypy src/valuation_tool/

   # Linting
   ruff check src/
   ```

4. **Test Locally**
   ```bash
   # Backup database
   cp ~/.local/share/valuation-tool/companies.db \
      ~/.local/share/valuation-tool/companies.db.backup

   # Process small batch
   uv run valuation-tool process --limit 20

   # Check logs
   tail -f ~/.local/share/valuation-tool/logs/valuation-tool.log

   # Verify no database lock errors
   grep -i "database is locked" ~/.local/share/valuation-tool/logs/valuation-tool.log
   ```

5. **Commit Changes**
   ```bash
   git add -A
   git commit -m "refactor: Remove async/concurrent processing

   - Convert all async/await to synchronous code
   - Simplify database session management
   - Remove concurrency configuration parameters
   - Fix database lock errors

   BREAKING CHANGE: Sequential processing is slower but more reliable"
   ```

**Rollback Procedure**:
```bash
# If Phase 1 causes issues
git revert HEAD
git checkout main
```

**Success Criteria**:
- ✓ Zero "database is locked" errors in logs
- ✓ All tests pass
- ✓ Can process 20+ companies without errors
- ✓ Code is simpler (fewer lines, no async)

### Phase 2 Deployment (Week 1, Days 3-5)

**Objective**: Deploy content detection and signal generation fixes.

**Steps**:

1. **Implement Changes** (On same branch)
   - Add content validation to scraping services
   - Implement database fallback mechanism
   - Add EMPTY_CONTENT signal type
   - Enhance logging throughout

2. **Run Tests**
   ```bash
   # New tests
   pytest tests/unit/test_empty_content_detection.py -v
   pytest tests/integration/test_empty_content_detection.py -v

   # All tests
   pytest tests/ -v

   # Type checking
   mypy src/valuation_tool/
   ```

3. **Test Locally**
   ```bash
   # Process larger batch
   uv run valuation-tool process --limit 100

   # Check status distribution
   uv run valuation-tool stats

   # Check signals
   sqlite3 ~/.local/share/valuation-tool/companies.db \
     "SELECT COUNT(*) FROM companies WHERE signals != '[]';"

   # Review flagged companies
   uv run valuation-tool query by-status requires-review
   ```

4. **Commit Changes**
   ```bash
   git add -A
   git commit -m "feat: Add empty content detection and database fallback

   - Validate content after scraping (detect empty responses)
   - Add database fallback when current scrape is empty
   - Add EMPTY_CONTENT signal type for ambiguous cases
   - Enhance logging for debugging
   - Fix signal detection to use historical content

   Fixes: #1 (content storage), #2 (signal detection)"
   ```

**Rollback Procedure**:
```bash
# Rollback Phase 2 only (keep Phase 1)
git revert HEAD
```

**Success Criteria**:
- ✓ <10% status="unknown"
- ✓ >95% snapshots have content
- ✓ >95% companies have signals
- ✓ Database fallback used appropriately

### Final Deployment (Week 2)

**Objective**: Full end-to-end test and production deployment.

**Steps**:

1. **Full Pipeline Test**
   ```bash
   # Backup database
   cp ~/.local/share/valuation-tool/companies.db \
      ~/.local/share/valuation-tool/companies.db.pre_full_test

   # Optional: Reset database for clean test
   uv run valuation-tool db init --force

   # Process ALL companies (may take 3-4 hours)
   uv run valuation-tool process --force-refresh

   # Monitor progress
   watch -n 60 'uv run valuation-tool stats'
   ```

2. **Verify Results**
   ```bash
   # Status distribution
   uv run valuation-tool stats

   # Check for errors
   sqlite3 ~/.local/share/valuation-tool/companies.db \
     "SELECT error_log FROM processing_runs ORDER BY id DESC LIMIT 1;"

   # Export results
   uv run valuation-tool export --format json --output results.json

   # Validate signal distribution
   sqlite3 ~/.local/share/valuation-tool/companies.db <<EOF
   SELECT
     status,
     COUNT(*) as count,
     ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM companies), 2) as pct
   FROM companies
   GROUP BY status
   ORDER BY count DESC;
   EOF
   ```

3. **Create Pull Request**
   ```bash
   git push -u origin refactor/remove-concurrency-fix-signals

   gh pr create \
     --title "Fix critical data persistence and signal detection bugs" \
     --body "$(cat docs/CRITICAL_BUGS_FIX_PLAN.md)"
   ```

4. **Merge to Main**
   ```bash
   # After PR approval
   git checkout main
   git merge refactor/remove-concurrency-fix-signals
   git push origin main
   ```

**Final Success Criteria**:
- ✓ <10% companies with status="unknown"
- ✓ >50% companies flagged (operational, requires_review, or likely_closed)
- ✓ All status determinations have explanations
- ✓ Zero database errors across 979 companies
- ✓ 50-150 companies require manual review (actual issues)
- ✓ Processing time acceptable (3-4 hours for full dataset)

---

## Verification Procedures

### Automated Verification

**Script**: `scripts/verify_fixes.sh`

```bash
#!/bin/bash
# Verify that critical bugs are fixed

set -e

DB_PATH="$HOME/.local/share/valuation-tool/companies.db"

echo "=== Verification Report ==="
echo

# 1. Check for database lock errors
echo "1. Database Lock Errors:"
LOCK_ERRORS=$(sqlite3 "$DB_PATH" \
  "SELECT COUNT(*) FROM processing_runs WHERE error_log LIKE '%database is locked%';")
if [ "$LOCK_ERRORS" -eq 0 ]; then
  echo "   ✓ PASS: No database lock errors"
else
  echo "   ✗ FAIL: Found $LOCK_ERRORS processing runs with database lock errors"
fi
echo

# 2. Check content storage rate
echo "2. Content Storage Rate:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  'Total Snapshots: ' || COUNT(*) as metric
FROM url_snapshots
UNION ALL
SELECT
  'Empty Content: ' || SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END)
FROM url_snapshots
UNION ALL
SELECT
  'Empty Rate: ' || ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) || '%'
FROM url_snapshots;
EOF

EMPTY_RATE=$(sqlite3 "$DB_PATH" \
  "SELECT ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) FROM url_snapshots;")
if [ "$(echo "$EMPTY_RATE < 10" | bc)" -eq 1 ]; then
  echo "   ✓ PASS: Empty content rate is acceptable (<10%)"
else
  echo "   ✗ FAIL: Empty content rate is too high (>10%)"
fi
echo

# 3. Check signal detection rate
echo "3. Signal Detection Rate:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  'Total Companies: ' || COUNT(*) as metric
FROM companies
UNION ALL
SELECT
  'Empty Signals: ' || SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END)
FROM companies
UNION ALL
SELECT
  'Empty Rate: ' || ROUND(SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) || '%'
FROM companies;
EOF

EMPTY_SIGNALS=$(sqlite3 "$DB_PATH" \
  "SELECT ROUND(SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) FROM companies;")
if [ "$(echo "$EMPTY_SIGNALS < 5" | bc)" -eq 1 ]; then
  echo "   ✓ PASS: Signal detection working (<5% empty)"
else
  echo "   ✗ FAIL: Signal detection not working (>5% empty)"
fi
echo

# 4. Check status distribution
echo "4. Status Distribution:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM companies), 2) as pct
FROM companies
GROUP BY status
ORDER BY count DESC;
EOF

UNKNOWN_RATE=$(sqlite3 "$DB_PATH" \
  "SELECT ROUND(SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) FROM companies;")
if [ "$(echo "$UNKNOWN_RATE < 10" | bc)" -eq 1 ]; then
  echo "   ✓ PASS: Status determination working (<10% unknown)"
else
  echo "   ✗ FAIL: Status determination not working (>10% unknown)"
fi
echo

# 5. Check for EMPTY_CONTENT signals
echo "5. Empty Content Detection:"
EMPTY_CONTENT_SIGNALS=$(sqlite3 "$DB_PATH" \
  "SELECT COUNT(*) FROM companies WHERE signals LIKE '%empty_content%';")
echo "   Companies with EMPTY_CONTENT signal: $EMPTY_CONTENT_SIGNALS"
if [ "$EMPTY_CONTENT_SIGNALS" -gt 0 ]; then
  echo "   ✓ PASS: Empty content detection is working"
else
  echo "   ℹ INFO: No empty content detected (may be expected)"
fi
echo

# Overall summary
echo "=== Overall Status ==="
if [ "$LOCK_ERRORS" -eq 0 ] && \
   [ "$(echo "$EMPTY_RATE < 10" | bc)" -eq 1 ] && \
   [ "$(echo "$EMPTY_SIGNALS < 5" | bc)" -eq 1 ] && \
   [ "$(echo "$UNKNOWN_RATE < 10" | bc)" -eq 1 ]; then
  echo "✓ ALL CHECKS PASSED - Fixes are working correctly"
  exit 0
else
  echo "✗ SOME CHECKS FAILED - Review output above"
  exit 1
fi
```

**Usage**:
```bash
chmod +x scripts/verify_fixes.sh
./scripts/verify_fixes.sh
```

### Manual Verification Checklist

After deployment, manually verify:

- [ ] **Database Locks**: No "database is locked" errors in logs
- [ ] **Content Storage**: <10% of snapshots have empty content
- [ ] **Signal Detection**: <5% of companies have empty signals arrays
- [ ] **Status Distribution**: <10% of companies have status="unknown"
- [ ] **Flagged Companies**: 50-150 companies require manual review
- [ ] **EMPTY_CONTENT Signals**: Some companies have this signal (indicates detection working)
- [ ] **Processing Reliability**: Can process 100+ companies without crashes
- [ ] **Log Quality**: Logs show clear flow (scrape → fallback → signals → status)
- [ ] **Database Integrity**: No corruption, all foreign keys valid
- [ ] **Performance**: Processing time acceptable (10-30 min for 100 companies)

### SQL Queries for Verification

```sql
-- 1. Database lock errors
SELECT COUNT(*) FROM processing_runs
WHERE error_log LIKE '%database is locked%';
-- Expected: 0

-- 2. Empty content rate
SELECT
  COUNT(*) as total_snapshots,
  SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) as empty,
  ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as empty_pct
FROM url_snapshots;
-- Expected: empty_pct < 10%

-- 3. Signal detection rate
SELECT
  COUNT(*) as total_companies,
  SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) as empty_signals,
  ROUND(SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as empty_pct
FROM companies;
-- Expected: empty_pct < 5%

-- 4. Status distribution
SELECT
  status,
  COUNT(*) as count,
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM companies), 2) as pct
FROM companies
GROUP BY status
ORDER BY count DESC;
-- Expected: unknown < 10%

-- 5. Companies with EMPTY_CONTENT signal
SELECT
  name,
  status,
  signals
FROM companies
WHERE signals LIKE '%empty_content%';
-- Expected: Some companies (indicates detection working)

-- 6. Database fallback usage (from logs)
SELECT
  COUNT(*) as companies_using_db_fallback
FROM companies
WHERE last_processed_at IS NOT NULL;
-- Check logs for "using_db_fallback_content" entries

-- 7. Recent processing runs
SELECT
  id,
  started_at,
  completed_at,
  companies_processed,
  errors_count,
  SUBSTR(error_log, 1, 100) as error_preview
FROM processing_runs
ORDER BY id DESC
LIMIT 5;
-- Expected: errors_count = 0, no error_log

-- 8. Companies requiring review
SELECT
  status,
  COUNT(*) as count
FROM companies
WHERE status IN ('requires_review', 'likely_closed')
GROUP BY status;
-- Expected: 50-150 total

-- 9. Sample of operational companies with signals
SELECT
  name,
  status,
  confidence_score,
  JSON_EXTRACT(signals, '$[0].signal_type') as first_signal
FROM companies
WHERE status = 'operational'
  AND signals != '[]'
LIMIT 10;
-- Expected: Various signal types, confidence > 0.5

-- 10. Sample of flagged companies with explanations
SELECT
  name,
  status,
  explanation,
  JSON_EXTRACT(signals, '$[0].description') as signal_desc
FROM companies
WHERE status IN ('requires_review', 'likely_closed')
LIMIT 10;
-- Expected: Clear explanations and signal descriptions
```

---

## Rollback Procedures

### Phase 1 Rollback (Remove Concurrency)

**When to Rollback**:
- Database lock errors persist
- Critical functionality breaks
- Tests fail unexpectedly

**Rollback Steps**:

```bash
# 1. Revert commit
git revert HEAD

# 2. Test reverted version
pytest tests/ -v
uv run valuation-tool process --limit 10

# 3. If stable, push revert
git push origin refactor/remove-concurrency-fix-signals

# 4. Investigate issue offline
git checkout -b debug/phase1-issues
```

**Impact**: Return to async/concurrent implementation with database lock errors.

### Phase 2 Rollback (Content/Signal Detection)

**When to Rollback**:
- False positive rate too high (>50% of flagged companies are operational)
- Empty content detection causes issues
- Database fallback performs poorly

**Rollback Steps**:

```bash
# 1. Revert Phase 2 commit only (keep Phase 1)
git revert HEAD

# 2. Test without Phase 2 changes
pytest tests/ -v
uv run valuation-tool process --limit 50

# 3. Verify Phase 1 still working
grep -i "database is locked" ~/.local/share/valuation-tool/logs/valuation-tool.log
# Should be empty

# 4. Push revert
git push origin refactor/remove-concurrency-fix-signals
```

**Impact**: Keep sequential processing (Phase 1) but return to broken signal detection.

### Full Rollback (Both Phases)

**When to Rollback**:
- Critical production issue
- Data corruption detected
- Unable to process any companies

**Rollback Steps**:

```bash
# 1. Revert branch completely
git checkout main
git branch -D refactor/remove-concurrency-fix-signals

# 2. Restore database from backup
cp ~/.local/share/valuation-tool/companies.db.backup \
   ~/.local/share/valuation-tool/companies.db

# 3. Verify system stable
uv run valuation-tool stats
uv run valuation-tool process --limit 5

# 4. Investigate offline
git checkout -b debug/critical-issue
```

**Impact**: Return to original broken state (async errors, empty signals).

### Emergency Procedures

**Database Corruption**:
```bash
# Restore from backup
cp ~/.local/share/valuation-tool/companies.db.backup \
   ~/.local/share/valuation-tool/companies.db

# Verify integrity
sqlite3 ~/.local/share/valuation-tool/companies.db "PRAGMA integrity_check;"

# If corrupted beyond repair, reinitialize
uv run valuation-tool db init --force
```

**Infinite Loop/Hang**:
```bash
# Kill process
pkill -f "valuation-tool process"

# Check logs
tail -n 100 ~/.local/share/valuation-tool/logs/valuation-tool.log

# Identify stuck company
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT name FROM companies ORDER BY last_processed_at DESC LIMIT 1;"
```

**Out of Disk Space**:
```bash
# Check database size
du -h ~/.local/share/valuation-tool/companies.db

# Vacuum database
sqlite3 ~/.local/share/valuation-tool/companies.db "VACUUM;"

# Clear old snapshots (keep last 7 days)
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "DELETE FROM url_snapshots WHERE scraped_at < datetime('now', '-7 days');"
```

---

## Performance Analysis

### Processing Time Comparison

**Assumptions**:
- 979 total companies
- ~3 URLs per company (careers, about, news)
- ~5 seconds per URL (Firecrawl API latency)
- 20 companies per Firecrawl batch

**Current (Async/Concurrent) - FAILS**:
- Theoretical: ~8-10 minutes
- Actual: Fails with database lock errors
- **Status**: Non-functional

**After Phase 1 (Sequential) - WORKS**:
- Per URL: ~5 seconds
- Per company: ~15 seconds (3 URLs)
- Per batch (20 companies): ~300 seconds (5 minutes)
- Total (979 companies): ~49 batches × 5 min = **~245 minutes (4 hours)**
- **Status**: Functional, acceptable

**Bottleneck Analysis**:

| Component | Time (ms) | % of Total |
|-----------|-----------|-----------|
| Firecrawl API | 4500-5000 | 90% |
| Playwright | 1000-2000 | 5% |
| Database write | 10-50 | 1% |
| Signal detection | 100-200 | 2% |
| Other | 50-100 | 2% |

**Conclusion**: Network I/O (Firecrawl API) is 90% of processing time. Concurrency doesn't help because:
1. Firecrawl batches are already optimized (20 companies at once)
2. Rate limits prevent faster scraping
3. Database writes are negligible (<1% of time)
4. Sequential is simpler and more reliable

### Throughput Comparison

**Metrics**:

| Metric | Current (Async) | Phase 1 (Sequential) | Phase 2 (Full Fix) |
|--------|----------------|---------------------|-------------------|
| **Companies/hour** | 0 (fails) | ~15 | ~15 |
| **Successful scrapes** | ~44% | ~44% | >95% (with fallback) |
| **Status detection** | 0% | 0% | >90% |
| **Database locks** | ~30% runs | 0% | 0% |
| **Reliability** | 10% | 95% | 98% |

**Key Improvements**:
- ✓ Reliability: 10% → 98% (+88 percentage points)
- ✓ Status detection: 0% → 90% (+90 percentage points)
- ✓ Content usage: 44% → 95% (+51 percentage points via fallback)
- ⚠ Speed: N/A → 4 hours (acceptable for batch job)

### Resource Usage

**Current (Async)**:
- Memory: ~200-300 MB (multiple coroutines)
- CPU: 10-20% (context switching overhead)
- Database connections: 1 (shared, causes locks)
- Complexity: High (async code, session management)

**After Phase 1 (Sequential)**:
- Memory: ~150-200 MB (single execution path)
- CPU: 5-10% (mostly waiting for network)
- Database connections: 1 (exclusive access)
- Complexity: Low (simple for loop)

**After Phase 2 (Full Fix)**:
- Memory: ~200-250 MB (loading DB snapshots)
- CPU: 5-10%
- Database connections: 1
- Complexity: Low-Medium (fallback logic adds some complexity)

### Scalability Analysis

**Current Dataset (979 companies)**:
- Processing time: ~4 hours
- Acceptable: ✓ YES (batch job)

**Future Growth (5000 companies)**:
- Processing time: ~20 hours
- Acceptable: ✓ YES (overnight batch)

**Optimization Options (if needed later)**:
1. **Distributed Processing**: Multiple machines, each with own SQLite DB
2. **Smarter Batching**: Process high-priority companies first
3. **Incremental Updates**: Only refresh stale content (>30 days old)
4. **PostgreSQL Migration**: Better concurrency support (only if >10k companies)

**Recommendation**: Current sequential approach is sufficient for foreseeable future. Don't optimize prematurely.

---

## Post-Deployment Monitoring

### Key Metrics to Track

**Daily Monitoring**:
```bash
# 1. Processing success rate
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     COUNT(*) as total_runs,
     SUM(CASE WHEN errors_count = 0 THEN 1 ELSE 0 END) as successful_runs,
     ROUND(SUM(CASE WHEN errors_count = 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as success_rate
   FROM processing_runs
   WHERE started_at > datetime('now', '-7 days');"
# Target: >95% success rate

# 2. Status distribution trend
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     status,
     COUNT(*) as count
   FROM companies
   GROUP BY status
   ORDER BY count DESC;"
# Target: unknown <10%, flagged 50-150

# 3. Empty content rate
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) as empty_pct
   FROM url_snapshots
   WHERE scraped_at > datetime('now', '-7 days');"
# Target: <10%

# 4. Database size
du -h ~/.local/share/valuation-tool/companies.db
# Alert if >1GB (may need cleanup)
```

**Weekly Analysis**:
```bash
# 1. Signal type distribution
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     REPLACE(REPLACE(signal_type, '\"', ''), '[{', '') as signal_type,
     COUNT(*) as count
   FROM (
     SELECT json_each.value as signal_type
     FROM companies, json_each(companies.signals)
   )
   GROUP BY signal_type
   ORDER BY count DESC;"

# 2. False positive analysis (manual review sample)
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT name, url, status, explanation
   FROM companies
   WHERE status = 'requires_review'
   ORDER BY RANDOM()
   LIMIT 10;" | less
# Manually verify if flags are accurate

# 3. Performance trends
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     DATE(started_at) as date,
     AVG((julianday(completed_at) - julianday(started_at)) * 24 * 60) as avg_duration_minutes,
     AVG(companies_processed) as avg_companies
   FROM processing_runs
   WHERE started_at > datetime('now', '-30 days')
     AND completed_at IS NOT NULL
   GROUP BY DATE(started_at)
   ORDER BY date DESC;"
# Check for performance degradation over time
```

### Alert Conditions

**Critical Alerts** (immediate action required):
- Database lock errors detected (shouldn't happen after fix)
- Processing success rate <80%
- >50% of companies status="unknown"
- Database corruption detected

**Warning Alerts** (investigate within 24 hours):
- Processing success rate <95%
- Empty content rate >20%
- >20% of companies status="unknown"
- Processing time >6 hours for 1000 companies

**Info Alerts** (review during weekly analysis):
- False positive rate appears high (>30% based on samples)
- Unusual signal distribution (all one type)
- Database size >500MB

### Log Monitoring

**Critical Log Patterns** (should never appear):
```bash
# Database locks
grep -i "database is locked" ~/.local/share/valuation-tool/logs/valuation-tool.log

# Async errors (shouldn't exist after Phase 1)
grep -i "CancelledError\|async\|await" ~/.local/share/valuation-tool/logs/valuation-tool.log

# Uncaught exceptions
grep -i "Traceback\|Exception" ~/.local/share/valuation-tool/logs/valuation-tool.log
```

**Warning Log Patterns** (investigate if frequent):
```bash
# Empty content warnings (some expected, but not all)
grep "firecrawl_returned_empty_content\|playwright_returned_empty_content" \
  ~/.local/share/valuation-tool/logs/valuation-tool.log | wc -l

# Database fallback usage (indicates scraping issues)
grep "using_db_fallback_content" \
  ~/.local/share/valuation-tool/logs/valuation-tool.log | wc -l

# No historical content (may indicate new companies or persistent empty scrapes)
grep "no_historical_content" \
  ~/.local/share/valuation-tool/logs/valuation-tool.log | wc -l
```

**Info Log Patterns** (normal operation):
```bash
# Successful signal detection
grep "signals_detected" ~/.local/share/valuation-tool/logs/valuation-tool.log | tail -20

# Status updates
grep "status_updated" ~/.local/share/valuation-tool/logs/valuation-tool.log | tail -20
```

### Health Check Dashboard

**Create simple health check script**: `scripts/health_check.sh`

```bash
#!/bin/bash
# Daily health check for valuation tool

DB_PATH="$HOME/.local/share/valuation-tool/companies.db"
LOG_PATH="$HOME/.local/share/valuation-tool/logs/valuation-tool.log"

echo "=== Valuation Tool Health Check ==="
echo "Date: $(date)"
echo

# 1. Database health
echo "1. Database Health:"
sqlite3 "$DB_PATH" "PRAGMA integrity_check;" | head -1
echo "   Size: $(du -h "$DB_PATH" | cut -f1)"
echo

# 2. Recent processing
echo "2. Recent Processing:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  'Last run: ' || MAX(started_at),
  'Companies processed: ' || companies_processed,
  'Errors: ' || errors_count
FROM processing_runs;
EOF
echo

# 3. Status distribution
echo "3. Status Distribution:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  status || ': ' || COUNT(*) || ' (' ||
  ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM companies), 1) || '%)'
FROM companies
GROUP BY status
ORDER BY COUNT(*) DESC;
EOF
echo

# 4. Critical errors (last 24 hours)
echo "4. Critical Errors (last 24 hours):"
CRITICAL_ERRORS=$(grep -i "database is locked\|CancelledError" "$LOG_PATH" | wc -l)
if [ "$CRITICAL_ERRORS" -eq 0 ]; then
  echo "   ✓ No critical errors"
else
  echo "   ✗ $CRITICAL_ERRORS critical errors found"
fi
echo

# 5. Content quality
echo "5. Content Quality:"
sqlite3 "$DB_PATH" <<EOF
SELECT
  'Total snapshots: ' || COUNT(*),
  'Empty: ' || SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) ||
  ' (' || ROUND(SUM(CASE WHEN content IS NULL OR content = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) || '%)'
FROM url_snapshots;
EOF
echo

echo "=== End Health Check ==="
```

**Usage**:
```bash
chmod +x scripts/health_check.sh

# Run manually
./scripts/health_check.sh

# Or schedule daily via cron
crontab -e
# Add: 0 9 * * * /path/to/scripts/health_check.sh | mail -s "Valuation Tool Health" your@email.com
```

---

## Success Metrics Summary

### Immediate Success (Post-Phase 1)

**Target**: Sequential processing is stable and reliable

- ✓ Zero "database is locked" errors
- ✓ Zero async/await related errors
- ✓ Can process 20+ companies without failures
- ✓ All existing tests pass
- ✓ Code is simpler (fewer lines, no async complexity)

**Measurement**:
```bash
# Database lock errors
grep -i "database is locked" ~/.local/share/valuation-tool/logs/valuation-tool.log | wc -l
# Expected: 0

# Successful processing
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT errors_count FROM processing_runs ORDER BY id DESC LIMIT 1;"
# Expected: 0
```

### Immediate Success (Post-Phase 2)

**Target**: Content detection and signal generation work correctly

- ✓ <10% of companies with status="unknown"
- ✓ <5% of snapshots with empty content
- ✓ >95% of companies have non-empty signals arrays
- ✓ EMPTY_CONTENT signal detected appropriately
- ✓ Database fallback used when needed

**Measurement**:
```bash
# Status distribution
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     ROUND(SUM(CASE WHEN status = 'unknown' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
   FROM companies;"
# Expected: <10%

# Signal detection
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT
     ROUND(SUM(CASE WHEN signals = '[]' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2)
   FROM companies;"
# Expected: <5%
```

### Short-Term Success (1 Week)

**Target**: Process full dataset reliably

- ✓ Process all 979 companies without failures (time irrelevant, 3-4 hours OK)
- ✓ 50-150 companies flagged for review (based on actual issues)
- ✓ Status distribution: operational/requires_review/likely_closed (not all "unknown")
- ✓ Confidence scores >0.7 for flagged companies
- ✓ Zero data loss or corruption incidents

**Measurement**:
```bash
# Full processing success
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT companies_processed, errors_count
   FROM processing_runs
   ORDER BY id DESC LIMIT 1;"
# Expected: companies_processed=979, errors_count=0

# Flagged companies
sqlite3 ~/.local/share/valuation-tool/companies.db \
  "SELECT COUNT(*) FROM companies
   WHERE status IN ('requires_review', 'likely_closed');"
# Expected: 50-150
```

### Long-Term Success (1 Month)

**Target**: Reliable production operation

- ✓ Can reliably process 50-500 companies (batch sizes)
- ✓ Accurate status detection (validated by manual review)
- ✓ <1% false positive rate for "requires_review"
- ✓ Zero critical bugs or production incidents
- ✓ Easy to debug and maintain (simple synchronous code)

**Measurement**:
- Manual review of 20 random "requires_review" companies
- Track false positives (operational companies incorrectly flagged)
- Monitor processing run error rates
- Code review feedback (maintainability)

---

## Appendix: Technical Reference

### Database Schema (Relevant Tables)

```sql
-- Companies table
CREATE TABLE companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    careers_url TEXT,
    about_url TEXT,
    news_url TEXT,
    status TEXT DEFAULT 'unknown',  -- unknown, operational, requires_review, likely_closed
    confidence_score REAL,
    signals TEXT DEFAULT '[]',  -- JSON array of Signal objects
    explanation TEXT,
    last_processed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- URL snapshots table
CREATE TABLE url_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    url TEXT NOT NULL,
    content TEXT,  -- Markdown/text content (may be NULL/empty)
    html TEXT,  -- Raw HTML (may be NULL/empty)
    scraped_at TIMESTAMP NOT NULL,
    scrape_method TEXT,  -- firecrawl, playwright
    success BOOLEAN NOT NULL,
    error_message TEXT,
    FOREIGN KEY (company_id) REFERENCES companies (id) ON DELETE CASCADE
);

-- Processing runs table
CREATE TABLE processing_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    companies_processed INTEGER DEFAULT 0,
    errors_count INTEGER DEFAULT 0,
    error_log TEXT,  -- JSON array of errors
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_url_snapshots_company_url ON url_snapshots(company_id, url);
CREATE INDEX idx_url_snapshots_scraped_at ON url_snapshots(scraped_at DESC);
CREATE INDEX idx_companies_status ON companies(status);
CREATE INDEX idx_companies_last_processed ON companies(last_processed_at DESC);
```

### Signal Structure

```python
@dataclass
class Signal:
    """Represents a detected signal about company status."""

    signal_type: DeadWebsiteSignalType
    confidence: float  # 0.0-1.0
    description: str
    evidence: dict[str, Any]
    detected_at: datetime
```

**Example Signals**:

```json
{
  "signal_type": "acquisition_notice",
  "confidence": 0.95,
  "description": "Found acquisition notice on careers page mentioning Acme Corp",
  "evidence": {
    "url": "https://example.com/careers",
    "matched_text": "We have been acquired by Acme Corp...",
    "acquiring_company": "Acme Corp"
  },
  "detected_at": "2026-01-30T10:15:30Z"
}
```

```json
{
  "signal_type": "empty_content",
  "confidence": 0.7,
  "description": "Scraping https://example.com/careers succeeded but returned no content",
  "evidence": {
    "url": "https://example.com/careers",
    "content_length": 0,
    "html_length": 0,
    "both_empty": true
  },
  "detected_at": "2026-01-30T10:15:30Z"
}
```

### Configuration Reference

**Relevant Settings** (`config.py`):

```python
class Config(BaseSettings):
    # Processing
    batch_size: int = 20  # Number of companies per Firecrawl batch
    # concurrency: int = 5  # REMOVED in Phase 1

    # Scraping
    firecrawl_api_key: str
    scrape_timeout: int = 30  # seconds
    max_retries: int = 3

    # Database
    database_url: str = "sqlite:///~/.local/share/valuation-tool/companies.db"
    database_pool_size: int = 1  # StaticPool (single connection)

    # Signal detection
    confidence_threshold: float = 0.7  # Minimum confidence for status determination
    empty_content_confidence: float = 0.7  # Confidence for EMPTY_CONTENT signal

    # Logging
    log_level: str = "INFO"
    log_file: str = "~/.local/share/valuation-tool/logs/valuation-tool.log"
```

### Logging Standards

**Structured Logging Format** (using `structlog`):

```python
import structlog

logger = structlog.get_logger()

# Good logging examples
logger.info(
    "scraping_url",
    company=company.name,
    url=url,
    url_type=url_type
)

logger.warning(
    "empty_scrape_result",
    company=company.name,
    url=url,
    url_type=url_type,
    method=result.method
)

logger.error(
    "scrape_failed",
    company=company.name,
    url=url,
    error=str(error),
    traceback=traceback.format_exc()
)

# Context binding for entire operation
logger = logger.bind(company=company.name, batch_id=batch_id)
logger.info("starting_processing")
# ... operations ...
logger.info("processing_complete", signals_detected=len(signals))
```

**Log Levels**:
- **DEBUG**: Detailed diagnostic information (disabled by default)
- **INFO**: Normal operation milestones (scraping, signal detection, status updates)
- **WARNING**: Unexpected but recoverable situations (empty content, fallback usage)
- **ERROR**: Failures requiring attention (scraping errors, database errors)
- **CRITICAL**: System-level failures (shouldn't occur after fixes)

### CLI Commands Reference

```bash
# Initialize/reset database
uv run valuation-tool db init [--force]

# Process companies
uv run valuation-tool process [--limit N] [--force-refresh] [--company-name NAME]

# Query companies
uv run valuation-tool query all
uv run valuation-tool query by-status <status>
uv run valuation-tool query flagged

# Statistics
uv run valuation-tool stats

# Export results
uv run valuation-tool export --format json --output results.json

# View logs
tail -f ~/.local/share/valuation-tool/logs/valuation-tool.log
```

---

## Glossary

**Acquisition Signal**: Indicator that a company has been acquired (e.g., "acquired by", "now part of")

**Adaptive Scraping**: Strategy that tries Firecrawl first, falls back to Playwright if needed

**Batch Processing**: Processing multiple companies in a single operation (default: 20 at a time)

**Confidence Score**: 0.0-1.0 value indicating certainty of status determination

**Content Storage Failure**: Bug where HTTP 200 responses stored NULL/empty content in database

**Database Fallback**: Loading historical content from database when current scrape is empty

**Dead Website Signal**: Negative indicator suggesting company may be inactive (e.g., 404, expired domain)

**Empty Content**: HTTP 200 response with no usable content (may indicate anti-scraping measures)

**Firecrawl**: Primary scraping service (API-based, converts HTML to markdown)

**Operational Signal**: Positive indicator that company is active (e.g., recent job posting, news)

**Playwright**: Backup scraping service (browser automation, handles JavaScript)

**Sequential Processing**: Processing companies one at a time (vs concurrent/parallel)

**Signal**: Detected indicator about company status (positive or negative)

**Signal Detection Failure**: Bug where all companies have empty signals arrays and "unknown" status

**StaticPool**: SQLite connection pool that uses single connection (perfect for sequential processing)

**Status**: Company classification (unknown, operational, requires_review, likely_closed)

**URL Snapshot**: Stored copy of scraped content with timestamp and metadata

**Triage Approach**: Strategy where ANY negative signal triggers manual review (conservative)

---

## Document History

| Version | Date | Changes | Author |
|---------|------|---------|--------|
| 1.0 | 2026-01-30 | Initial plan created | Claude |
| 1.1 | 2026-01-30 | Added comprehensive test fixing instructions for Phase 1 and Phase 2. Added critical warning about test updates in Executive Summary. Documented all required test changes with examples and common pitfalls. | Claude |

---

**END OF IMPLEMENTATION PLAN**
