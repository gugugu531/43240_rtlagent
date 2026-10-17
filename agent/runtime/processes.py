"""Budget and evidence management for user component processes."""
from agent.core.process import ProcessRequest, ProcessResult


class ProcessService:
    """Public custom-action process API with budget and mandatory call evidence."""
    def __init__(self, budget, executor, cancellation, emit):
        self._budget, self._executor = budget, executor
        self._cancellation, self._emit = cancellation, emit
        self._sequence = 0

    def run(self, request: ProcessRequest) -> ProcessResult:
        from dataclasses import replace
        self._cancellation.raise_if_cancelled()
        request = replace(request, timeout_s=self._budget.timeout_s(request.timeout_s))
        self._sequence += 1
        identity = f'p{self._sequence:03d}'
        self._emit('started', process_id=identity, command=list(request.command), timeout_s=request.timeout_s)
        try:
            result = self._executor.run(request)
        except BaseException as exc:
            self._emit('failed', process_id=identity, error_type=type(exc).__name__)
            raise
        self._emit('result', process_id=identity, status=result.status, rc=result.rc,
                   elapsed_s=result.elapsed_s, excerpt=result.output[:2000])
        return result
