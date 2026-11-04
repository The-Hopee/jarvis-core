import re

PLATFORM = r'(?:телеграм(?:м[ае]?|[ае])?|telegram|вконтакте|вк|vk)'


def chat_intent(text):
    match = re.search(PLATFORM, text, re.I)
    if not match:
        return None
    platform = 'telegram' if match[0].casefold().startswith(('телеграм', 'telegram')) else 'vk'
    person = re.search(rf'(?:диалог|чат|переписк\w*)\s+с\s+(.+?)(?=\s+(?:в|во)\s+{PLATFORM}\b|\s+и\s+(?:напиши|ответь|отправь)|[,;]|$)', text, re.I)
    if not person:
        person = re.search(rf'(?:напиши|отправь)\s+(.+?)\s+(?:в|во)\s+{PLATFORM}\b', text, re.I)
    if not person:
        return None
    recipient = person[1].strip(' ,.!?')
    if not recipient or recipient.casefold() in {'ему', 'ей', 'им'}:
        return None
    args = {'platform': platform, 'recipient': recipient}
    if re.search(r'(?:ответь|напиши\s+ответ)', text, re.I) and re.search(r'мо[её]м\s+стиле|сво[её]\s+усмотрение|по\s+контексту', text, re.I):
        return 'reply_in_my_style', args
    message = re.search(r'(?:напиши|отправь)(?:\s+(?:ему|ей|им))?\s*[:,—-]\s*(.+)$', text, re.I)
    if not message:
        message = re.search(r'и\s+(?:напиши|отправь)(?:\s+(?:ему|ей|им))?\s+(.+)$', text, re.I)
    if not message:
        message = re.search(rf'(?:напиши|отправь)\s+.+?\s+(?:в|во)\s+{PLATFORM}\s*[:,—-]\s*(.+)$', text, re.I)
    if message:
        return 'send_message', {**args, 'text': message[1].strip().strip('«»"')}
    if re.search(r'прочитай|контекст|последни', text, re.I):
        return 'read_dialog', args
    return 'open_dialog', args
