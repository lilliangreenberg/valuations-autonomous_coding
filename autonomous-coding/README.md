# Autonomous Coding Agent Demo

A minimal harness demonstrating long-running autonomous coding with the Claude Agent SDK. This demo implements a two-agent pattern (initializer + coding agent) that can build complete applications over multiple sessions.

## Prerequisites

**Required:** Choose one of the following installation methods:

### Option 1: Docker (Recommended)

Docker provides an isolated environment with all dependencies pre-installed.

**Requirements:**
- Docker and Docker Compose installed
- Anthropic API key

**Setup:**
```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API key
# ANTHROPIC_API_KEY=your-api-key-here

# Build and run
docker-compose up --build
```

### Option 2: Local Installation

**Requirements:**
- Python 3.12+
- Node.js 18+ and npm
- Git

**Setup:**
```bash
# Install Claude Code CLI (latest version required)
npm install -g @anthropic-ai/claude-code

# Install Python dependencies
pip install -r requirements.txt

# Or with uv (recommended)
uv pip install -r requirements.txt
```

Verify your installations:
```bash
claude --version  # Should be latest version
pip show claude-code-sdk  # Check SDK is installed
```

**API Key:** Set your Anthropic API key:
```bash
export ANTHROPIC_API_KEY='API KEY HERE'
```

## Quick Start

### With Docker (Recommended)

Using the convenience script:
```bash
# First time: build the image
./run.sh build

# Run the autonomous agent
./run.sh run

# Test with limited iterations
./run.sh test

# Run with custom project name
./run.sh run --project-dir my_custom_app

# Open a shell in the container
./run.sh shell

# View help
./run.sh --help
```

Or using Docker Compose directly:
```bash
# Build and run with Docker Compose
docker-compose up --build

# Or with custom options
docker-compose run autonomous-agent python autonomous_agent_demo.py \
  --project-dir /app/generations/my_project \
  --max-iterations 5

# Stop the container
docker-compose down
```

### Without Docker

```bash
python autonomous_agent_demo.py --project-dir ./my_project
```

For testing with limited iterations:
```bash
python autonomous_agent_demo.py --project-dir ./my_project --max-iterations 5
```

## Important Timing Expectations

> **Warning: This demo takes a long time to run!**

- **First session (initialization):** The agent generates gherkin features. This takes several minutes and may appear to hang - this is normal. The agent is writing out all the features.

- **Subsequent sessions:** Each coding iteration can take **5-15 minutes** depending on complexity.

- **Full app:** Building all features typically requires **many hours** of total runtime across multiple sessions.

**Tip:** The initializer agent creates one feature file for every identified feature in the spec, which may result in hundreds of files depending on the application scope. This behavior is configured in `prompts/initializer_prompt.md`.

## How It Works

### Two-Agent Pattern

1. **Initializer Agent (Session 1):** Reads `app_spec.txt`, creates gherkin features, sets up project structure, and initializes git.

2. **Coding Agent (Sessions 2+):** Picks up where the previous session left off, implements features one by one, and marks them as passing in `gherkin.feature_*.feature`.

### Session Management

- Each session runs with a fresh context window
- Progress is persisted via gherkin features and git commits
- The agent auto-continues between sessions (3 second delay)
- Press `Ctrl+C` to pause; run the same command to resume

## Security Model

This demo uses a defense-in-depth security approach (see `security.py` and `client.py`):

1. **OS-level Sandbox:** Bash commands run in an isolated environment
2. **Filesystem Restrictions:** File operations restricted to the project directory only
3. **Bash Allowlist:** Only specific commands are permitted:
   - File inspection: `ls`, `cat`, `head`, `tail`, `wc`, `grep`
   - Node.js: `npm`, `node`
   - Version control: `git`
   - Process management: `ps`, `lsof`, `sleep`, `pkill` (dev processes only)

Commands not in the allowlist are blocked by the security hook.

## Project Structure

```
autonomous-coding/
├── autonomous_agent_demo.py  # Main entry point
├── agent.py                  # Agent session logic
├── client.py                 # Claude SDK client configuration
├── security.py               # Bash command allowlist and validation
├── progress.py               # Progress tracking utilities
├── prompts.py                # Prompt loading utilities
├── prompts/
│   ├── app_spec.txt          # Application specification
│   ├── initializer_prompt.md # First session prompt
│   └── coding_prompt.md      # Continuation session prompt
└── requirements.txt          # Python dependencies
```

## Generated Project Structure

After running, your project directory will contain:

```
my_project/
├── gherkin.feature_1.feature  # Gherkin feature file 1
├── gherkin.feature_2.feature  # Gherkin feature file 2
├── gherkin.feature_N.feature  # Additional feature files...
├── feature_dependencies.txt   # Feature dependency mapping
├── app_spec.txt               # Copied specification
├── init.sh                    # Environment setup script
├── claude-progress.txt        # Session progress notes
├── .claude_settings.json      # Security settings
└── [application files]        # Generated application code
```

## Running the Generated Application

After the agent completes (or pauses), you can run the generated application:

```bash
cd generations/my_project

# Run the setup script created by the agent
./init.sh

# Or manually (typical for Node.js apps):
npm install
npm run dev
```

The application will typically be available at `http://localhost:3000` or similar (check the agent's output or `init.sh` for the exact URL).

## Command Line Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project-dir` | Directory for the project | `./valuation_tool_project` |
| `--max-iterations` | Max agent iterations | Unlimited |
| `--model` | Claude model to use | `claude-sonnet-4-5-20250929` |

## Customization

### Changing the Application

Edit `prompts/app_spec.txt` to specify a different application to build.

### Adjusting Feature Coverage

Edit `prompts/initializer_prompt.md` to adjust feature coverage requirements. By default, one feature file is created for every identified feature in the spec (may be hundreds of files). You can modify the prompt to limit coverage for faster demos.

### Modifying Allowed Commands

Edit `security.py` to add or remove commands from `ALLOWED_COMMANDS`.

## Docker Usage

### Building the Image

```bash
# Build with Docker Compose
docker-compose build

# Or build manually
docker build -t autonomous-coding:latest .
```

### Running the Container

```bash
# Run with Docker Compose (recommended)
docker-compose up

# Or run manually
docker run -it \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v $(pwd)/generations:/app/generations \
  autonomous-coding:latest
```

### Customizing Container Options

Edit `docker-compose.yml` to:
- Change the model (default: `claude-sonnet-4-5-20250929`)
- Adjust max iterations
- Modify the project directory path
- Add additional environment variables

### Accessing Generated Projects

Generated projects are stored in the `./generations` directory, which is mounted as a volume. You can access and run them directly from your host machine:

```bash
cd generations/valuation_tool_project
./init.sh  # Run the setup script created by the agent
```

## Troubleshooting

**"Appears to hang on first run"**
This is normal. The initializer agent is generating feature files with detailed scenarios, which takes significant time. Watch for `[Tool: ...]` output to confirm the agent is working.

**"Command blocked by security hook"**
The agent tried to run a command not in the allowlist. This is the security system working as intended. If needed, add the command to `ALLOWED_COMMANDS` in `security.py`.

**"API key not set"**
Ensure `ANTHROPIC_API_KEY` is exported in your shell environment or set in the `.env` file for Docker.

**"Docker build fails"**
Ensure you have enough disk space and memory allocated to Docker. The build installs Playwright browsers which require significant space (~1GB).

**"Permission denied in Docker container"**
The container runs as root by default. Generated files will be owned by root. You can change ownership after generation:
```bash
sudo chown -R $USER:$USER generations/
```

## License

Internal Anthropic use.
