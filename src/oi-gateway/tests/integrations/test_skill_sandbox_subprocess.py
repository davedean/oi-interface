"""Tests for subprocess-based skill sandbox, tool broker, and firmware protection."""
from __future__ import annotations

import pytest

from integrations.skill_sandbox import (
    Skill,
    SkillSandbox,
    SkillExecutor,
    ToolBroker,
    RiskLevel,
    SkillValidationError,
)


class TestToolBroker:
    """Tests for the ToolBroker class."""

    @pytest.fixture
    def tool_broker(self):
        """Create a tool broker instance."""
        return ToolBroker()

    def test_tool_broker_init(self, tool_broker):
        """Test tool broker initializes with correct permissions."""
        assert tool_broker is not None
        assert len(tool_broker._permissions) > 0

    def test_allowed_tools_safe_level(self, tool_broker):
        """Test getting allowed tools for SAFE risk level."""
        allowed = tool_broker.get_allowed_tools(RiskLevel.SAFE)
        # SAFE level should have minimal permissions
        assert "read_state" in allowed
        assert "list_devices" in allowed
        # Restricted tools should not be allowed
        assert "rebind_buttons" not in allowed
        assert "flash_firmware" not in allowed
        assert "bypass_mute" not in allowed

    def test_allowed_tools_limited_level(self, tool_broker):
        """Test getting allowed tools for LIMITED risk level."""
        allowed = tool_broker.get_allowed_tools(RiskLevel.LIMITED)
        # Limited should include SAFE tools
        assert "read_state" in allowed
        assert "list_devices" in allowed
        # Limited tools
        assert "show_status" in allowed
        assert "play_audio" in allowed

    def test_allowed_tools_elevated_level(self, tool_broker):
        """Test getting allowed tools for ELEVATED risk level."""
        allowed = tool_broker.get_allowed_tools(RiskLevel.ELEVATED)
        # Elevated should include all except restricted
        assert "read_state" in allowed
        assert "list_devices" in allowed
        assert "show_status" in allowed
        assert "play_audio" in allowed
        assert "mute_device" in allowed
        assert "cache_audio" in allowed

    def test_forbidden_operations_blocked(self, tool_broker):
        """Test that forbidden operations are blocked."""
        # Direct forbidden operations
        assert not tool_broker.is_operation_allowed("rebind_buttons")
        assert not tool_broker.is_operation_allowed("flash_firmware")
        assert not tool_broker.is_operation_allowed("bypass_mute")
        assert not tool_broker.is_operation_allowed("execute_system")

    def test_allowed_operations_pass(self, tool_broker):
        """Test that normal operations are allowed."""
        assert tool_broker.is_operation_allowed("read_state")
        assert tool_broker.is_operation_allowed("show_status")
        assert tool_broker.is_operation_allowed("play_audio")

    def test_check_permission_safe_skill(self, tool_broker):
        """Test permission check for a SAFE level skill."""
        # SAFE skill can access SAFE tools
        assert tool_broker.check_permission("read_state", RiskLevel.SAFE)
        assert tool_broker.check_permission("list_devices", RiskLevel.SAFE)
        
        # SAFE skill cannot access LIMITED tools
        assert not tool_broker.check_permission("show_status", RiskLevel.SAFE)

    def test_check_permission_restricted_tool(self, tool_broker):
        """Test that restricted tools are always blocked."""
        assert not tool_broker.check_permission("rebind_buttons", RiskLevel.ELEVATED)
        assert not tool_broker.check_permission("flash_firmware", RiskLevel.ELEVATED)
        assert not tool_broker.check_permission("bypass_mute", RiskLevel.ELEVATED)

    def test_check_permission_unknown_tool_denied(self, tool_broker):
        """Unknown tools should fail closed."""
        assert not tool_broker.check_permission("totally_new_tool", RiskLevel.ELEVATED)


class TestSkillExecutor:
    """Tests for the SkillExecutor class (subprocess execution)."""

    @pytest.fixture
    def executor(self):
        """Create a skill executor instance."""
        return SkillExecutor(max_execution_time=5.0)

    @pytest.mark.asyncio
    async def test_executor_runs_in_subprocess(self, executor):
        """Test that skill executes in a subprocess."""
        # Simple skill that returns a value
        code = "result = 42"
        result = await executor.execute(code, {})
        
        assert result.success is True
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_executor_receives_parameters(self, executor):
        """Test that parameters are passed to the skill."""
        code = "result = parameters.get('value', 'default')"
        result = await executor.execute(code, {"value": "hello"})
        
        assert result.success is True
        assert result.result == "hello"

    @pytest.mark.asyncio
    async def test_executor_handles_complex_results(self, executor):
        """Test skill can return complex data structures."""
        code = "result = {'key': 'value', 'list': [1, 2, 3]}"
        result = await executor.execute(code, {})
        
        assert result.success is True
        assert result.result == {"key": "value", "list": [1, 2, 3]}

    @pytest.mark.asyncio
    async def test_executor_timeout(self, executor):
        """Test that executor respects timeout."""
        # Create executor with very short timeout
        short_executor = SkillExecutor(max_execution_time=0.1)
        
        # Skill that sleeps longer than timeout
        code = "import time; time.sleep(1); result = 'done'"
        result = await short_executor.execute(code, {})
        
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_executor_captures_errors(self, executor):
        """Test that execution errors are captured."""
        code = "result = undefined_variable"
        result = await executor.execute(code, {})
        
        assert result.success is False
        assert result.error is not None


