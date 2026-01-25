# Dockerfile for Autonomous Coding Agent
# Supports long-running agent sessions that build complete applications

FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    # Core build tools
    build-essential \
    curl \
    git \
    wget \
    gnupg \
    ca-certificates \
    # Playwright browser dependencies
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    xdg-utils \
    # Tesseract OCR (for screenshot text extraction)
    tesseract-ocr \
    tesseract-ocr-eng \
    # Development tools
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js from NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files first (for layer caching)
COPY requirements.txt pyproject.toml* ./

# Install Python dependencies with uv
RUN uv pip install --system -r requirements.txt

# Install puppeteer MCP server globally (needed by client.py)
RUN npm install -g puppeteer-mcp-server

# Install Claude Code CLI (needed by claude-code-sdk)
RUN npm install -g @anthropic-ai/claude-code

# Install Playwright browsers (needed for LinkedIn scraping)
RUN npx playwright install chromium --with-deps

# Copy application code
COPY autonomous_agent_demo.py agent.py client.py prompts.py security.py progress.py ./

# Copy prompts directory
COPY prompts/ ./prompts/

# Create directory for generated projects
RUN mkdir -p /app/generations

# Set default command
CMD ["python", "autonomous_agent_demo.py"]

# Labels
LABEL maintainer="Anthropic"
LABEL description="Autonomous coding agent using Claude Agent SDK"
LABEL version="0.1.0"
