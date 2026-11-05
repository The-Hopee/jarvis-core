"""Local decisions for brief replies and progress; no model or network calls."""
import re


def normalized_command(text):
    text=re.sub(r'^\s*(?:джарвис|джервис|джарвиз|jarvis)\b[\s,:.!—-]*','',text,flags=re.I)
    return re.sub(r'\s+',' ',text).casefold().strip(' ,.!?')


HEARING_CHECK=re.compile(
    r'(?:как(?: ты| вы)? меня слыш(?:но|ишь|ите)|как слышно|'
    r'(?:(?:ты|вы) )?меня (?:хорошо )?слыш(?:но|ишь|ите)|'
    r'слышно меня|проверка (?:связи|микрофона)|при[её]м)')


def quick_reply(text):
    if HEARING_CHECK.fullmatch(normalized_command(text)):
        return 'Слышу вас, сэр.'
    return None


def needs_progress(text):
    """Brief commands stay quiet even when a provider takes a long time."""
    text=normalized_command(text)
    if not text or quick_reply(text):return False
    if re.search(r'\b(?:кратко|коротко|в двух словах|одним предложением)\b',text):return False
    if re.fullmatch(r'(?:привет|здравствуй\w*|я дома|ты на связи|как дела|'
                    r'спасибо|благодарю|хватит|отбой|выход|до свидания|'
                    r'(?:включи )?режим переписки|(?:заверши|закончи) переписку)',text):return False
    # Dictation and clarification are local, immediate operations. Do not inspect
    # message contents for academic/coding keywords when deciding to announce work.
    from .privacy import chat_action
    if chat_action(text):return False
    if re.search(r'\b(?:расскажи|расскажите|объясни|объясните|почему|докажи|'
                 r'разбери|разберите|сравни|проанализируй|исследуй|реализуй|'
                 r'спроектируй|разработай|подготовь|заполни|составь|напиши|создай|исправь)\b',text):return True
    if re.match(r'^(?:открой|открыть|запусти|включи|выключи|пауза|продолжи|'
                r'громкость|сверни|погода|какая погода|состояни[еяи] |'
                r'(?:проверь )?состояни[еяи] |сколько будет\b)',text):return False
    return len(text.split())>=12
