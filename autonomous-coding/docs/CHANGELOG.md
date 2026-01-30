# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Critical: Session Concurrency Issue** - Fixed `UNIQUE constraint failed: website_snapshots.id` error during concurrent URL processing
  - Implemented session-per-operation pattern using session factories instead of shared sessions
  - Each concurrent operation now gets its own isolated database session
  - Prevents race conditions and transaction conflicts during parallel URL scraping
  - See `SESSION_CONCURRENCY_FIX.md` for detailed technical explanation
  - Modified files:
    - `src/valuation_tool/service/batch_processing_service.py`
    - `src/valuation_tool/cli.py`

- **Critical: Playwright Threading Error** - Fixed `Cannot switch to a different thread` greenlet error
  - Converted PlaywrightClient from sync_api to async_api
  - Async API is thread-safe and works properly with concurrent asyncio operations
  - LinkedIn and Twitter/X URLs now scrape successfully with Playwright
  - See `BUGFIX_SUMMARY.md` for details
  - Modified files:
    - `src/valuation_tool/infrastructure/playwright_client.py`
    - `src/valuation_tool/service/adaptive_scraper_service.py`
    - `src/valuation_tool/service/batch_processing_service.py`

- **Bug: Wrong Attribute Names** - Fixed AttributeError in status determination
  - Changed `aggregated.status` → `aggregated.final_status`
  - Changed `aggregated.signals` → `aggregated.all_signals`
  - Changed `aggregated.confidence` → `aggregated.overall_confidence`
  - Modified files:
    - `src/valuation_tool/service/status_determination_service.py`

- **Bug: Wrong Batch Statistics Field** - Fixed AttributeError in CLI display
  - Changed `batch_stats.companies_processed` → `batch_stats.processed`
  - Modified files:
    - `src/valuation_tool/cli.py`

- **Bug: Wrong Function Name** - Fixed `module has no attribute 'are_checksums_equal'` error
  - Changed function call from `are_checksums_equal()` → `checksums_match()`
  - This was causing scraping failures when storing website snapshots
  - Modified files:
    - `src/valuation_tool/service/adaptive_scraper_service.py`

- **Critical: Database Lock Errors** - Added automatic retry logic for SQLite lock contention
  - Implemented exponential backoff retry mechanism for database operations
  - Handles transient "database is locked" errors during high concurrency
  - Automatically retries commit/flush operations up to 5 times with increasing delays
  - **Enhanced:** Added explicit `session.rollback()` before retry to clear SQLAlchemy's internal error state
  - Prevents `PendingRollbackError` cascading failures after successful retry
  - Created new utility module `core/db_retry.py` with retry decorators and context managers
  - Modified files:
    - `src/valuation_tool/core/db_retry.py` (new file)
    - `src/valuation_tool/service/batch_processing_service.py`
    - `src/valuation_tool/service/adaptive_scraper_service.py`
    - `src/valuation_tool/service/status_determination_service.py`

- **Critical: Timezone-Aware DateTime Comparisons** - Fixed "can't compare offset-naive and offset-aware datetimes" error
  - Changed all `datetime.now()` calls to `datetime.now(UTC)` for consistent timezone handling
  - Added timezone-aware handling in `filter_recently_processed()` for database datetime comparisons
  - Ensures all datetimes are timezone-aware (UTC) throughout the application
  - Modified files:
    - `src/valuation_tool/service/batch_processing_service.py`
    - `src/valuation_tool/core/news_search.py`
    - `src/valuation_tool/core/operational_signals_detection.py`
    - `src/valuation_tool/core/staleness_detection.py`
    - `src/valuation_tool/core/error_reporting.py`
    - `src/valuation_tool/infrastructure/rate_limiter.py`

## [0.1.0] - 2026-01-25

### Added
- Initial implementation of valuation tool
- Airtable import functionality
- Batch processing service
- Adaptive scraper service with Firecrawl and Playwright support
- Status determination system
- Dead website detection
- Acquisition detection
- Staleness detection
- News search and keyword analysis
- CLI interface with process, query, and export commands
