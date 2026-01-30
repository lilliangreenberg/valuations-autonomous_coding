# Database Validation Fix

## Problem

The CLI was checking if the database **file** existed, but not checking if **migrations had been applied**. This caused the program to report success messages like "979 companies added, 1000+ URLs" from Airtable, but then fail silently when trying to write to non-existent tables.

### Root Cause

In `src/valuation_tool/cli.py`, the validation was:

```python
if not db_path.exists():
    console.print("[bold red]Error:[/bold red] Database does not exist. Run 'db init' first.")
    sys.exit(1)
```

This checked if the **file** exists, but an empty database file with only the `alembic_version` table would pass this check, then fail when trying to insert into `companies` or `urls` tables.

## Solution

Added comprehensive database validation in `check_database_schema()` function that:

1. **Checks if database file exists**
2. **Verifies all required tables are present**:
   - companies
   - urls
   - company_urls
   - website_snapshots
   - status_determinations
   - processing_runs
3. **Provides actionable error messages** with exact commands to fix the issue

### New Error Messages

**Before:**
```
Error: Database does not exist. Run 'db init' first.
```

**After (missing file):**
```
Database Error:
Database file does not exist at: /path/to/valuation_tool.db
Run 'valuation-tool db init' to create and initialize the database.
```

**After (migrations not applied):**
```
Database Error:
Database exists but schema is not initialized.
Missing tables: companies, urls, company_urls, website_snapshots, status_determinations, processing_runs
Run 'alembic upgrade head' to apply migrations, or
Run 'valuation-tool db init' to initialize the database.
```

## Commands Updated

The validation was added to these commands:

1. ✅ `valuation-tool process` - Main processing command
2. ✅ `valuation-tool db sync` - Airtable sync command
3. ✅ `valuation-tool stats` - Statistics command
4. ✅ `valuation-tool query flagged` - Query flagged companies

## Testing

All validation scenarios tested and working:

- ✅ Non-existent database file
- ✅ Empty database (only alembic_version table)
- ✅ Partial schema (some tables missing)
- ✅ Valid database (all tables present)

## How to Use

After this fix, users will see clear error messages when the database isn't properly initialized:

```bash
# If database doesn't exist or is uninitialized:
$ valuation-tool process
Database Error:
Database exists but schema is not initialized.
Missing tables: companies, urls, ...
Run 'alembic upgrade head' to apply migrations, or
Run 'valuation-tool db init' to initialize the database.

# Fix by running migrations:
$ alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 7803a715685d

# Or initialize from scratch:
$ valuation-tool db init
✓ Database created at: valuation_tool.db
✓ All tables created successfully
✓ Schema stamped to latest version
```

## Impact

This fix prevents the confusing scenario where:
1. Airtable reports "979 companies, 1000+ URLs fetched"
2. Program attempts to write to database
3. SQLAlchemy raises `OperationalError: no such table: companies`
4. Transaction rolls back
5. User thinks data was saved but database is empty

Now, users get a clear error **before** any Airtable API calls are made, with exact instructions on how to fix the issue.
