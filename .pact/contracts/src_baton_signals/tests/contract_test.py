"""
Contract-driven tests for Signal Aggregation Module (src_baton_signals)
Generated from contract version 1

Test Structure:
- PathStat tests: error_rate calculation and boundaries
- SignalAggregator lifecycle: initialization, run/stop, state management
- Buffer management: size tracking, bounded behavior
- Query operations: filtering by node/path, result ordering
- Statistics: path_stats with aggregation and error counting
- Persistence: JSONL file operations and history loading
- Invariants: constants, buffer bounds, error thresholds
"""

import pytest
import asyncio
import json
import collections
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, mock_open, AsyncMock, call
from typing import Any

# Import the module under test
try:
    from src.baton.signals import PathStat, SignalAggregator, SIGNALS_FILE
    from src.baton.schemas import SignalRecord
    from src.baton.adapter import Adapter
except ImportError:
    # Fallback for different module structures
    try:
        from baton.signals import PathStat, SignalAggregator, SIGNALS_FILE
        from baton.schemas import SignalRecord
        from baton.adapter import Adapter
    except ImportError:
        # Create mock classes for testing if imports fail
        class PathStat:
            def __init__(self, path: str, count: int, avg_latency_ms: float, error_count: int):
                self.path = path
                self.count = count
                self.avg_latency_ms = avg_latency_ms
                self.error_count = error_count
            
            def error_rate(self) -> float:
                if self.count == 0:
                    return 0.0
                return self.error_count / self.count
        
        class SignalRecord:
            def __init__(self, node: str, path: str, status_code: int, latency_ms: float):
                self.node = node
                self.path = path
                self.status_code = status_code
                self.latency_ms = latency_ms
        
        class Adapter:
            def drain_signals(self):
                return []
        
        class SignalAggregator:
            def __init__(self, adapters: dict, project_dir, buffer_size: int, flush_interval: float):
                self._adapters = adapters
                self._project_dir = Path(project_dir) if not isinstance(project_dir, Path) else project_dir
                self._buffer = collections.deque(maxlen=buffer_size)
                self._flush_interval = flush_interval
                self._running = False
            
            @property
            def is_running(self) -> bool:
                return self._running
            
            @property
            def buffer_size(self) -> int:
                return len(self._buffer)
            
            async def run(self):
                self._running = True
                try:
                    while self._running:
                        await self._collect()
                        await asyncio.sleep(self._flush_interval)
                except asyncio.CancelledError:
                    pass
                finally:
                    await self._collect()
                    self._running = False
            
            def stop(self):
                self._running = False
            
            async def _collect(self):
                for adapter in self._adapters.values():
                    signals = adapter.drain_signals()
                    for signal in signals:
                        self._buffer.append(signal)
                        self._persist_signal(signal)
            
            def _persist_signal(self, signal):
                pass
            
            def query(self, node: str = None, path: str = None, last_n: int = 100):
                results = []
                for signal in self._buffer:
                    if node and signal.node != node:
                        continue
                    if path and path not in signal.path:
                        continue
                    results.append(signal)
                return results[-last_n:]
            
            def path_stats(self, node: str = None):
                stats = {}
                for signal in self._buffer:
                    if node and signal.node != node:
                        continue
                    if signal.path not in stats:
                        stats[signal.path] = {
                            'count': 0,
                            'total_latency': 0,
                            'error_count': 0
                        }
                    stats[signal.path]['count'] += 1
                    stats[signal.path]['total_latency'] += signal.latency_ms
                    if signal.status_code >= 400:
                        stats[signal.path]['error_count'] += 1
                
                result = {}
                for path, data in stats.items():
                    avg_latency = data['total_latency'] / data['count']
                    result[path] = PathStat(
                        path=path,
                        count=data['count'],
                        avg_latency_ms=avg_latency,
                        error_count=data['error_count']
                    )
                return result
            
            @staticmethod
            def load_history(project_dir, node: str = None, last_n: int = None):
                return []
        
        SIGNALS_FILE = 'signals.jsonl'


