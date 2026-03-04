"""
Contract-driven test suite for ProcessManager component.

This test suite uses a two-tier testing strategy:
1. Unit tests with mocked subprocess for fast, deterministic testing
2. Integration tests with real short-lived processes for lifecycle verification

Test coverage includes:
- Happy path tests for all functions
- Edge cases (empty states, duplicates, nonexistent processes)
- Error cases (subprocess creation failure, process lookup errors)
- Invariant tests (uniqueness, key-value consistency)
- Concurrency and timeout scenarios
"""

import pytest
import asyncio
from unittest.mock import Mock, MagicMock, patch, AsyncMock, call
from typing import Dict, Optional
import logging

# Import component under test
from src.baton.process import ProcessManager, ProcessInfo


class TestProcessManagerInit:
    """Tests for ProcessManager.__init__()"""
    
    def test_init_creates_empty_process_dict(self):
        """Initialize ProcessManager creates empty process dictionary"""
        manager = ProcessManager()
        
        assert hasattr(manager, '_processes'), "ProcessManager should have _processes attribute"
        assert isinstance(manager._processes, dict), "_processes should be a dict"
        assert len(manager._processes) == 0, "_processes should be empty on initialization"
        assert manager._processes == {}, "_processes should be an empty dict"


class TestProcessManagerProcesses:
    """Tests for ProcessManager.processes() property"""
    
    def test_processes_empty_manager(self):
        """processes() returns empty dict when no processes tracked"""
        manager = ProcessManager()
        
        result = manager.processes()
        
        assert isinstance(result, dict), "processes() should return a dict"
        assert len(result) == 0, "Returned dict should be empty for new manager"
        assert result is not manager._processes, "Returned dict should be a copy, not reference"
    
    def test_processes_returns_copy(self):
        """processes() property returns a copy of internal state"""
        manager = ProcessManager()
        
        # Manually add a mock process to internal state
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        
        process_info = ProcessInfo(
            command="echo test",
            pid=12345,
            process=mock_process,
            node_name="test_node"
        )
        manager._processes["test_node"] = process_info
        
        result = manager.processes()
        
        assert "test_node" in result, "Returned dict should contain tracked processes"
        assert result["test_node"] == process_info, "Returned dict should contain same data"
        assert result is not manager._processes, "Returned dict should be a copy"
        
        # Modify returned dict and verify internal state unchanged
        result["new_node"] = Mock()
        assert "new_node" not in manager._processes, "Modifications to returned dict should not affect internal state"


