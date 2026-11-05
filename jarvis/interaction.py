"""One synchronous turn with independent, cached progress playback."""
from .progress import ProgressFeedback
from .telemetry import TurnTrace, mark, measure


def run_turn(assistant, speaker, text, *, trace=None, feedback=None, display=None, stopped=None):
    trace = trace or TurnTrace('text')
    stopped = stopped or (lambda: False)
    feedback = feedback or ProgressFeedback(speaker, enabled=speaker.settings.progress_enabled,
                                            delay=speaker.settings.progress_delay, stopped=stopped)
    outcome = 'error'
    sentences=None
    try:
        with trace.activate():
            if text:
                feedback.start(trace)
            with measure('respond'):
                if speaker.settings.llm_streaming and hasattr(getattr(assistant,'client',None),'stream_complete'):
                    from .sentence_speech import SentenceSpeech
                    sentences=SentenceSpeech(speaker,feedback,trace,stopped)
                    turn=assistant.respond(text,on_text=sentences.feed)
                else:turn = assistant.respond(text)
            mark('answer_ready')
            if display:
                display(turn)
            if sentences:sentences.finish(cancel=bool(turn.warning))

            def ready():
                feedback.stop()
                return not stopped()

            if not stopped() and not (sentences and sentences.started):
                speaker.speak(turn.text, before_playback=ready, stopped=stopped)
            outcome = 'cancelled' if stopped() else 'degraded' if turn.warning or sentences and sentences.failed else 'completed'
            return turn
    finally:
        if sentences:sentences.finish(cancel=True)
        feedback.stop()
        trace.finish(outcome)
