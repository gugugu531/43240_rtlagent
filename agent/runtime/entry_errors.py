"""Keep required output contracts when configuration or task loading fails."""
from agent.composition.validation import ConfigError
from agent.recording.artifacts import atomic_write_text, atomic_write_json
from agent.recording.recorder import RunRecorder


def record_entry_error(output, error):
    atomic_write_text(output / 'solution.v', '')
    atomic_write_json(output / 'selection.json', {'candidate_id': None})
    recorder = RunRecorder(output)
    try:
        recorder.write_event('agent', 'error', error_type=type(error).__name__,
                             reason='configuration_or_entry_error',
                             excerpt=str(error) if isinstance(error, ConfigError) else 'entry preparation failed')
        recorder.write_event('agent', 'done', candidate_id=None, code_hash=None, bytes=0,
                             status='error', stop_reason='configuration_or_entry_error')
    finally:
        recorder.close()