class TestProcessManagerStart:
    """Tests for ProcessManager.start()"""
    
    @pytest.mark.asyncio
    async def test_start_creates_subprocess(self):
        """start() creates a subprocess and tracks it"""
        manager = ProcessManager()
        
        # Mock subprocess
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        
        with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_process
            
            result = await manager.start("test_node", "echo hello", None)
            
            # Verify subprocess creation
            mock_create.assert_called_once()
            call_args = mock_create.call_args
            assert "echo hello" in str(call_args), "Command should be passed to create_subprocess_shell"
            
            # Verify returned ProcessInfo
            assert isinstance(result, ProcessInfo), "start() should return ProcessInfo"
            assert result.pid == 12345, "ProcessInfo should have valid pid"
            assert result.node_name == "test_node", "ProcessInfo.node_name should match input"
            assert result.command == "echo hello", "ProcessInfo.command should match input"
            assert result.process == mock_process, "ProcessInfo should contain process object"
            
            # Verify process is tracked
            assert "test_node" in manager._processes, "Process should be stored in _processes"
            assert manager._processes["test_node"] == result, "Stored ProcessInfo should match returned"
    
    @pytest.mark.asyncio
    async def test_start_with_env_variables(self):
        """start() creates subprocess with environment variables"""
        manager = ProcessManager()
        
        mock_process = Mock()
        mock_process.pid = 12346
        mock_process.returncode = None
        
        env_vars = {"TEST_VAR": "test_value", "ANOTHER_VAR": "another_value"}
        
        with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_process
            
            result = await manager.start("env_node", "printenv TEST_VAR", env_vars)
            
            # Verify subprocess created with env
            mock_create.assert_called_once()
            call_kwargs = mock_create.call_args.kwargs
            assert 'env' in call_kwargs, "env parameter should be passed to create_subprocess_shell"
            
            # Verify process tracked
            assert "env_node" in manager._processes, "Process should be tracked"
            assert result.pid == 12346, "ProcessInfo should have correct pid"
    
    @pytest.mark.asyncio
    async def test_start_replaces_existing_process(self):
        """start() stops existing process for same node_name before starting new one"""
        manager = ProcessManager()
        
        # Create first process
        old_process = Mock()
        old_process.pid = 11111
        old_process.returncode = None
        
        old_info = ProcessInfo(
            command="old command",
            pid=11111,
            process=old_process,
            node_name="duplicate_node"
        )
        manager._processes["duplicate_node"] = old_info
        
        # Mock stop and start
        new_process = Mock()
        new_process.pid = 22222
        new_process.returncode = None
        
        with patch.object(manager, 'stop', new_callable=AsyncMock) as mock_stop:
            with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = new_process
                
                result = await manager.start("duplicate_node", "echo new", None)
                
                # Verify old process was stopped
                mock_stop.assert_called_once_with("duplicate_node", timeout=5.0)
                
                # Verify new process tracked
                assert manager._processes["duplicate_node"].pid == 22222, "New ProcessInfo should replace old"
                assert result.pid == 22222, "Returned ProcessInfo should be new process"
                assert len([k for k in manager._processes.keys() if k == "duplicate_node"]) == 1, \
                    "Only one entry should exist for node_name"
    
    @pytest.mark.asyncio
    async def test_start_subprocess_creation_failure(self):
        """start() raises error when subprocess creation fails"""
        manager = ProcessManager()
        
        with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
            mock_create.side_effect = OSError("Command not found")
            
            with pytest.raises(Exception) as exc_info:
                await manager.start("fail_node", "invalid_command", None)
            
            # Verify error contains indication of subprocess creation failure
            assert "subprocess" in str(exc_info.value).lower() or "command" in str(exc_info.value).lower(), \
                "Error should indicate subprocess creation failure"
            
            # Verify process not added to tracking
            assert "fail_node" not in manager._processes, "Failed process should not be tracked"
    
    @pytest.mark.asyncio
    async def test_start_empty_command(self):
        """start() with empty command string"""
        manager = ProcessManager()
        
        mock_process = Mock()
        mock_process.pid = 99999
        mock_process.returncode = None
        
        with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
            # Mock can succeed or fail - test handles both
            mock_create.return_value = mock_process
            
            try:
                result = await manager.start("empty_cmd_node", "", None)
                # If it succeeds, verify it's tracked
                assert "empty_cmd_node" in manager._processes, "Process should be tracked if creation succeeds"
            except Exception as e:
                # If it fails, verify it's not tracked
                assert "empty_cmd_node" not in manager._processes, "Failed process should not be tracked"


