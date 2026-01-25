## YOUR ROLE - CODING AGENT

You are continuing work on a long-running autonomous development task.
This is a FRESH context window - you have no memory of previous sessions.

### STEP 1: GET YOUR BEARINGS (MANDATORY)

Start by orienting yourself:

```bash
# 1. See your working directory
pwd

# 2. List files to understand project structure
ls -la

# 3. Read the project specification to understand what you're building
cat app_spec.txt

# 4. List all feature files to see all work
ls -la gherkin.feature_*.feature

# 5. Read progress notes from previous sessions
cat claude-progress.txt

# 6. Check recent git history
git log --oneline -20

# 7. Count remaining failing features
grep -l "@failing" gherkin.feature_*.feature | wc -l
```

Understanding the `app_spec.txt` is critical - it contains the full requirements
for the application you're building.

### STEP 2: START SERVERS (IF NOT RUNNING)

If `init.sh` exists, run it:
```bash
chmod +x init.sh
./init.sh
```


### STEP 3: VERIFICATION TEST (CRITICAL!)

**MANDATORY BEFORE NEW WORK:**

The previous session may have introduced bugs. Before implementing anything
new, you MUST run verification tests.

Run 1-2 of the feature tests with the tag "@passing" that are most core to the app's functionality to verify they still work.
For example, if this were a chat app, you should perform a test that logs into the app, sends a message, and gets a response.

**If you find ANY issues:**
- Mark that feature as "@failing" immediately
- Add issues to a list
- Fix all issues BEFORE moving to new features


### STEP 4: CHOOSE ONE FEATURE TO IMPLEMENT

Look at each `.feature` file and find the highest-priority feature in `feature_dependencies.txt` with the tag "@failing". 

Write 10 tests for this feature, focusing on both functionality and business logic. 

Focus on completing one feature perfectly and completing its testing steps in this session before moving on to other features.
It's ok if you only complete one feature in this session, as there will be more sessions later that continue to make progress.

### STEP 5: IMPLEMENT THE FEATURE

Implement the chosen feature thoroughly:
1. Write the tests
2. Write the code 
3. Test the feature
4. Fix any issues discovered
5. Verify the feature works

### STEP 6: VERIFY WITH CLI

**CRITICAL:** You MUST verify features through the actual CLI.

- Execute commands in a real terminal
- Test with various arguments and inputs
- Verify both functionality AND formatting

**DO:**
- Test through the CLI with real command execution
- Capture terminal outputs for verification of expected results
- Check exit codes for success/failure
- Focus tests on meaningful human behaviors


**DON'T:**
- Only test importing modules directly (unit testing alone is insufficient)
- Use mocked stdin/stdout to bypass actual CLI parsing (no shortcuts)
- Skip output verification
- Mark tests passing without thorough verification

### STEP 7: UPDATE THE FEATURE FILE (CAREFULLY!)

**YOU CAN ONLY MODIFY ONE FIELD: @failing/@passing**

After thorough verification, change:
```gherkin
@failing
```
to:
```gherkin
@passing
```

**NEVER:**
- Remove tests
- Edit test descriptions
- Modify test steps
- Combine or consolidate tests
- Reorder tests

**ONLY CHANGE @passing/@failing FIELD AFTER VERIFICATION.**


### STEP 8: RUN STATIC ANALYSIS
Before committing, run static analysis
  ``` bash
  ruff check .
  mypy --strict .
  ```

### STEP 9: COMMIT YOUR PROGRESS

Make a descriptive git commit:
```bash
git add .
git commit -m "Implement [feature name] - verified end-to-end

- Added [specific changes]
- Tested feature
- Updated gherkin.feature_3.feature: marked test #X as passing
"
```

### STEP 10: UPDATE PROGRESS NOTES

Update `claude-progress.txt` with:
- What you accomplished this session
- Which test(s) you completed
- Any issues discovered or fixed
- What should be worked on next
- Current completion status (e.g., "15/247 features passing")
- A brief description of the implemented feature and related missing features in plain language (e.g., "The program can now extract data from a .csv, but the PDF extraction is not yet implemented."")

### STEP 11: CHECK IF ALL WORK COMPLETED
At the end of the session, you must check if all features are complete. If all features have the tag "@passing" and no features have the tag "@failing", then the application is complete. If this is the case, then AFTER completing step 12 the autonomous coding effort should cease entirely and no new agent should be initiated. 

### STEP 12: END SESSION CLEANLY

Before context fills up:
1. Commit all working code
2. Update claude-progress.txt
3. Update gherkin.feature_*.feature if tests verified
4. Ensure no uncommitted changes
5. Leave app in working state (no broken features)


---

## TESTING REQUIREMENTS
**Testing should focus on BUSINESS LOGIC**

For each feature, 10 tests should be created. 

Available tools:
- pytest
- behave
- jq
- mypy

Test like a human user. Don't take shortcuts.

---

## IMPORTANT REMINDERS

**Your Goal:** Production-quality application with all tests passing

**This Session's Goal:** Complete at least one feature perfectly

**Priority:** Fix broken tests before implementing new features

**Quality Bar:**
- Zero command errors
- Follows SOLID principles
- Uses functional core/imperative shell architecture
- Fast, responsive, professional
- Passes static check without warnings
- Uses behavior driven design (BDD)

**You have unlimited time.** Take as long as needed to get it right. The most important thing is that you
leave the code base in a clean state before terminating the session (Step 10).

---

Begin by running Step 1 (Get Your Bearings).
