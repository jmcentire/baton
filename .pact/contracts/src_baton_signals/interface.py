# === Signal Aggregation Module (src_baton_signals) v1 ===
#  Dependencies: asyncio, collections, logging, pathlib, baton.adapter, baton.schemas, baton.state
# Cross-node signal aggregation system that collects signals from all adapters, persists them to JSONL files, and provides querying and per-path statistics capabilities.

# Module invariants:
#   - SIGNALS_FILE constant is 'signals.jsonl'
#   - _buffer is bounded by buffer_size (maxlen of deque)
#   - _running reflects the current state of the async loop
#   - Signals are persisted to JSONL immediately when collected
#   - Error status codes are defined as >= 400

class PathStat:
    """Per-path aggregation statistics including count, average latency, and error metrics"""
    path: str                                # required, The path being tracked
    count: int = 0                           # optional, Total number of signals for this path
    avg_latency_ms: float = 0.0              # optional, Average latency in milliseconds
    error_count: int = 0                     # optional, Count of errors (status_code >= 400)

class SignalAggregator:
    """Main class that collects signals from all adapters and persists them to JSONL"""
    _adapters: dict[str, Adapter]            # required, Dictionary of adapters to collect signals from
    _project_dir: Path                       # required, Project directory for storing signals
    _buffer: collections.deque[SignalRecord] # required, In-memory buffer of signals with max size
    _flush_interval: float                   # required, Interval in seconds between collection cycles
    _running: bool                           # required, Flag indicating if the aggregator loop is running

def PathStat.error_rate(
    self: PathStat,
) -> float:
    """
    Calculate the error rate as a fraction of errors to total count

    Postconditions:
      - Returns 0.0 if count is 0
      - Returns error_count/count if count > 0
      - Result is in range [0.0, 1.0]

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.__init__(
    self: SignalAggregator,
    adapters: dict[str, Adapter],
    project_dir: str | Path,
    buffer_size: int = 10000,
    flush_interval: float = 10.0,
) -> None:
    """
    Initialize a SignalAggregator with adapters, project directory, buffer size, and flush interval

    Postconditions:
      - _adapters is set to the provided adapters dictionary
      - _project_dir is converted to Path object
      - _buffer is initialized as deque with maxlen=buffer_size
      - _flush_interval is set to provided value
      - _running is initialized to False

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.is_running(
    self: SignalAggregator,
) -> bool:
    """
    Property that returns whether the aggregator loop is currently running

    Postconditions:
      - Returns current value of _running flag

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.buffer_size(
    self: SignalAggregator,
) -> int:
    """
    Property that returns the current number of signals in the buffer

    Postconditions:
      - Returns the length of _buffer

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.run(
    self: SignalAggregator,
) -> None:
    """
    Async loop that drains signals from adapters, appends to buffer and JSONL file at regular intervals

    Postconditions:
      - _running is set to False when loop exits
      - Final collection is performed before exit
      - All signals collected during run are in buffer and persisted to JSONL

    Errors:
      - asyncio_cancelled (asyncio.CancelledError): Task is cancelled

    Side effects: Sets _running to True on entry, Collects signals periodically via _collect(), Sleeps for _flush_interval seconds between collections, Sets _running to False on exit
    Idempotent: no
    """
    ...

def SignalAggregator.stop(
    self: SignalAggregator,
) -> None:
    """
    Signal the run loop to stop by setting _running flag to False

    Postconditions:
      - _running is set to False

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator._collect(
    self: SignalAggregator,
) -> None:
    """
    Drain signals from all adapters into buffer and persist each to JSONL file

    Postconditions:
      - All signals from all adapters are drained
      - Each signal is appended to _buffer
      - Each signal is persisted to JSONL file

    Side effects: Calls drain_signals() on each adapter, Appends signals to _buffer, Writes signals to JSONL file via append_jsonl()
    Idempotent: no
    """
    ...

def SignalAggregator.query(
    self: SignalAggregator,
    node: str | None = None,
    path: str | None = None,
    last_n: int = 100,
) -> list[SignalRecord]:
    """
    Query in-memory buffer with optional filtering by node and path, returning last N results

    Postconditions:
      - Returns at most last_n signals
      - All returned signals match node filter if provided
      - All returned signals contain path substring if provided
      - Signals are ordered by insertion time

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.path_stats(
    self: SignalAggregator,
    node: str | None = None,
) -> dict[str, PathStat]:
    """
    Compute per-path aggregation statistics including count, average latency, and error rate from buffer

    Postconditions:
      - Returns dict mapping path to PathStat
      - Each PathStat contains accurate count, avg_latency_ms, and error_count
      - error_count increments for signals with status_code >= 400
      - avg_latency_ms is calculated from all latency values for the path

    Side effects: none
    Idempotent: no
    """
    ...

def SignalAggregator.load_history(
    project_dir: str | Path,
    node: str | None = None,
    last_n: int | None = None,
) -> list[dict]:
    """
    Static method to read signal history from .baton/signals.jsonl with optional filtering

    Postconditions:
      - Returns list of signal records as dictionaries
      - All returned records match node filter if provided
      - At most last_n records returned if specified

    Side effects: none
    Idempotent: no
    """
    ...

# ── REQUIRED EXPORTS ──────────────────────────────────
# Your implementation module MUST export ALL of these names
# with EXACTLY these spellings. Tests import them by name.
# __all__ = ['PathStat', 'SignalAggregator']