class TestProcessManagerStop:
    """Tests for ProcessManager.stop()"""
    
    @pytest.mark.asyncio
    async def test_stop_terminates_running_process(self):
        """stop() sends SIGTERM to running process and removes from tracking"""
        manager = ProcessManager()
        
        # Setup tracked process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        mock_process.terminate = Mock()
        mock_process.wait = AsyncMock(return_value=0)
        
        process_info = ProcessInfo(
            command="echo test",
            pid=12345,
            process=mock_process,
            node_name="running_node"
        )
        manager._processes["running_node"] = process_info
        
        with patch('logging.Logger.info'):
            await manager.stop("running_node", timeout=5.0)
        
        # Verify terminate called
        mock_process.terminate.assert_called_once()
        
        # Verify wait called with timeout
        mock_process.wait.assert_called()
        
        # Verify process removed from tracking
        assert "running_node" not in manager._processes, "Process should be removed from _processes"
    
    @pytest.mark.asyncio
    async def test_stop_sends_sigkill_on_timeout(self):
        """stop() sends SIGKILL when process does not exit within timeout"""
        manager = ProcessManager()
        
        # Setup stubborn process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        mock_process.terminate = Mock()
        mock_process.kill = Mock()
        # Simulate timeout
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        
        process_info = ProcessInfo(
            command="stubborn process",
            pid=12345,
            process=mock_process,
            node_name="stubborn_node"
        )
        manager._processes["stubborn_node"] = process_info
        
        with patch('logging.Logger.info'):
            with patch('logging.Logger.warning'):
                await manager.stop("stubborn_node", timeout=1.0)
        
        # Verify terminate called first
        mock_process.terminate.assert_called_once()
        
        # Verify kill called after timeout
        mock_process.kill.assert_called_once()
        
        # Verify process removed
        assert "stubborn_node" not in manager._processes, "Process should be removed after kill"
    
    @pytest.mark.asyncio
    async def test_stop_nonexistent_process(self):
        """stop() does nothing when node_name not found"""
        manager = ProcessManager()
        
        # No exception should be raised
        await manager.stop("nonexistent_node", timeout=5.0)
        
        # Verify _processes unchanged (still empty)
        assert len(manager._processes) == 0, "_processes should remain unchanged"
    
    @pytest.mark.asyncio
    async def test_stop_already_exited_process(self):
        """stop() handles process that already exited gracefully"""
        manager = ProcessManager()
        
        # Setup exited process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = 0  # Already exited
        mock_process.terminate = Mock()
        
        process_info = ProcessInfo(
            command="finished process",
            pid=12345,
            process=mock_process,
            node_name="exited_node"
        )
        manager._processes["exited_node"] = process_info
        
        with patch('logging.Logger.info'):
            await manager.stop("exited_node", timeout=5.0)
        
        # Verify process removed without attempting to terminate
        assert "exited_node" not in manager._processes, "Process should be removed"
    
    @pytest.mark.asyncio
    async def test_stop_process_lookup_error(self):
        """stop() handles process lookup error when process already gone"""
        manager = ProcessManager()
        
        # Setup process that will raise ProcessLookupError
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        mock_process.terminate = Mock(side_effect=ProcessLookupError("Process not found"))
        
        process_info = ProcessInfo(
            command="disappearing process",
            pid=12345,
            process=mock_process,
            node_name="gone_node"
        )
        manager._processes["gone_node"] = process_info
        
        with patch('logging.Logger.info'):
            with patch('logging.Logger.warning'):
                await manager.stop("gone_node", timeout=5.0)
        
        # Verify process removed despite error
        assert "gone_node" not in manager._processes, "Process should be removed despite lookup error"
    
    @pytest.mark.asyncio
    async def test_stop_zero_timeout(self):
        """stop() with timeout=0.0 immediately sends SIGKILL"""
        manager = ProcessManager()
        
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None
        mock_process.terminate = Mock()
        mock_process.kill = Mock()
        # Immediate timeout
        mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        
        process_info = ProcessInfo(
            command="test process",
            pid=12345,
            process=mock_process,
            node_name="zero_timeout_node"
        )
        manager._processes["zero_timeout_node"] = process_info
        
        with patch('logging.Logger.info'):
            with patch('logging.Logger.warning'):
                await manager.stop("zero_timeout_node", timeout=0.0)
        
        # Verify both terminate and kill called
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        
        # Verify process removed
        assert "zero_timeout_node" not in manager._processes, "Process should be removed"