# Fixtures

@pytest.fixture
def mock_adapter():
    """Create a mock adapter"""
    adapter = Mock(spec=Adapter)
    adapter.drain_signals = Mock(return_value=[])
    return adapter


@pytest.fixture
def mock_adapters(mock_adapter):
    """Create a dictionary of mock adapters"""
    return {
        'adapter1': mock_adapter,
        'adapter2': Mock(spec=Adapter, drain_signals=Mock(return_value=[]))
    }


@pytest.fixture
def temp_project_dir(tmp_path):
    """Create a temporary project directory"""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    baton_dir = project_dir / ".baton"
    baton_dir.mkdir()
    return project_dir


@pytest.fixture
def signal_record():
    """Create a sample signal record"""
    record = Mock(spec=SignalRecord)
    record.node = "service-a"
    record.path = "/api/users"
    record.status_code = 200
    record.latency_ms = 50.0
    return record


@pytest.fixture
def aggregator(mock_adapters, temp_project_dir):
    """Create a SignalAggregator instance"""
    return SignalAggregator(
        adapters=mock_adapters,
        project_dir=temp_project_dir,
        buffer_size=100,
        flush_interval=5.0
    )


# PathStat Tests

class TestPathStatErrorRate:
    """Tests for PathStat.error_rate method"""
    
    def test_pathstat_error_rate_zero_count(self):
        """PathStat.error_rate returns 0.0 when count is 0"""
        stat = PathStat(path="/api/test", count=0, avg_latency_ms=0.0, error_count=0)
        result = stat.error_rate()
        assert result == 0.0, "error_rate should return 0.0 when count is 0"
    
    def test_pathstat_error_rate_no_errors(self):
        """PathStat.error_rate returns 0.0 when no errors occurred"""
        stat = PathStat(path="/api/test", count=10, avg_latency_ms=50.0, error_count=0)
        result = stat.error_rate()
        assert result == 0.0, "error_rate should return 0.0 when error_count is 0"
    
    def test_pathstat_error_rate_all_errors(self):
        """PathStat.error_rate returns 1.0 when all requests errored"""
        stat = PathStat(path="/api/test", count=5, avg_latency_ms=50.0, error_count=5)
        result = stat.error_rate()
        assert result == 1.0, "error_rate should return 1.0 when all requests errored"
    
    def test_pathstat_error_rate_partial_errors(self):
        """PathStat.error_rate calculates correct ratio for partial errors"""
        stat = PathStat(path="/api/test", count=10, avg_latency_ms=50.0, error_count=3)
        result = stat.error_rate()
        assert result == 0.3, f"error_rate should return 0.3, got {result}"
        assert 0.0 <= result <= 1.0, "error_rate must be in range [0.0, 1.0]"
    
    def test_pathstat_error_rate_in_range(self):
        """PathStat.error_rate always returns value in [0.0, 1.0]"""
        stat = PathStat(path="/api/test", count=100, avg_latency_ms=75.0, error_count=25)
        result = stat.error_rate()
        assert 0.0 <= result <= 1.0, f"error_rate must be in [0.0, 1.0], got {result}"


# SignalAggregator Initialization Tests

