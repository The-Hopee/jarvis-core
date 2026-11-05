"""Explicit Russian VK music commands, separate from VK messenger intents."""
import re

VK = r'(?:vk\s+music|вк\s+музык[ае]|вконтакте|в\s+контакте|вк|vk)'
PLATFORM = re.compile(rf'\b{VK}\b', re.I)


def music_control(text):
    text = re.sub(rf'\s+(?:в|во|на)\s+{VK}\b', '', text, flags=re.I).strip(' .!?,')
    patterns = {
        'pause': r'(?:пауза|(?:поставь|поставить)\s+(?:(?:трек|музыку|песню)\s+)?на\s+паузу|(?:останови|выключи)\s+(?:музыку|трек|песню))',
        'resume': r'(?:продолжи(?:\s+(?:музыку|воспроизведение|трек))?|возобнови\s+(?:музыку|воспроизведение)|сними\s+(?:музыку\s+)?с\s+паузы)',
        'next': r'(?:(?:включи|поставь|переключи\s+на)\s+)?следующ(?:ий\s+(?:трек|трэк)|ую\s+песню)|дальше',
        'previous': r'(?:(?:включи|поставь|переключи\s+на)\s+)?предыдущ(?:ий\s+(?:трек|трэк)|ую\s+песню)',
        'status': r'(?:что\s+(?:сейчас\s+)?играет|какой\s+(?:сейчас\s+)?трек)',
    }
    for action, pattern in patterns.items():
        if re.fullmatch(pattern, text, re.I):
            return action
    return None


def music_intent(text):
    if not PLATFORM.search(text) or re.search(r'\b(?:диалог|переписк\w*|чат|напиши|отправь|ответь|видео|клип|ролик)\b', text, re.I):
        return None
    control = music_control(text)
    if control:
        return 'control_vk_music', {'action': control}
    source = re.sub(rf'\s+(?:в|во|на|из)\s+{VK}\b', '', text, flags=re.I).strip(' .!?,')
    # Also accept "включи в ВК ..." and "включи ВКонтакте трек ...".
    source = re.sub(rf'^(включи|поставь|найди|поищи|запусти)\s+{VK}\s+', r'\1 ', source, flags=re.I)
    from .conversation import selection_number
    index = selection_number(source)
    if index is not None:
        return 'play_vk_music_result', {'index': index}
    match = re.fullmatch(r'(включи|поставь|найди|поищи|запусти|воспроизведи|открой)\s+(?:мне\s+)?(?:(?:трек|трэк|песню|музыку|композицию)\s+)?(.+)', source, re.I)
    if not match:
        return None
    query = match[2].strip(' «»"')
    if not query or query.casefold() in {'музыка', 'музыку', 'трек', 'песню', 'вк', 'вконтакте', 'vk', 'vk music'}:
        return None
    if match[1].casefold() in {'найди', 'поищи', 'открой'} and not re.search(r'\b(?:трек|трэк|песн\w*|музык\w*|композици\w*)\b', text, re.I):
        return None
    return ('search_vk_music' if match[1].casefold() in {'найди', 'поищи'} else 'play_vk_music'), {'query': query}