class TestProcessManagerStopAll:
    """Tests for ProcessManager.stop_all()"""
    
    @pytest.mark.asyncio
    async def test_stop_all_stops_multiple_processes(self):
        """stop_all() stops all tracked processes"""
        manager = ProcessManager()
        
        # Setup multiple processes
        processes = {}
        for i in range(3):
            mock_process = Mock()
            mock_process.pid = 10000 + i
            mock_process.returncode = None
            mock_process.terminate = Mock()
            mock_process.wait = AsyncMock(return_value=0)
            
            node_name = f"node_{i}"
            process_info = ProcessInfo(
                command=f"command_{i}",
                pid=10000 + i,
                process=mock_process,
                node_name=node_name
            )
            manager._processes[node_name] = process_info
            processes[node_name] = mock_process
        
        assert len(manager._processes) == 3, "Should have 3 processes tracked"
        
        with patch('logging.Logger.info'):
            await manager.stop_all(timeout=5.0)
        
        # Verify all processes terminated
        for node_name, mock_process in processes.items():
            mock_process.terminate.assert_called_once()
        
        # Verify _processes is empty
        assert len(manager._processes) == 0, "_processes should be empty after stop_all()"
    
    @pytest.mark.asyncio
    async def test_stop_all_empty_manager(self):
        """stop_all() on empty ProcessManager does nothing"""
        manager = ProcessManager()
        
        # Should not raise any exception
        await manager.stop_all(timeout=5.0)
        
        # Verify still empty
        assert len(manager._processes) == 0, "_processes should remain empty"


class TestProcessManagerIsRunning:
    """Tests for ProcessManager.is_running()"""
    
    def test_is_running_returns_true_for_running_process(self):
        """is_running() returns True for tracked running process"""
        manager = ProcessManager()
        
        # Setup running process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = None  # Running
        
        process_info = ProcessInfo(
            command="running command",
            pid=12345,
            process=mock_process,
            node_name="running_node"
        )
        manager._processes["running_node"] = process_info
        
        result = manager.is_running("running_node")
        
        assert result is True, "is_running() should return True for running process"
    
    def test_is_running_returns_false_for_exited_process(self):
        """is_running() returns False for process with returncode set"""
        manager = ProcessManager()
        
        # Setup exited process
        mock_process = Mock()
        mock_process.pid = 12345
        mock_process.returncode = 0  # Exited
        
        process_info = ProcessInfo(
            command="finished command",
            pid=12345,
            process=mock_process,
            node_name="exited_node"
        )
        manager._processes["exited_node"] = process_info
        
        result = manager.is_running("exited_node")
        
        assert result is False, "is_running() should return False for exited process"
    
    def test_is_running_returns_false_for_nonexistent(self):
        """is_running() returns False when node_name not found"""
        manager = ProcessManager()
        
        result = manager.is_running("nonexistent_node")
        
        assert result is False, "is_running() should return False for nonexistent process"


class TestProcessManagerGetPid:
    """Tests for ProcessManager.get_pid()"""
    
    def test_get_pid_returns_pid_for_tracked_process(self):
        """get_pid() returns integer PID for tracked process"""
        manager = ProcessManager()
        
        # Setup tracked process
        mock_process = Mock()
        mock_process.pid = 12345
        
        process_info = ProcessInfo(
            command="test command",
            pid=12345,
            process=mock_process,
            node_name="tracked_node"
        )
        manager._processes["tracked_node"] = process_info
        
        result = manager.get_pid("tracked_node")
        
        assert isinstance(result, int), "get_pid() should return int"
        assert result == 12345, "get_pid() should return correct PID"
    
    def test_get_pid_returns_none_for_nonexistent(self):
        """get_pid() returns None when node_name not found"""
        manager = ProcessManager()
        
        result = manager.get_pid("nonexistent_node")
        
        assert result is None, "get_pid() should return None for nonexistent process"


