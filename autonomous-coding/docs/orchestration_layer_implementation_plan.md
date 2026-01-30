# Implementation Plan: Orchestration Layer for Batch Processing

## Executive Summary

Replace the placeholder implementation in `BatchProcessor.process_company()` (lines 272-327) with a complete orchestration pipeline that scrapes URLs, runs detection systems, aggregates signals, and persists status determinations.

**Location:** `/Users/Lily/saxdev/valuations_autonomous_agent/autonomous-coding/generations/autonomous_demo_project/src/valuation_tool/service/batch_processing_service.py`

**Impact:** Enables actual web scraping and company analysis (currently just returns fake results after 0.1s sleep)

---

## Problem Statement

The `process_company` method currently contains:
```python
# TODO: Implement actual scraping and detection
# For now, return a placeholder result
await asyncio.sleep(0.1)
return CompanyProcessingResult(status=COMPLETED)  # Fake result
```

All the required services are fully implemented but not connected:
- ✅ AdaptiveScraperService - intelligent Firecrawl/Playwright selection
- ✅ Dead website, acquisition, staleness, operational detection systems
- ✅ News search and keyword analysis
- ✅ Signal aggregation and status determination
- ❌ Orchestration layer to connect them all

---

## Solution Architecture

### High-Level Flow

```
Company → Fetch URLs → Scrape Concurrently → Run Detections in Parallel → Aggregate Signals → Persist Status
```

### Key Design Decisions

1. **Service Initialization:** Add clients to `__init__()` for reuse across companies
2. **Async/Sync Bridge:** Use `asyncio.to_thread()` for synchronous detection functions
3. **URL Processing:** Concurrent scraping with error isolation
4. **Detection:** Run all 6 detection systems in parallel using thread pool
5. **Error Handling:** Continue processing if individual URLs fail; only fail if ALL URLs fail

---

## Implementation Steps

### Step 1: Add Service Initialization to `__init__`

**File:** `batch_processing_service.py` lines ~195-210

**Add after existing initialization:**
```python
# Initialize scraping clients (reused across all companies)
self.firecrawl_client = FirecrawlClient(
    api_keys=config.api_keys,
    scraper_config=config.scraper
)
self.playwright_client = PlaywrightClient(
    config=config.playwright,
    ocr_config=config.ocr
)
self.adaptive_scraper = AdaptiveScraperService(
    config=config,
    db_session=session,
    firecrawl_client=self.firecrawl_client,
    playwright_client=self.playwright_client
)
```

**Why:** Instantiate once per BatchProcessor instead of per company for efficiency.

---

### Step 2: Add Required Imports

**File:** `batch_processing_service.py` top of file

**Add imports:**
```python
import asyncio
import logging
from valuation_tool.infrastructure.database import CompanyURL, URL
from valuation_tool.infrastructure.firecrawl_client import FirecrawlClient
from valuation_tool.infrastructure.playwright_client import PlaywrightClient
from valuation_tool.service.adaptive_scraper_service import AdaptiveScraperService, ScrapingResult
from valuation_tool.service.status_determination_service import determine_and_persist_status
from valuation_tool.core.dead_website_detection import DeadWebsiteAnalysis
from valuation_tool.core.acquisition_detection import AcquisitionAnalysis
from valuation_tool.core.staleness_detection import StalenessAnalysis
from valuation_tool.core.operational_signals_detection import OperationalAnalysis
from valuation_tool.core.keyword_detector import KeywordAnalysisResult

logger = logging.getLogger(__name__)
```

---

### Step 3: Replace `process_company` Method

**File:** `batch_processing_service.py` lines 272-327

**Replace entire method with:**