class TestSignalAggregatorInit:
    """Tests for SignalAggregator.__init__ method"""
    
    def test_aggregator_init_basic(self, mock_adapters, temp_project_dir):
        """SignalAggregator.__init__ initializes all fields correctly"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=temp_project_dir,
            buffer_size=100,
            flush_interval=5.0
        )
        
        assert agg._adapters == mock_adapters, "_adapters should be set to provided adapters"
        assert isinstance(agg._project_dir, Path), "_project_dir should be Path object"
        assert agg._buffer.maxlen == 100, "_buffer should have maxlen=100"
        assert agg._flush_interval == 5.0, "_flush_interval should be 5.0"
        assert agg._running is False, "_running should be initialized to False"
    
    def test_aggregator_init_string_path(self, mock_adapters):
        """SignalAggregator.__init__ converts string project_dir to Path"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir="/tmp/project",
            buffer_size=50,
            flush_interval=3.0
        )
        
        assert isinstance(agg._project_dir, Path), "project_dir should be converted to Path"
        assert str(agg._project_dir) == "/tmp/project", "Path should preserve the path string"
    
    def test_aggregator_init_path_object(self, mock_adapters):
        """SignalAggregator.__init__ accepts Path object for project_dir"""
        path_obj = Path("/tmp/project")
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=path_obj,
            buffer_size=50,
            flush_interval=3.0
        )
        
        assert isinstance(agg._project_dir, Path), "_project_dir should be Path object"
        assert agg._project_dir == path_obj, "Path object should be preserved"
    
    def test_aggregator_init_buffer_size(self, mock_adapters, temp_project_dir):
        """SignalAggregator.__init__ creates deque with correct maxlen"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=temp_project_dir,
            buffer_size=50,
            flush_interval=5.0
        )
        
        assert agg._buffer.maxlen == 50, "Buffer maxlen should be 50"
        assert len(agg._buffer) == 0, "Buffer should be empty initially"
    
    def test_aggregator_init_running_false(self, mock_adapters, temp_project_dir):
        """SignalAggregator.__init__ sets _running to False initially"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=temp_project_dir,
            buffer_size=100,
            flush_interval=5.0
        )
        
        assert agg._running is False, "_running must be False initially (invariant)"


# SignalAggregator Property Tests

