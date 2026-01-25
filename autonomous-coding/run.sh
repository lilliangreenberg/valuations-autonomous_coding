#!/bin/bash
# Convenience script for running the autonomous coding agent with Docker

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}Warning: .env file not found${NC}"
    echo "Creating .env from .env.example..."
    cp .env.example .env
    echo -e "${RED}Please edit .env and add your ANTHROPIC_API_KEY${NC}"
    exit 1
fi

# Check if ANTHROPIC_API_KEY is set in .env
if ! grep -q "^ANTHROPIC_API_KEY=..*" .env; then
    echo -e "${RED}Error: ANTHROPIC_API_KEY not set in .env file${NC}"
    echo "Please edit .env and add your API key"
    exit 1
fi

# Function to display usage
usage() {
    echo "Usage: $0 [command] [options]"
    echo ""
    echo "Commands:"
    echo "  build         Build the Docker image"
    echo "  run           Run the autonomous agent (default)"
    echo "  test          Run with max-iterations=3 for testing"
    echo "  shell         Open a bash shell in the container"
    echo "  clean         Remove generated projects and stop containers"
    echo "  logs          Show container logs"
    echo ""
    echo "Options (for run/test commands):"
    echo "  --project-dir NAME    Custom project directory name (default: autonomous_demo_project)"
    echo "  --max-iterations N    Limit iterations (test uses 3 by default)"
    echo ""
    echo "Examples:"
    echo "  $0 run"
    echo "  $0 run --project-dir my_app"
    echo "  $0 test"
    echo "  $0 shell"
}

# Parse command
COMMAND=${1:-run}
shift || true

# Default values
PROJECT_DIR="autonomous_demo_project"
MAX_ITERATIONS=""

# Parse options
while [[ $# -gt 0 ]]; do
    case $1 in
        --project-dir)
            PROJECT_DIR="$2"
            shift 2
            ;;
        --max-iterations)
            MAX_ITERATIONS="--max-iterations $2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            usage
            exit 1
            ;;
    esac
done

# Execute command
case $COMMAND in
    build)
        echo -e "${GREEN}Building Docker image...${NC}"
        docker-compose build
        ;;

    run)
        echo -e "${GREEN}Running autonomous coding agent...${NC}"
        docker-compose run --rm autonomous-agent python autonomous_agent_demo.py \
            --project-dir /app/generations/$PROJECT_DIR \
            $MAX_ITERATIONS
        ;;

    test)
        echo -e "${GREEN}Running autonomous agent in test mode (3 iterations)...${NC}"
        MAX_ITERATIONS="--max-iterations 3"
        docker-compose run --rm autonomous-agent python autonomous_agent_demo.py \
            --project-dir /app/generations/$PROJECT_DIR \
            $MAX_ITERATIONS
        ;;

    shell)
        echo -e "${GREEN}Opening shell in container...${NC}"
        docker-compose run --rm autonomous-agent /bin/bash
        ;;

    clean)
        echo -e "${YELLOW}Stopping containers and cleaning up...${NC}"
        docker-compose down
        echo -e "${YELLOW}Note: Generated projects in ./generations are preserved${NC}"
        echo -e "${YELLOW}To remove them: rm -rf ./generations/*${NC}"
        ;;

    logs)
        echo -e "${GREEN}Showing container logs...${NC}"
        docker-compose logs -f
        ;;

    -h|--help)
        usage
        exit 0
        ;;

    *)
        echo -e "${RED}Unknown command: $COMMAND${NC}"
        usage
        exit 1
        ;;
esac
