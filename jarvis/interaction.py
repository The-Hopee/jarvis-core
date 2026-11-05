"""One synchronous turn with independent, cached progress playback."""
from .progress import ProgressFeedback
from .telemetry import TurnTrace, mark, measure


def run_turn(assistant, speaker, text, *, trace=None, feedback=None, display=None, stopped=None):
    trace = trace or TurnTrace('text')
    stopped = stopped or (lambda: False)
    feedback = feedback or ProgressFeedback(speaker, enabled=speaker.settings.progress_enabled,
                                            delay=speaker.settings.progress_delay, stopped=stopped)
    outcome = 'error'
    try:
        with trace.activate():
            if text:
                feedback.start(trace)
            with measure('respond'):
                turn = assistant.respond(text)
            mark('answer_ready')
            if display:
                display(turn)

            def ready():
                feedback.stop()
                return not stopped()

            if not stopped():
                speaker.speak(turn.text, before_playback=ready)
            outcome = 'cancelled' if stopped() else 'degraded' if turn.warning else 'completed'
            return turn
    finally:
        feedback.stop()
        trace.finish(outcome)