```python
async def process_company(
    self,
    company: Company,
) -> CompanyProcessingResult:
    """Process a single company through the complete pipeline.

    Pipeline:
    1. Fetch all company URLs from database
    2. Scrape URLs concurrently with adaptive scraper selection
    3. Run detection systems in parallel
    4. Search and analyze news (if business_description exists)
    5. Process OCR text from screenshots
    6. Aggregate all signals and determine status
    7. Persist to database

    Args:
        company: Company to process

    Returns:
        CompanyProcessingResult with status determination
    """
    start_time = datetime.now(UTC)

    try:
        async with self.concurrent_throttler.throttle():
            # STEP 1: Fetch all URLs for this company
            company_urls = (
                self.session.query(URL)
                .join(CompanyURL)
                .filter(CompanyURL.company_id == company.id)
                .filter(URL.is_active == True)
                .all()
            )

            # Handle edge case: no URLs
            if not company_urls:
                return CompanyProcessingResult(
                    company_id=company.id,
                    company_name=company.name,
                    status=CompanyProcessingStatus.SKIPPED,
                    skipped_reason="No active URLs found",
                    processing_time=(datetime.now(UTC) - start_time).total_seconds()
                )

            # STEP 2: Scrape all URLs concurrently
            scraping_tasks = [
                self._scrape_url_adaptive(url) for url in company_urls
            ]

            scraping_results = await asyncio.gather(
                *scraping_tasks,
                return_exceptions=True
            )

            # Filter successful results
            successful_scrapes = []
            for idx, result in enumerate(scraping_results):
                if isinstance(result, Exception):
                    logger.error(
                        "Scraping failed for company='%s' url='%s': %s",
                        company.name,
                        company_urls[idx].url,
                        str(result)
                    )
                    continue
                successful_scrapes.append(result)

            # Fail if ALL URLs failed
            if not successful_scrapes:
                error = CompanyProcessingError(
                    company_id=company.id,
                    company_name=company.name,
                    error_type="AllURLsFailedError",
                    error_message=f"All {len(company_urls)} URLs failed to scrape",
                    timestamp=datetime.now(UTC)
                )
                return CompanyProcessingResult(
                    company_id=company.id,
                    company_name=company.name,
                    status=CompanyProcessingStatus.FAILED,
                    error=error,
                    processing_time=(datetime.now(UTC) - start_time).total_seconds()
                )

            # STEP 3: Run detection systems in parallel
            detection_tasks = [
                asyncio.to_thread(self._detect_dead_websites, successful_scrapes),
                asyncio.to_thread(self._detect_acquisitions, successful_scrapes),
                asyncio.to_thread(self._detect_staleness, successful_scrapes),
                asyncio.to_thread(self._detect_operational, successful_scrapes),
                asyncio.to_thread(self._search_news, company),
                asyncio.to_thread(self._process_ocr, successful_scrapes),
            ]

            results = await asyncio.gather(*detection_tasks, return_exceptions=True)

            # Unpack results (log exceptions but continue)
            dead_analysis = results[0] if not isinstance(results[0], Exception) else None
            acquisition_analysis = results[1] if not isinstance(results[1], Exception) else None
            staleness_analysis = results[2] if not isinstance(results[2], Exception) else None
            operational_analysis = results[3] if not isinstance(results[3], Exception) else None
            news_results = results[4] if not isinstance(results[4], Exception) else None
            ocr_texts = results[5] if not isinstance(results[5], Exception) else None

            # Log detection errors
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    detection_name = ["dead", "acquisition", "staleness", "operational", "news", "ocr"][idx]
                    logger.error(
                        "%s detection failed for %s: %s",
                        detection_name.title(),
                        company.name,
                        str(result)
                    )

            # STEP 4: Merge OCR text into keyword analysis
            if ocr_texts and news_results is None:
                news_results = []

            if ocr_texts:
                from valuation_tool.core.keyword_detector import analyze_content
                for text in ocr_texts:
                    analysis = analyze_content(text)
                    news_results.append(analysis)

            # STEP 5: Aggregate signals and persist status
            status_result = await asyncio.to_thread(
                determine_and_persist_status,
                session=self.session,
                company_id=company.id,
                dead_website_analysis=dead_analysis,
                acquisition_analysis=acquisition_analysis,
                staleness_analysis=staleness_analysis,
                operational_analysis=operational_analysis,
                news_results=news_results
            )

            self.session.commit()

            # STEP 6: Return result
            return CompanyProcessingResult(
                company_id=company.id,
                company_name=company.name,
                status=CompanyProcessingStatus.COMPLETED,
                status_determination=status_result,
                processing_time=(datetime.now(UTC) - start_time).total_seconds()
            )

    except Exception as e:
        import traceback
        logger.exception("Unexpected error processing %s", company.name)

        error = CompanyProcessingError(
            company_id=company.id,
            company_name=company.name,
            error_type=type(e).__name__,
            error_message=str(e),
            timestamp=datetime.now(UTC),
            traceback=traceback.format_exc()
        )

        return CompanyProcessingResult(
            company_id=company.id,
            company_name=company.name,
            status=CompanyProcessingStatus.FAILED,
            error=error,
            processing_time=(datetime.now(UTC) - start_time).total_seconds()
        )
```

---

### Step 4: Add Helper Methods

**File:** `batch_processing_service.py` after `process_company` method

**Add these helper methods:**