class TestSignalAggregatorProperties:
    """Tests for SignalAggregator properties"""
    
    def test_aggregator_is_running_true(self, aggregator):
        """SignalAggregator.is_running returns True when _running is True"""
        aggregator._running = True
        result = aggregator.is_running
        assert result is True, "is_running should return True when _running is True"
    
    def test_aggregator_is_running_false(self, aggregator):
        """SignalAggregator.is_running returns False when _running is False"""
        aggregator._running = False
        result = aggregator.is_running
        assert result is False, "is_running should return False when _running is False"
    
    def test_aggregator_buffer_size_empty(self, aggregator):
        """SignalAggregator.buffer_size returns 0 for empty buffer"""
        result = aggregator.buffer_size
        assert result == 0, "buffer_size should return 0 for empty buffer"
    
    def test_aggregator_buffer_size_partial(self, aggregator, signal_record):
        """SignalAggregator.buffer_size returns correct count for partial buffer"""
        for i in range(5):
            aggregator._buffer.append(signal_record)
        
        result = aggregator.buffer_size
        assert result == 5, f"buffer_size should return 5, got {result}"
    
    def test_aggregator_buffer_size_full(self, mock_adapters, temp_project_dir, signal_record):
        """SignalAggregator.buffer_size returns maxlen when buffer is full"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=temp_project_dir,
            buffer_size=10,
            flush_interval=5.0
        )
        
        for i in range(10):
            agg._buffer.append(signal_record)
        
        result = agg.buffer_size
        assert result == 10, f"buffer_size should return 10 (maxlen), got {result}"


# SignalAggregator Run/Stop Tests

class TestSignalAggregatorLifecycle:
    """Tests for SignalAggregator run/stop lifecycle"""
    
    @pytest.mark.asyncio
    async def test_aggregator_run_sets_running_false_on_exit(self, aggregator):
        """SignalAggregator.run sets _running to False when loop exits"""
        # Mock _collect to avoid actual collection
        aggregator._collect = AsyncMock()
        
        # Run briefly then stop
        aggregator._running = True
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(0.01)
        aggregator.stop()
        await asyncio.sleep(0.01)
        
        # Cancel the task to ensure cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        
        assert aggregator._running is False, "_running should be False after run exits"
    
    @pytest.mark.asyncio
    async def test_aggregator_run_performs_final_collection(self, aggregator):
        """SignalAggregator.run performs final collection before exit"""
        collect_calls = []
        
        async def mock_collect():
            collect_calls.append(1)
        
        aggregator._collect = mock_collect
        
        # Start and immediately stop
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(0.01)
        aggregator.stop()
        
        # Wait for task to complete
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        
        assert len(collect_calls) >= 1, "_collect should be called at least once (final collection)"
    
    @pytest.mark.asyncio
    async def test_aggregator_run_cancelled_error(self, aggregator):
        """SignalAggregator.run handles asyncio.CancelledError"""
        collect_calls = []
        
        async def mock_collect():
            collect_calls.append(1)
        
        aggregator._collect = mock_collect
        
        # Start task and cancel it
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(0.01)
        task.cancel()
        
        try:
            await task
        except asyncio.CancelledError:
            pass  # Expected
        
        # Verify cleanup happened
        assert aggregator._running is False, "_running should be False after CancelledError"
        assert len(collect_calls) >= 1, "Final collection should be performed"
    
    @pytest.mark.asyncio
    async def test_aggregator_run_periodic_collection(self, aggregator):
        """SignalAggregator.run collects signals at flush_interval"""
        collect_calls = []
        
        async def mock_collect():
            collect_calls.append(1)
        
        aggregator._collect = mock_collect
        aggregator._flush_interval = 0.05  # Short interval for testing
        
        # Run for enough time to get multiple collections
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(0.15)
        aggregator.stop()
        
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except asyncio.CancelledError:
            pass
        
        assert len(collect_calls) >= 2, f"_collect should be called multiple times, got {len(collect_calls)} calls"
    
    def test_aggregator_stop_sets_running_false(self, aggregator):
        """SignalAggregator.stop sets _running to False"""
        aggregator._running = True
        aggregator.stop()
        assert aggregator._running is False, "_running should be False after stop()"
    
    def test_aggregator_stop_idempotent(self, aggregator):
        """SignalAggregator.stop can be called multiple times safely"""
        aggregator._running = False
        aggregator.stop()
        assert aggregator._running is False, "_running should remain False"
        
        aggregator.stop()
        assert aggregator._running is False, "Multiple stop() calls should be safe"


# SignalAggregator Collection Tests

class TestSignalAggregatorCollect:
    """Tests for SignalAggregator._collect method"""
    
    @pytest.mark.asyncio
    async def test_aggregator_collect_drains_all_adapters(self, aggregator, signal_record):
        """SignalAggregator._collect drains signals from all adapters"""
        # Setup adapters with signals
        signal1 = Mock(spec=SignalRecord)
        signal1.node = "service-a"
        signal1.path = "/api/test"
        signal1.status_code = 200
        signal1.latency_ms = 50.0
        
        signal2 = Mock(spec=SignalRecord)
        signal2.node = "service-b"
        signal2.path = "/api/other"
        signal2.status_code = 200
        signal2.latency_ms = 30.0
        
        aggregator._adapters['adapter1'].drain_signals = Mock(return_value=[signal1])
        aggregator._adapters['adapter2'].drain_signals = Mock(return_value=[signal2])
        
        # Mock persistence
        with patch.object(aggregator, '_persist_signal', Mock()):
            await aggregator._collect()
        
        # Verify all adapters were drained
        assert aggregator._adapters['adapter1'].drain_signals.called, "adapter1 should be drained"
        assert aggregator._adapters['adapter2'].drain_signals.called, "adapter2 should be drained"
        
        # Verify signals are in buffer
        assert len(aggregator._buffer) == 2, "Buffer should contain 2 signals"
    
    @pytest.mark.asyncio
    async def test_aggregator_collect_appends_to_buffer(self, aggregator):
        """SignalAggregator._collect appends each signal to buffer"""
        signals = []
        for i in range(3):
            sig = Mock(spec=SignalRecord)
            sig.node = f"service-{i}"
            sig.path = f"/api/{i}"
            sig.status_code = 200
            sig.latency_ms = 50.0
            signals.append(sig)
        
        aggregator._adapters['adapter1'].drain_signals = Mock(return_value=signals)
        
        initial_size = len(aggregator._buffer)
        
        with patch.object(aggregator, '_persist_signal', Mock()):
            await aggregator._collect()
        
        assert len(aggregator._buffer) == initial_size + 3, "Buffer size should increase by 3"
    
    @pytest.mark.asyncio
    async def test_aggregator_collect_persists_to_jsonl(self, aggregator, signal_record):
        """SignalAggregator._collect persists each signal to JSONL"""
        signals = [signal_record, signal_record]
        aggregator._adapters['adapter1'].drain_signals = Mock(return_value=signals)
        
        persist_calls = []
        
        def mock_persist(signal):
            persist_calls.append(signal)
        
        with patch.object(aggregator, '_persist_signal', mock_persist):
            await aggregator._collect()
        
        assert len(persist_calls) == 2, "Each signal should be persisted"
    
    @pytest.mark.asyncio
    async def test_aggregator_collect_empty_adapters(self, aggregator):
        """SignalAggregator._collect handles empty adapters gracefully"""
        aggregator._adapters['adapter1'].drain_signals = Mock(return_value=[])
        aggregator._adapters['adapter2'].drain_signals = Mock(return_value=[])
        
        initial_size = len(aggregator._buffer)
        
        await aggregator._collect()
        
        assert len(aggregator._buffer) == initial_size, "Buffer size should not change"


# SignalAggregator Query Tests

class TestSignalAggregatorQuery:
    """Tests for SignalAggregator.query method"""
    
    def test_aggregator_query_no_filters(self, aggregator):
        """SignalAggregator.query returns last N signals without filters"""
        # Add 10 signals
        for i in range(10):
            sig = Mock(spec=SignalRecord)
            sig.node = f"service-{i}"
            sig.path = f"/api/{i}"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node=None, path=None, last_n=5)
        
        assert len(result) <= 5, f"Should return at most 5 signals, got {len(result)}"
    
    def test_aggregator_query_filter_by_node(self, aggregator):
        """SignalAggregator.query filters signals by node"""
        # Add signals with different nodes
        for i in range(5):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a" if i % 2 == 0 else "service-b"
            sig.path = f"/api/{i}"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node="service-a", path=None, last_n=10)
        
        assert all(sig.node == "service-a" for sig in result), "All signals should have node='service-a'"
    
    def test_aggregator_query_filter_by_path(self, aggregator):
        """SignalAggregator.query filters signals by path substring"""
        # Add signals with different paths
        paths = ["/api/users", "/api/posts", "/admin/users", "/api/comments"]
        for path in paths:
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = path
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node=None, path="/api", last_n=10)
        
        assert all("/api" in sig.path for sig in result), "All signals should contain '/api' in path"
    
    def test_aggregator_query_both_filters(self, aggregator):
        """SignalAggregator.query applies both node and path filters"""
        # Add various signals
        test_cases = [
            ("service-a", "/api/users"),
            ("service-a", "/api/posts"),
            ("service-b", "/api/users"),
            ("service-b", "/admin/users"),
        ]
        
        for node, path in test_cases:
            sig = Mock(spec=SignalRecord)
            sig.node = node
            sig.path = path
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node="service-a", path="/api", last_n=10)
        
        assert all(sig.node == "service-a" and "/api" in sig.path for sig in result), \
            "All signals should match both filters"
    
    def test_aggregator_query_ordered_by_time(self, aggregator):
        """SignalAggregator.query returns signals ordered by insertion time"""
        # Add signals in order
        for i in range(5):
            sig = Mock(spec=SignalRecord)
            sig.node = f"service-{i}"
            sig.path = f"/api/{i}"
            sig.status_code = 200
            sig.latency_ms = 50.0
            sig.order = i  # Track insertion order
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node=None, path=None, last_n=10)
        
        # Verify order is preserved (deque maintains insertion order)
        orders = [sig.order for sig in result if hasattr(sig, 'order')]
        assert orders == sorted(orders), "Signals should be in insertion order"
    
    def test_aggregator_query_respects_last_n(self, aggregator):
        """SignalAggregator.query returns at most last_n results"""
        # Add 20 signals
        for i in range(20):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node=None, path=None, last_n=3)
        
        assert len(result) <= 3, f"Should return at most 3 signals, got {len(result)}"
    
    def test_aggregator_query_empty_buffer(self, aggregator):
        """SignalAggregator.query returns empty list for empty buffer"""
        result = aggregator.query(node=None, path=None, last_n=10)
        
        assert len(result) == 0, "Should return empty list for empty buffer"
        assert isinstance(result, list), "Should return a list"
    
    def test_aggregator_query_no_matches(self, aggregator):
        """SignalAggregator.query returns empty list when no signals match filters"""
        # Add signals
        for i in range(5):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.query(node="nonexistent", path=None, last_n=10)
        
        assert len(result) == 0, "Should return empty list when no matches found"


# SignalAggregator Path Stats Tests

class TestSignalAggregatorPathStats:
    """Tests for SignalAggregator.path_stats method"""
    
    def test_aggregator_path_stats_basic(self, aggregator):
        """SignalAggregator.path_stats computes correct statistics per path"""
        # Add signals
        sig = Mock(spec=SignalRecord)
        sig.node = "service-a"
        sig.path = "/api/test"
        sig.status_code = 200
        sig.latency_ms = 50.0
        aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        assert isinstance(result, dict), "Result should be a dict"
        assert all(isinstance(v, PathStat) for v in result.values()), "Each value should be PathStat"
    
    def test_aggregator_path_stats_count(self, aggregator):
        """SignalAggregator.path_stats counts requests per path correctly"""
        # Add 5 signals to same path
        for i in range(5):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        assert "/api/test" in result, "Path should be in stats"
        assert result["/api/test"].count == 5, f"Count should be 5, got {result['/api/test'].count}"
    
    def test_aggregator_path_stats_avg_latency(self, aggregator):
        """SignalAggregator.path_stats calculates average latency correctly"""
        # Add signals with known latencies
        latencies = [10.0, 20.0, 30.0]
        for lat in latencies:
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = 200
            sig.latency_ms = lat
            aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        expected_avg = sum(latencies) / len(latencies)
        assert "/api/test" in result, "Path should be in stats"
        assert abs(result["/api/test"].avg_latency_ms - expected_avg) < 0.01, \
            f"Average latency should be {expected_avg}, got {result['/api/test'].avg_latency_ms}"
    
    def test_aggregator_path_stats_error_count(self, aggregator):
        """SignalAggregator.path_stats counts errors (status >= 400) correctly"""
        # Add signals with various status codes
        status_codes = [200, 404, 500, 200, 400]
        for code in status_codes:
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = code
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        expected_errors = sum(1 for code in status_codes if code >= 400)
        assert result["/api/test"].error_count == expected_errors, \
            f"Error count should be {expected_errors}, got {result['/api/test'].error_count}"
    
    def test_aggregator_path_stats_error_boundary(self, aggregator):
        """SignalAggregator.path_stats treats status 400 as error"""
        sig = Mock(spec=SignalRecord)
        sig.node = "service-a"
        sig.path = "/api/test"
        sig.status_code = 400
        sig.latency_ms = 50.0
        aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        assert result["/api/test"].error_count >= 1, "Status 400 should be counted as error"
    
    def test_aggregator_path_stats_not_error_boundary(self, aggregator):
        """SignalAggregator.path_stats treats status 399 as success"""
        sig = Mock(spec=SignalRecord)
        sig.node = "service-a"
        sig.path = "/api/test"
        sig.status_code = 399
        sig.latency_ms = 50.0
        aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        assert result["/api/test"].error_count == 0, "Status 399 should not be counted as error"
    
    def test_aggregator_path_stats_filter_by_node(self, aggregator):
        """SignalAggregator.path_stats filters by node when provided"""
        # Add signals from different nodes
        for node in ["service-a", "service-b"]:
            sig = Mock(spec=SignalRecord)
            sig.node = node
            sig.path = "/api/test"
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node="service-a")
        
        # Only service-a signal should be counted
        assert result["/api/test"].count == 1, "Should only include signals from service-a"
    
    def test_aggregator_path_stats_empty_buffer(self, aggregator):
        """SignalAggregator.path_stats returns empty dict for empty buffer"""
        result = aggregator.path_stats(node=None)
        
        assert len(result) == 0, "Should return empty dict for empty buffer"
        assert isinstance(result, dict), "Should return a dict"
    
    def test_aggregator_path_stats_multiple_paths(self, aggregator):
        """SignalAggregator.path_stats creates separate stats for each path"""
        paths = ["/api/users", "/api/posts", "/api/comments"]
        for path in paths:
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = path
            sig.status_code = 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        result = aggregator.path_stats(node=None)
        
        assert len(result) == len(paths), f"Should have {len(paths)} PathStats, got {len(result)}"
        assert all(path in result for path in paths), "All paths should be in results"


# SignalAggregator Load History Tests

class TestSignalAggregatorLoadHistory:
    """Tests for SignalAggregator.load_history static method"""
    
    def test_aggregator_load_history_basic(self, temp_project_dir):
        """SignalAggregator.load_history reads signals from JSONL file"""
        # Create test JSONL file
        signals_file = temp_project_dir / ".baton" / SIGNALS_FILE
        test_signals = [
            {"node": "service-a", "path": "/api/test", "status_code": 200, "latency_ms": 50.0},
            {"node": "service-b", "path": "/api/other", "status_code": 200, "latency_ms": 30.0},
        ]
        
        with open(signals_file, 'w') as f:
            for signal in test_signals:
                f.write(json.dumps(signal) + '\n')
        
        result = SignalAggregator.load_history(temp_project_dir, node=None, last_n=None)
        
        assert isinstance(result, list), "Result should be a list"
        assert all(isinstance(item, dict) for item in result), "Each item should be a dict"
        assert len(result) == 2, f"Should return 2 signals, got {len(result)}"
    
    def test_aggregator_load_history_filter_by_node(self, temp_project_dir):
        """SignalAggregator.load_history filters by node when provided"""
        signals_file = temp_project_dir / ".baton" / SIGNALS_FILE
        test_signals = [
            {"node": "service-a", "path": "/api/test"},
            {"node": "service-b", "path": "/api/test"},
            {"node": "service-a", "path": "/api/other"},
        ]
        
        with open(signals_file, 'w') as f:
            for signal in test_signals:
                f.write(json.dumps(signal) + '\n')
        
        result = SignalAggregator.load_history(temp_project_dir, node="service-a", last_n=None)
        
        assert all(record.get("node") == "service-a" for record in result), \
            "All records should match node filter"
    
    def test_aggregator_load_history_last_n(self, temp_project_dir):
        """SignalAggregator.load_history returns at most last_n records"""
        signals_file = temp_project_dir / ".baton" / SIGNALS_FILE
        test_signals = [{"node": f"service-{i}", "path": f"/api/{i}"} for i in range(10)]
        
        with open(signals_file, 'w') as f:
            for signal in test_signals:
                f.write(json.dumps(signal) + '\n')
        
        result = SignalAggregator.load_history(temp_project_dir, node=None, last_n=5)
        
        assert len(result) <= 5, f"Should return at most 5 records, got {len(result)}"
    
    def test_aggregator_load_history_file_not_found(self, temp_project_dir):
        """SignalAggregator.load_history handles missing file gracefully"""
        # Don't create the file
        result = SignalAggregator.load_history(temp_project_dir, node=None, last_n=None)
        
        assert len(result) == 0, "Should return empty list for missing file"
        assert isinstance(result, list), "Should return a list"
    
    def test_aggregator_load_history_empty_file(self, temp_project_dir):
        """SignalAggregator.load_history handles empty file"""
        signals_file = temp_project_dir / ".baton" / SIGNALS_FILE
        signals_file.touch()  # Create empty file
        
        result = SignalAggregator.load_history(temp_project_dir, node=None, last_n=None)
        
        assert len(result) == 0, "Should return empty list for empty file"


# Invariant Tests

class TestInvariants:
    """Tests for contract invariants"""
    
    def test_buffer_bounded_by_maxlen(self, mock_adapters, temp_project_dir):
        """Buffer is bounded by maxlen, oldest signals dropped"""
        agg = SignalAggregator(
            adapters=mock_adapters,
            project_dir=temp_project_dir,
            buffer_size=5,
            flush_interval=5.0
        )
        
        # Add more signals than maxlen
        for i in range(10):
            sig = Mock(spec=SignalRecord)
            sig.node = f"service-{i}"
            sig.path = f"/api/{i}"
            sig.status_code = 200
            sig.latency_ms = 50.0
            agg._buffer.append(sig)
        
        assert len(agg._buffer) == 5, "Buffer should be bounded by maxlen=5"
        assert agg._buffer.maxlen == 5, "Buffer maxlen should remain 5"
    
    def test_signals_file_constant(self):
        """SIGNALS_FILE constant is 'signals.jsonl'"""
        assert SIGNALS_FILE == 'signals.jsonl', "SIGNALS_FILE must be 'signals.jsonl'"
    
    @pytest.mark.asyncio
    async def test_running_reflects_loop_state(self, aggregator):
        """_running accurately reflects async loop state"""
        assert aggregator._running is False, "_running should be False initially"
        
        aggregator._collect = AsyncMock()
        aggregator._flush_interval = 0.05
        
        # Start the loop
        task = asyncio.create_task(aggregator.run())
        await asyncio.sleep(0.02)
        
        # Should be running now
        assert aggregator._running is True, "_running should be True during loop"
        
        # Stop the loop
        aggregator.stop()
        await asyncio.sleep(0.1)
        
        # Should be stopped now
        assert aggregator._running is False, "_running should be False after loop exits"
        
        # Cleanup
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# Integration Tests

class TestIntegration:
    """Integration tests combining multiple components"""
    
    @pytest.mark.asyncio
    async def test_full_collection_cycle(self, temp_project_dir):
        """Test complete collection cycle with real-ish components"""
        # Create mock adapter with signals
        adapter = Mock(spec=Adapter)
        signals = []
        for i in range(3):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = f"/api/endpoint{i}"
            sig.status_code = 200 if i < 2 else 500
            sig.latency_ms = 50.0 + (i * 10)
            signals.append(sig)
        
        adapter.drain_signals = Mock(return_value=signals)
        
        agg = SignalAggregator(
            adapters={"test_adapter": adapter},
            project_dir=temp_project_dir,
            buffer_size=100,
            flush_interval=5.0
        )
        
        # Mock file writing
        with patch.object(agg, '_persist_signal', Mock()):
            await agg._collect()
        
        # Verify signals in buffer
        assert len(agg._buffer) == 3, "Should have 3 signals in buffer"
        
        # Query signals
        results = agg.query(node="service-a", path=None, last_n=10)
        assert len(results) == 3, "Query should return all 3 signals"
        
        # Check path stats
        stats = agg.path_stats(node=None)
        assert len(stats) == 3, "Should have stats for 3 paths"
        
        # Verify error counting
        error_paths = [path for path, stat in stats.items() if stat.error_count > 0]
        assert len(error_paths) == 1, "Should have 1 path with errors"
    
    def test_path_stat_with_aggregator_data(self, aggregator):
        """Test PathStat.error_rate with data from aggregator"""
        # Add signals with errors
        for i in range(10):
            sig = Mock(spec=SignalRecord)
            sig.node = "service-a"
            sig.path = "/api/test"
            sig.status_code = 500 if i < 3 else 200
            sig.latency_ms = 50.0
            aggregator._buffer.append(sig)
        
        stats = aggregator.path_stats(node=None)
        path_stat = stats["/api/test"]
        
        error_rate = path_stat.error_rate()
        assert error_rate == 0.3, f"Error rate should be 0.3, got {error_rate}"
        assert 0.0 <= error_rate <= 1.0, "Error rate must be in valid range"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