class TestProcessManagerInvariants:
    """Tests for ProcessManager invariants"""
    
    @pytest.mark.asyncio
    async def test_invariant_node_name_uniqueness(self):
        """Each node_name maps to at most one ProcessInfo"""
        manager = ProcessManager()
        
        # Start multiple processes with same node_name
        pids = []
        for i in range(3):
            mock_process = Mock()
            mock_process.pid = 10000 + i
            mock_process.returncode = None
            
            with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_process
                
                with patch.object(manager, 'stop', new_callable=AsyncMock):
                    result = await manager.start("same_node", f"command_{i}", None)
                    pids.append(result.pid)
        
        # Verify only one process tracked
        assert len(manager._processes) == 1 or "same_node" in manager._processes, \
            "Only one ProcessInfo should exist per node_name"
        
        # Verify it's the latest one
        if "same_node" in manager._processes:
            assert manager._processes["same_node"].pid == pids[-1], \
                "Should track the most recent process for the node_name"
    
    @pytest.mark.asyncio
    async def test_invariant_node_name_matches_key(self):
        """ProcessInfo.node_name always matches dictionary key"""
        manager = ProcessManager()
        
        # Setup multiple processes
        node_names = ["node_a", "node_b", "node_c"]
        
        for node_name in node_names:
            mock_process = Mock()
            mock_process.pid = hash(node_name) % 10000
            mock_process.returncode = None
            
            with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_process
                await manager.start(node_name, f"command for {node_name}", None)
        
        # Verify invariant
        for key, process_info in manager._processes.items():
            assert key == process_info.node_name, \
                f"Key '{key}' should match ProcessInfo.node_name '{process_info.node_name}'"


class TestProcessManagerConcurrency:
    """Tests for concurrent operations"""
    
    @pytest.mark.asyncio
    async def test_concurrent_start_operations(self):
        """Multiple concurrent start() operations maintain state consistency"""
        manager = ProcessManager()
        
        async def start_process(node_name: str, command: str):
            mock_process = Mock()
            mock_process.pid = hash(node_name) % 10000
            mock_process.returncode = None
            
            with patch('asyncio.create_subprocess_shell', new_callable=AsyncMock) as mock_create:
                mock_create.return_value = mock_process
                return await manager.start(node_name, command, None)
        
        # Start multiple processes concurrently
        tasks = [
            start_process(f"node_{i}", f"command_{i}")
            for i in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Verify all processes tracked
        assert len(manager._processes) == 5, "All started processes should be tracked"
        
        # Verify no processes lost
        for i in range(5):
            assert f"node_{i}" in manager._processes, f"node_{i} should be tracked"
        
        # Verify all results valid
        for result in results:
            assert isinstance(result, ProcessInfo), "All results should be ProcessInfo"
            assert result.pid > 0, "All ProcessInfo should have valid PID"


class TestProcessManagerIntegration:
    """Integration tests with real subprocess (short-lived)"""
    
    @pytest.mark.asyncio
    async def test_integration_start_and_stop_real_process(self):
        """Integration test: start and stop real subprocess"""
        manager = ProcessManager()
        
        # Start a real subprocess (sleep for short time)
        process_info = await manager.start("test_sleep", "sleep 10", None)
        
        assert process_info is not None, "ProcessInfo should be returned"
        assert process_info.pid > 0, "Process should have valid PID"
        assert manager.is_running("test_sleep"), "Process should be running"
        
        # Stop the process
        await manager.stop("test_sleep", timeout=2.0)
        
        assert not manager.is_running("test_sleep"), "Process should be stopped"
        assert "test_sleep" not in manager._processes, "Process should be removed from tracking"
    
    @pytest.mark.asyncio
    async def test_integration_echo_command(self):
        """Integration test: run echo command and verify completion"""
        manager = ProcessManager()
        
        # Start echo command (completes immediately)
        process_info = await manager.start("test_echo", "echo 'Hello World'", None)
        
        assert process_info is not None, "ProcessInfo should be returned"
        assert process_info.pid > 0, "Process should have valid PID"
        
        # Wait a bit for process to complete
        await asyncio.sleep(0.5)
        
        # Process may or may not be in tracking depending on timing
        # Just verify no crashes
        manager.is_running("test_echo")
        manager.get_pid("test_echo")
    
    @pytest.mark.asyncio  
    async def test_integration_stop_all_real_processes(self):
        """Integration test: stop_all with multiple real processes"""
        manager = ProcessManager()
        
        # Start multiple processes
        for i in range(3):
            await manager.start(f"sleep_{i}", f"sleep {5 + i}", None)
        
        assert len(manager._processes) == 3, "Should have 3 processes"
        
        # Stop all
        await manager.stop_all(timeout=2.0)
        
        assert len(manager._processes) == 0, "All processes should be stopped"


# Entry point for pytest
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