class TestSkillSandboxFirmwareProtection:
    """Tests for firmware protection in SkillSandbox."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox instance."""
        return SkillSandbox(max_execution_time=5.0)

    def test_forbidden_button_rebinding_blocked(self, sandbox):
        """Test that button rebinding patterns are blocked at registration."""
        skill = Skill(
            name="rebind_skill",
            description="Tries to rebind buttons",
            code="result = parameters.get('button_map')",
        )
        
        # Should be blocked - button_map is a forbidden pattern
        with pytest.raises(SkillValidationError, match="Forbidden operation"):
            sandbox.register_skill(skill)

    def test_forbidden_firmware_flash_blocked(self, sandbox):
        """Test that firmware flash patterns are blocked."""
        skill = Skill(
            name="flash_skill",
            description="Tries to flash firmware",
            code="result = parameters.get('flash_firmware')",
        )
        
        # Should be blocked - flash_firmware is a forbidden pattern
        with pytest.raises(SkillValidationError, match="Forbidden operation"):
            sandbox.register_skill(skill)

    def test_forbidden_eval_blocked(self, sandbox):
        """Test that eval is blocked."""
        skill = Skill(
            name="eval_skill",
            description="Uses eval",
            code="result = eval('1+1')",
        )
        
        with pytest.raises(SkillValidationError, match="Forbidden pattern"):
            sandbox.register_skill(skill)

    def test_forbidden_exec_blocked(self, sandbox):
        """Test that exec is blocked."""
        skill = Skill(
            name="exec_skill",
            description="Uses exec",
            code="exec('result = 1')",
        )
        
        with pytest.raises(SkillValidationError, match="Forbidden pattern"):
            sandbox.register_skill(skill)

    def test_forbidden_os_import_blocked(self, sandbox):
        """Test that os import is blocked."""
        skill = Skill(
            name="os_skill",
            description="Imports os",
            code="import os; result = os.name",
        )

        with pytest.raises(SkillValidationError, match="Forbidden import"):
            sandbox.register_skill(skill)

    def test_forbidden_import_via___import___blocked(self, sandbox):
        """Test that dynamic __import__ access is blocked."""
        skill = Skill(
            name="dynamic_import_skill",
            description="Imports os dynamically",
            code='result = __import__("os").name',
        )

        with pytest.raises(SkillValidationError, match="Forbidden pattern"):
            sandbox.register_skill(skill)

    def test_harmless_string_literal_is_allowed(self, sandbox):
        """Mentioning a forbidden token in a plain string should not be blocked."""
        skill = Skill(
            name="string_literal_skill",
            description="Returns a harmless label",
            code='result = "button_map"',
        )

        sandbox.register_skill(skill)
        assert sandbox.get_skill("string_literal_skill") is skill


class TestSkillSandboxSubprocess:
    """Tests for subprocess-based execution in SkillSandbox."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox instance."""
        return SkillSandbox(max_execution_time=5.0)

    @pytest.mark.asyncio
    async def test_execute_in_subprocess(self, sandbox):
        """Test that execution uses subprocess."""
        skill = Skill(
            name="subprocess_test",
            description="Test subprocess execution",
            code="result = 'executed'",
        )
        
        sandbox.register_skill(skill)
        result = await sandbox.execute_skill("subprocess_test", {})
        
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execution_time_recorded(self, sandbox):
        """Test that execution time is recorded in result."""
        skill = Skill(
            name="timing_test",
            description="Test timing",
            code="result = 'done'",
        )
        
        sandbox.register_skill(skill)
        result = await sandbox.execute_skill("timing_test", {})
        
        assert result.execution_time > 0

    @pytest.mark.asyncio
    async def test_execution_context_tracking(self, sandbox):
        """Test that execution context is tracked."""
        skill = Skill(
            name="context_test",
            description="Test context",
            code="result = 'done'",
        )
        
        sandbox.register_skill(skill)
        
        # Execute and check context is created
        result = await sandbox.execute_skill("context_test", {})
        
        # Context should be cleaned up after execution
        assert len(sandbox._execution_contexts) == 0


class TestSkillRiskLevel:
    """Tests for skill risk level classification."""

    def test_skill_default_risk_level(self):
        """Test that skills have a default risk level."""
        skill = Skill(
            name="test",
            description="Test",
            code="result = 'test'",
        )
        
        assert skill.risk_level == RiskLevel.LIMITED

    def test_skill_custom_risk_level(self):
        """Test that skills can have custom risk level."""
        skill = Skill(
            name="test",
            description="Test",
            code="result = 'test'",
            risk_level=RiskLevel.SAFE,
        )
        
        assert skill.risk_level == RiskLevel.SAFE

    def test_sandbox_stores_risk_level(self):
        """Test that sandbox stores risk level with skill."""
        sandbox = SkillSandbox()
        
        skill = Skill(
            name="test",
            description="Test",
            code="result = 'test'",
            risk_level=RiskLevel.ELEVATED,
        )
        
        sandbox.register_skill(skill)
        stored = sandbox.get_skill("test")
        
        assert stored.risk_level == RiskLevel.ELEVATED