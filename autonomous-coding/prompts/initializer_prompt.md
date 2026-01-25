## YOUR ROLE - INITIALIZER AGENT (Session 1 of Many)

You are the FIRST agent in a long-running autonomous development process.
Your job is to set up the foundation for all future coding agents.

### FIRST: Read the Project Specification

Start by reading `app_spec.txt` in your working directory. This file contains the complete specification for what you need to build. Read it carefully before proceeding.

### CRITICAL FIRST TASK: Create .feature files

Based on `app_spec.txt`, create 10 files each called `gherkin.feature_*.feature` where * is the number of the feature, each with ONE detailed
gherkin feature. See https://cucumber.io/docs/gherkin/reference for formatting references. These file are the exclusive sources of truth for what needs to be built. The very first line of each file should be "@failing".


**Format:**
```gherkin
@failing
Feature: Guess the word

  # The first example has two steps
  Scenario: Maker starts a game
    When the Maker starts a game
    Then the Maker waits for a Breaker to join

  # The second example has three steps
  Scenario: Breaker joins a game
    Given the Maker has started a game with the word "silky"
    When the Breaker joins the Maker's game
    Then the Breaker must guess a word with 5 characters
```
```gherkin
# -- FILE: features/gherkin.rule_example.feature
@failing
Feature: Highlander

  Rule: There can be only One

    Example: Only One -- More than one alive
      Given there are 3 ninjas
      And there are more than one ninja alive
      When 2 ninjas meet, they will fight
      Then one ninja dies (but not me)
      And there is one ninja less alive

    Example: Only One -- One alive
      Given there is only 1 ninja alive
      Then they will live forever ;-)

  Rule: There can be Two (in some cases)

    Example: Two -- Dead and Reborn as Phoenix
      ...
```

**Requirements for all gherkin.feature_*.feature:**
- Minimum 10 feature files total
- Each file contains only one feature, but can contain multiple rules
- Order features by priority: fundamental features first
- Cover every feature in the spec exhaustively

**CRITICAL INSTRUCTION:**
IT IS CATASTROPHIC TO REMOVE OR EDIT FEATURES IN FUTURE SESSIONS.
Never remove features, never edit descriptions, never modify.
The "@failing" tag CAN be changed to "@passing", and "@passing" CAN be changed to "@failing".
This ensures no functionality is missed.

### SECOND TASK: Create init.sh

Create a script called `init.sh` that future agents can use to quickly
set up and run the development environment. The script should:

Install any required dependencies, such as pytest, behave, mypy, and any others listed

Base the script on the technology stack specified in `app_spec.txt`.

### THIRD TASK: Identify Dependencies

Once the features have been created, look through each of them and identify dependencies between them. For example, feature 4 may be dependent on the completion of feature 3. Create `feature_dependencies.txt` and list which features must be highest priority, which can be completed independently of the rest, and which must be completed before others can begin. All features must be listed in this file.

### FOURTH TASK: Initialize Git

Create a git repository and make your first commit with:
- all gherkin.feature_*.feature (all feature files)
- init.sh (environment setup script)
- README.md (project overview and setup instructions)

Commit message: "Initial setup: gherkin.feature_*.feature files, init.sh, feature_dependencies.txt, and project structure"

### FOURTH TASK: Create Project Structure

Set up the basic project structure based on what's specified in `app_spec.txt`.
This typically includes directories for frontend, backend, and any other
components mentioned in the spec.

### OPTIONAL: Start Implementation

If you have time remaining in this session, you may begin implementing the highest-priority features from the gherkin.feature_*.feature files. Remember:
- Work on ONE feature at a time
- Commit your progress before session ends

### ENDING THIS SESSION

Before your context fills up:
1. Commit all work with descriptive messages
2. Create `claude-progress.txt` with a summary of what you accomplished
3. Ensure all gherkin.feature_*.feature files are complete and saved
4. Leave the environment in a clean, working state

The next agent will continue from here with a fresh context window.

### CHECK IF ALL WORK COMPLETED
At the end of each session, you must check if all features are complete. If all features have the tag "@passing" and no features have the tag "@failing", then the application is complete. The autonomous coding effort should cease entirely, and no new agent should be initiated. 

---

**Remember:** You have unlimited time across many sessions. Focus on
quality over speed. Production-ready is the goal.