```python
async def _scrape_url_adaptive(self, url_obj: URL) -> ScrapingResult:
    """Scrape URL using adaptive scraper in thread pool."""
    return await asyncio.to_thread(
        self.adaptive_scraper.scrape_url,
        url_id=url_obj.id,
        capture_screenshot=(
            url_obj.resource_type and
            "social" in url_obj.resource_type.value.lower()
        )
    )

def _detect_dead_websites(
    self,
    scraping_results: list[ScrapingResult]
) -> DeadWebsiteAnalysis | None:
    """Run dead website detection on scraping results."""
    from valuation_tool.core.dead_website_detection import (
        analyze_url_result,
        aggregate_signals,
        analyze_multiple_urls
    )

    all_signals = []
    url_results = []

    for result in scraping_results:
        signals = analyze_url_result(
            url=result.url,
            status_code=result.http_status_code,
            error_message=result.error_message,
            final_url=result.final_url,
            content=result.html_content
        )
        all_signals.extend(signals)

        url_results.append({
            "url": result.url,
            "is_dead": not result.success or result.http_status_code in [404, 410],
            "signal": signals[0] if signals else None
        })

    # Check for multiple URLs all dead pattern
    multi_signal = analyze_multiple_urls(url_results)
    if multi_signal:
        all_signals.append(multi_signal)

    return aggregate_signals(all_signals) if all_signals else None

def _detect_acquisitions(
    self,
    scraping_results: list[ScrapingResult]
) -> AcquisitionAnalysis | None:
    """Run acquisition detection on content."""
    from valuation_tool.core.acquisition_detection import analyze_for_acquisition

    all_signals = []

    for result in scraping_results:
        if not result.success or not result.html_content:
            continue

        analysis = analyze_for_acquisition(
            content=result.markdown_content or result.html_content,
            html_content=result.html_content,
            url=result.url,
            original_url=result.url,
            final_url=result.final_url,
            is_permanent_redirect=(result.http_status_code == 301)
        )

        if analysis and analysis.signals:
            all_signals.extend(analysis.signals)

    if not all_signals:
        return None

    from valuation_tool.core.acquisition_detection import aggregate_signals
    return aggregate_signals(all_signals)

def _detect_staleness(
    self,
    scraping_results: list[ScrapingResult]
) -> StalenessAnalysis | None:
    """Run staleness detection on content."""
    from valuation_tool.core.staleness_detection import analyze_for_staleness
    from valuation_tool.core.html_parser import find_copyright_year
    from datetime import datetime

    all_signals = []

    for result in scraping_results:
        if not result.success:
            continue

        copyright_year = None
        if result.html_content:
            copyright_year = find_copyright_year(result.html_content)

        last_modified = None
        if result.last_modified:
            # Parse last_modified string to datetime if needed
            if isinstance(result.last_modified, str):
                try:
                    last_modified = datetime.fromisoformat(result.last_modified)
                except:
                    pass
            else:
                last_modified = result.last_modified

        analysis = analyze_for_staleness(
            html_content=result.html_content,
            copyright_year=copyright_year,
            last_modified=last_modified
        )

        if analysis and analysis.signals:
            all_signals.extend(analysis.signals)

    if not all_signals:
        return None

    from valuation_tool.core.staleness_detection import aggregate_staleness_signals
    return aggregate_staleness_signals(all_signals)

def _detect_operational(
    self,
    scraping_results: list[ScrapingResult]
) -> OperationalAnalysis | None:
    """Run operational signals detection on content."""
    from valuation_tool.core.operational_signals_detection import (
        detect_job_postings,
        detect_recent_updates,
        aggregate_signals
    )

    all_signals = []

    for result in scraping_results:
        if not result.success or not result.html_content:
            continue

        # Job postings detection
        job_signal = detect_job_postings(result.html_content, result.url)
        if job_signal:
            all_signals.append(job_signal)

        # Recent content updates
        update_signal = detect_recent_updates(
            html_content=result.html_content,
            last_modified=result.last_modified
        )
        if update_signal:
            all_signals.append(update_signal)

    return aggregate_signals(all_signals) if all_signals else None

def _search_news(self, company: Company) -> list[KeywordAnalysisResult] | None:
    """Search and analyze news articles."""
    if not company.business_description:
        return None

    from valuation_tool.core.keyword_detector import analyze_content

    try:
        # Search for news using Firecrawl
        news_response = self.firecrawl_client.search_news(
            company_name=company.name,
            business_description=company.business_description,
            days=90,
            max_results=10
        )

        # Analyze each article
        results = []
        for article in news_response.get("results", []):
            content = article.get("content", "") or article.get("snippet", "")
            if content:
                analysis = analyze_content(content)
                if analysis:
                    results.append(analysis)

        return results if results else None

    except Exception as e:
        logger.error("News search failed for %s: %s", company.name, str(e))
        return None

def _process_ocr(self, scraping_results: list[ScrapingResult]) -> list[str] | None:
    """Extract text from screenshots using OCR."""
    from valuation_tool.core.ocr import process_ocr_image, should_process_screenshot

    ocr_texts = []

    for result in scraping_results:
        screenshot_path = result.metadata.get("screenshot_path")
        if not screenshot_path:
            continue

        if not should_process_screenshot(screenshot_path):
            continue

        try:
            ocr_result = process_ocr_image(screenshot_path, self.config.ocr)
            if ocr_result.has_text:
                ocr_texts.append(ocr_result.text)
        except Exception as e:
            logger.error("OCR failed for %s: %s", screenshot_path, str(e))
            continue

    return ocr_texts if ocr_texts else None
```

