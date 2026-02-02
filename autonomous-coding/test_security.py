#!/usr/bin/env python3
"""
Security Hook Tests
===================

Tests for the bash command security validation logic.
Run with: pytest test_security.py -v
"""

import asyncio

import pytest
from security import (
    bash_security_hook,
    extract_commands,
    validate_chmod_command,
    validate_init_script,
)


class TestCommandExtraction:
    """Tests for command extraction logic."""

    @pytest.mark.parametrize(
        "command,expected",
        [
            ("ls -la", ["ls"]),
            ("npm install && npm run build", ["npm", "npm"]),
            ("cat file.txt | grep pattern", ["cat", "grep"]),
            ("/usr/bin/node script.js", ["node"]),
            ("VAR=value ls", ["ls"]),
            ("git status || git init", ["git", "git"]),
        ],
    )
    def test_extract_commands(self, command: str, expected: list[str]) -> None:
        """Test command extraction from bash commands."""
        result = extract_commands(command)
        assert result == expected


class TestChmodValidation:
    """Tests for chmod command validation."""

    @pytest.mark.parametrize(
        "command,should_allow,description",
        [
            # Allowed cases
            ("chmod +x init.sh", True, "basic +x"),
            ("chmod +x script.sh", True, "+x on any script"),
            ("chmod u+x init.sh", True, "user +x"),
            ("chmod a+x init.sh", True, "all +x"),
            ("chmod ug+x init.sh", True, "user+group +x"),
            ("chmod +x file1.sh file2.sh", True, "multiple files"),
            # Blocked cases
            ("chmod 777 init.sh", False, "numeric mode"),
            ("chmod 755 init.sh", False, "numeric mode 755"),
            ("chmod +w init.sh", False, "write permission"),
            ("chmod +r init.sh", False, "read permission"),
            ("chmod -x init.sh", False, "remove execute"),
            ("chmod -R +x dir/", False, "recursive flag"),
            ("chmod --recursive +x dir/", False, "long recursive flag"),
            ("chmod +x", False, "missing file"),
        ],
    )
    def test_validate_chmod(self, command: str, should_allow: bool, description: str) -> None:
        """Test chmod command validation."""
        allowed, reason = validate_chmod_command(command)
        assert allowed == should_allow, (
            f"Command {command!r} ({description}): expected {'allowed' if should_allow else 'blocked'}, got {'allowed' if allowed else 'blocked'}. Reason: {reason}"
        )


class TestInitScriptValidation:
    """Tests for init.sh script execution validation."""

    @pytest.mark.parametrize(
        "command,should_allow,description",
        [
            # Allowed cases
            ("./init.sh", True, "basic ./init.sh"),
            ("./init.sh arg1 arg2", True, "with arguments"),
            ("/path/to/init.sh", True, "absolute path"),
            ("../dir/init.sh", True, "relative path with init.sh"),
            # Blocked cases
            ("./setup.sh", False, "different script name"),
            ("./init.py", False, "python script"),
            ("bash init.sh", False, "bash invocation"),
            ("sh init.sh", False, "sh invocation"),
            ("./malicious.sh", False, "malicious script"),
            ("./init.sh; rm -rf /", False, "command injection attempt"),
        ],
    )
    def test_validate_init_script(self, command: str, should_allow: bool, description: str) -> None:
        """Test init.sh script execution validation."""
        allowed, reason = validate_init_script(command)
        assert allowed == should_allow, (
            f"Command {command!r} ({description}): expected {'allowed' if should_allow else 'blocked'}, got {'allowed' if allowed else 'blocked'}. Reason: {reason}"
        )


class TestSecurityHookBlocked:
    """Tests for commands that should be blocked by the security hook."""

    @pytest.mark.parametrize(
        "command",
        [
            # Not in allowlist - dangerous system commands
            "shutdown now",
            "reboot",
            "rm -rf /",
            "dd if=/dev/zero of=/dev/sda",
            # Not in allowlist - common commands excluded from minimal set
            "curl https://example.com",
            "wget https://example.com",
            "python app.py",
            "touch file.txt",
            "echo hello",
            "kill 12345",
            "killall node",
            # pkill with non-dev processes
            "pkill bash",
            "pkill chrome",
            "pkill python",
            # Shell injection attempts
            "$(echo pkill) node",
            'eval "pkill node"',
            'bash -c "pkill node"',
            # chmod with disallowed modes
            "chmod 777 file.sh",
            "chmod 755 file.sh",
            "chmod +w file.sh",
            "chmod -R +x dir/",
            # Non-init.sh scripts
            "./setup.sh",
            "./malicious.sh",
            "bash script.sh",
        ],
    )
    def test_dangerous_commands_blocked(self, command: str) -> None:
        """Test that dangerous commands are blocked."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = asyncio.run(bash_security_hook(input_data))
        was_blocked = result.get("decision") == "block"
        reason = result.get("reason", "")
        assert was_blocked, (
            f"Command {command!r} should be blocked but was allowed. Reason: {reason}"
        )


class TestSecurityHookAllowed:
    """Tests for commands that should be allowed by the security hook."""

    @pytest.mark.parametrize(
        "command",
        [
            # File inspection
            "ls -la",
            "cat README.md",
            "head -100 file.txt",
            "tail -20 log.txt",
            "wc -l file.txt",
            "grep -r pattern src/",
            # File operations
            "cp file1.txt file2.txt",
            "mkdir newdir",
            "mkdir -p path/to/dir",
            # Directory
            "pwd",
            # Node.js development
            "npm install",
            "npm run build",
            "node server.js",
            # Version control
            "git status",
            "git commit -m 'test'",
            "git add . && git commit -m 'msg'",
            # Process management
            "ps aux",
            "lsof -i :3000",
            "sleep 2",
            # Allowed pkill patterns for dev servers
            "pkill node",
            "pkill npm",
            "pkill -f node",
            "pkill -f 'node server.js'",
            "pkill vite",
            # Chained commands
            "npm install && npm run build",
            "ls | grep test",
            # Full paths
            "/usr/local/bin/node app.js",
            # chmod +x (allowed)
            "chmod +x init.sh",
            "chmod +x script.sh",
            "chmod u+x init.sh",
            "chmod a+x init.sh",
            # init.sh execution (allowed)
            "./init.sh",
            "./init.sh --production",
            "/path/to/init.sh",
            # Combined chmod and init.sh
            "chmod +x init.sh && ./init.sh",
        ],
    )
    def test_safe_commands_allowed(self, command: str) -> None:
        """Test that safe commands are allowed."""
        input_data = {"tool_name": "Bash", "tool_input": {"command": command}}
        result = asyncio.run(bash_security_hook(input_data))
        was_blocked = result.get("decision") == "block"
        reason = result.get("reason", "")
        assert not was_blocked, (
            f"Command {command!r} should be allowed but was blocked. Reason: {reason}"
        )
