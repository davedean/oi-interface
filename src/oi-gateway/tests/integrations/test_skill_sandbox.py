"""Tests for Skill Sandbox."""
from __future__ import annotations

import pytest

from integrations.skill_sandbox import (
    Skill,
    SkillManifest,
    SkillResult,
    SkillSandbox,
    SkillSandboxError,
    SkillValidationError,
)


class TestSkill:
    """Tests for Skill dataclass."""

    def test_skill_creation(self):
        """Test skill creation."""
        skill = Skill(
            name="test_skill",
            description="A test skill",
            code="result = parameters['value'] * 2",
            version="1.0.0",
            parameters=[{"name": "value", "type": "number"}],
        )
        assert skill.name == "test_skill"
        assert skill.description == "A test skill"
        assert skill.version == "1.0.0"
        assert len(skill.parameters) == 1


class TestSkillManifest:
    """Tests for SkillManifest dataclass."""

    def test_manifest_creation(self):
        """Test manifest creation."""
        manifest = SkillManifest(
            name="test_skill",
            version="1.0.0",
            description="A test skill",
            parameters=[{"name": "value", "type": "number"}],
        )
        assert manifest.name == "test_skill"
        assert manifest.version == "1.0.0"


class TestSkillResult:
    """Tests for SkillResult dataclass."""

    def test_result_success(self):
        """Test success result."""
        result = SkillResult(
            success=True,
            result={"output": "test"},
            execution_time=0.5,
        )
        assert result.success is True
        assert result.result == {"output": "test"}
        assert result.error is None

    def test_result_error(self):
        """Test error result."""
        result = SkillResult(
            success=False,
            error="Execution failed",
            execution_time=1.0,
        )
        assert result.success is False
        assert result.error == "Execution failed"