---

## Critical Files

1. **`batch_processing_service.py` (lines 182-450)** - Main implementation file
2. **`adaptive_scraper_service.py`** - Interface reference for scraping
3. **`status_determination_service.py`** - Interface for `determine_and_persist_status()`
4. **`signal_aggregation.py`** - Shows `aggregate_all_signals()` signature
5. **Detection modules in `core/`** - All detection function signatures

---

## Performance Characteristics

**Before (Placeholder):**
- 20 companies × 0.1s = 2 seconds total
- No actual work done

**After (Full Implementation):**
- Per company: ~3-4 seconds (5 URLs scraped concurrently + parallel detection)
- 20 companies with concurrency=10: ~40-50 seconds total
- **4-5x faster** than sequential URL processing

**Concurrency Levels:**
1. Batch-level: 10 companies in parallel (existing)
2. Company-level: URLs scraped concurrently (NEW)
3. Detection-level: 6 systems run in parallel (NEW)

---

## Verification & Testing

### 1. Syntax Check
```bash
python -m py_compile src/valuation_tool/service/batch_processing_service.py
```

### 2. Type Check
```bash
mypy src/valuation_tool/service/batch_processing_service.py
```

### 3. Import Verification
```python
from valuation_tool.service.batch_processing_service import BatchProcessor
```

### 4. Integration Test
```bash
cd generations/autonomous_demo_project
valuation-tool process --limit 5 --force-refresh --verbose
```

**Expected behavior:**
- Fetches companies from Airtable
- Scrapes URLs using Firecrawl/Playwright
- Runs detection systems
- Creates WebsiteSnapshot records in database
- Updates Company.status and Company.confidence_score
- Creates StatusDetermination audit records

**Success criteria:**
- Processing time >1 second per company (not 0.4s)
- Database has snapshots: `SELECT COUNT(*) FROM website_snapshots;` returns >0
- Companies have status: `SELECT status, COUNT(*) FROM companies GROUP BY status;` shows operational/requires_review
- No exceptions in logs

### 5. Manual Verification
```bash
# Check a specific company
valuation-tool query company "Modal Labs"

# Should show:
# - Status: operational / requires_review / likely_closed (NOT unknown)
# - Confidence score >0
# - Last checked timestamp updated
# - URLs show verification_status (NOT "not_checked")
```

---

## Error Handling Strategy

| Scenario | Handling | Result |
|----------|----------|--------|
| No URLs found | Skip company | SKIPPED status |
| Some URLs fail | Log & continue | Process with successful URLs |
| All URLs fail | Return error | FAILED status |
| Detection throws exception | Log & pass None | Continue with other detections |
| News search fails | Log & continue | Process without news results |
| OCR fails | Log & continue | Process without OCR text |
| Status determination fails | Propagate exception | FAILED status |

**Philosophy:** Graceful degradation - partial results better than no results.

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Thread pool exhaustion | Detection tasks are fast (<1s each) |
| Database session in threads | SQLAlchemy session is thread-safe for reads |
| Memory growth | Concurrent throttler limits total operations |
| Playwright rate limit | Use `playwright_limiter.limit()` context manager |
| LinkedIn blocking | Already required to use Playwright for LinkedIn |

---

## Rollback Plan

If issues arise:
1. Revert `process_company` method to placeholder
2. Keep client initialization (harmless)
3. Test with `--limit 1` to isolate issues
4. Check logs for specific detection system failures

---

## Success Metrics

**Before:**
- ✅ 20 companies processed in 0.4 seconds
- ❌ 0 snapshots created
- ❌ All companies status="unknown"

**After:**
- ✅ 20 companies processed in 40-50 seconds
- ✅ 100+ snapshots created (5 URLs × 20 companies)
- ✅ Companies have meaningful status (operational/requires_review)
- ✅ Confidence scores calculated
- ✅ Audit trail in StatusDetermination table