class TestSkillSandbox:
    """Tests for SkillSandbox."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox instance."""
        return SkillSandbox(
            max_execution_time=5.0,
            max_memory_mb=128,
            allowed_imports=["json", "math", "random"],
        )

    def test_init(self, sandbox):
        """Test sandbox initialization."""
        assert sandbox.max_execution_time == 5.0
        assert sandbox.skill_count == 0

    def test_register_skill(self, sandbox):
        """Test skill registration."""
        skill = Skill(
            name="add_numbers",
            description="Add two numbers",
            code="result = parameters['a'] + parameters['b']",
        )

        skill_id = sandbox.register_skill(skill)

        assert skill_id is not None
        assert sandbox.skill_count == 1

    def test_register_skill_with_id(self, sandbox):
        """Test skill registration preserves existing ID."""
        skill = Skill(
            name="test_skill",
            description="Test",
            code="result = parameters['value']",
            skill_id="existing-id",
        )

        skill_id = sandbox.register_skill(skill)

        assert skill.skill_id == "existing-id"

    def test_register_skill_invalid_import(self, sandbox):
        """Test skill registration with forbidden import."""
        skill = Skill(
            name="bad_skill",
            description="Bad skill",
            code="import os; result = os.name",
        )

        with pytest.raises(SkillValidationError, match="Forbidden import"):
            sandbox.register_skill(skill)

    def test_register_skill_forbidden_pattern(self, sandbox):
        """Test skill registration with forbidden pattern."""
        skill = Skill(
            name="eval_skill",
            description="Skill using eval",
            code="result = eval('1+1')",
        )

        with pytest.raises(SkillValidationError, match="Forbidden pattern"):
            sandbox.register_skill(skill)

    def test_get_skill(self, sandbox):
        """Test getting a skill."""
        skill = Skill(
            name="test_skill",
            description="Test",
            code="result = parameters['value']",
        )

        sandbox.register_skill(skill)

        retrieved = sandbox.get_skill("test_skill")

        assert retrieved is not None
        assert retrieved.name == "test_skill"

    def test_get_skill_not_found(self, sandbox):
        """Test getting non-existent skill."""
        result = sandbox.get_skill("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_execute_skill_not_found(self, sandbox):
        """Test executing non-existent skill."""
        with pytest.raises(Exception):  # SkillNotFoundError not imported
            await sandbox.execute_skill("nonexistent", {})

    @pytest.mark.asyncio
    async def test_execute_skill_success(self, sandbox):
        """Test successful skill execution."""
        skill = Skill(
            name="add_numbers",
            description="Add two numbers",
            code="result = parameters['a'] + parameters['b']",
        )

        sandbox.register_skill(skill)

        result = await sandbox.execute_skill("add_numbers", {"a": 5, "b": 3})

        assert result.success is True
        assert result.result == 8

    @pytest.mark.asyncio
    async def test_execute_skill_with_complex_result(self, sandbox):
        """Test skill execution with complex result."""
        skill = Skill(
            name="process_data",
            description="Process data",
            code="result = {'sum': parameters['a'] + parameters['b'], 'product': parameters['a'] * parameters['b']}",
        )

        sandbox.register_skill(skill)

        result = await sandbox.execute_skill("process_data", {"a": 3, "b": 4})

        assert result.success is True
        assert result.result["sum"] == 7
        assert result.result["product"] == 12

    @pytest.mark.asyncio
    async def test_execute_skill_timeout(self, sandbox):
        """Test skill execution timeout."""
        # Create a very slow skill
        skill = Skill(
            name="slow_skill",
            description="A slow skill",
            code="import time; time.sleep(10); result = 'done'",
        )

        sandbox.register_skill(skill)

        # Create sandbox with very short timeout
        fast_sandbox = SkillSandbox(max_execution_time=0.1)

        fast_sandbox.register_skill(skill)

        result = await fast_sandbox.execute_skill("slow_skill", {})

        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_execute_skill_error(self, sandbox):
        """Test skill execution with error."""
        skill = Skill(
            name="error_skill",
            description="Error skill",
            code="result = nonexistent_variable",
        )

        sandbox.register_skill(skill)

        result = await sandbox.execute_skill("error_skill", {})

        assert result.success is False
        assert result.error is not None

    def test_list_skills(self, sandbox):
        """Test listing skills."""
        skill1 = Skill(
            name="skill_one",
            description="First skill",
            code="result = parameters['value']",
        )
        skill2 = Skill(
            name="skill_two",
            description="Second skill",
            code="result = parameters['value'] * 2",
        )

        sandbox.register_skill(skill1)
        sandbox.register_skill(skill2)

        manifests = sandbox.list_skills()

        assert len(manifests) == 2
        names = [m.name for m in manifests]
        assert "skill_one" in names
        assert "skill_two" in names

    def test_delete_skill(self, sandbox):
        """Test deleting a skill."""
        skill = Skill(
            name="delete_me",
            description="Will be deleted",
            code="result = parameters['value']",
        )

        sandbox.register_skill(skill)
        assert sandbox.skill_count == 1

        result = sandbox.delete_skill("delete_me")

        assert result is True
        assert sandbox.skill_count == 0

    def test_delete_skill_not_found(self, sandbox):
        """Test deleting non-existent skill."""
        result = sandbox.delete_skill("nonexistent")
        assert result is False

    def test_max_execution_time_setter(self, sandbox):
        """Test setting max execution time."""
        sandbox.max_execution_time = 10.0
        assert sandbox.max_execution_time == 10.0


class TestSkillSandboxEdgeCases:
    """Edge case tests for SkillSandbox."""

    @pytest.fixture
    def sandbox(self):
        """Create a sandbox instance."""
        return SkillSandbox(
            max_execution_time=5.0,
            max_memory_mb=128,
            allowed_imports=["json", "math", "random"],
        )

    @pytest.mark.asyncio
    async def test_empty_parameters(self, sandbox):
        """Test skill execution with no parameters."""
        skill = Skill(
            name="no_params",
            description="No params needed",
            code="result = 'always works'",
        )

        sandbox.register_skill(skill)

        result = await sandbox.execute_skill("no_params", {})

        assert result.success is True

    @pytest.mark.asyncio
    async def test_math_operations(self, sandbox):
        """Test skill with math operations."""
        skill = Skill(
            name="math_skill",
            description="Math operations",
            code="import math; result = math.sqrt(parameters['value'])",
        )

        sandbox.register_skill(skill)

        result = await sandbox.execute_skill("math_skill", {"value": 16})

        assert result.success is True
        assert result.result == 4.0


class TestSkillSandboxErrors:
    """Tests for SkillSandbox error classes."""

    def test_sandbox_error(self):
        """Test base sandbox error."""
        with pytest.raises(SkillSandboxError):
            raise SkillSandboxError("Test error")

    def test_validation_error(self):
        """Test validation error inherits from sandbox error."""
        with pytest.raises(SkillSandboxError):
            raise SkillValidationError("Validation failed")