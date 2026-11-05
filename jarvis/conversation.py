"""Small in-memory references for follow-up utterances, with bounded lifetimes."""
import re
import time

ORDINALS = {"первое": 1, "первый": 1, "первого": 1, "второе": 2, "второй": 2, "второго": 2,
            "третье": 3, "третий": 3, "третьего": 3, "четвертое": 4, "четвёртое": 4,
            "четвертый": 4, "четвёртый": 4, "пятое": 5, "пятый": 5}


def selection_number(text):
    text = text.casefold().strip(" .!?,")
    match = re.fullmatch(r"(?:(?:давай|включи|открой|покажи|выбери|номер|тогда)\s+)?([1-5]|" + "|".join(ORDINALS) + r")(?:\s+(?:видео|ролик|вариант))?", text)
    return (int(match[1]) if match[1].isdigit() else ORDINALS[match[1]]) if match else None


class Conversation:
    def __init__(self):
        self.clear()

    def clear(self):
        self.context = {}
        self.pending = None
        self.project_question = False
        self.asked_about_project = False
        self.updated_at = 0

    def expire(self):
        if self.updated_at and time.monotonic() - self.updated_at > 900:
            self.clear()
        if self.pending and time.monotonic() - self.pending["at"] > 120:
            self.pending = None

    def followup(self, text):
        self.expire()
        number = selection_number(text)
        if self.pending:
            pending, candidate = self.pending, None
            if number and number <= len(pending["candidates"]):
                candidate = pending["candidates"][number - 1]
            else:
                matches = [c for c in pending["candidates"] if text.casefold().strip(" .!?,@") in
                           {str(c.get("id", "")).casefold(), c.get("name", "").casefold(), c.get("username", "").casefold()}]
                if len(matches) == 1:
                    candidate = matches[0]
            if candidate:
                args = {**pending["arguments"], "recipient": str(candidate["id"])}
                self.pending = None
                return pending["name"], args, pending["can_send"]
        if number and self.context.get("youtube_query"):
            return "open_youtube_result", {"index": number}, False
        dialog = self.context.get("dialog")
        if dialog:
            message = re.fullmatch(r"(?:напиши|отправь)(?:\s+(?:ему|ей|им|туда)\s*[:,—-]?\s+|\s*[:,—-]\s*)(.+)", text, re.I | re.S)
            if message:
                return "send_message", {**dialog, "text": message[1].strip().strip('«»"')}, True
            if re.fullmatch(r"(?:прочитай|покажи)(?:\s+(?:его|её|ее|наш|нашу))?\s+(?:диалог|переписку|контекст|последние сообщения)", text, re.I):
                return "read_dialog", dialog, False
            if re.fullmatch(r"ответь(?:\s+(?:ему|ей|им))?(?:\s+(?:по контексту|в мо[её]м стиле|на сво[её] усмотрение))+", text, re.I):
                return "reply_in_my_style", dialog, True
        document = self.context.get("document")
        if document and re.fullmatch(r"(?:открой|покажи)(?:\s+(?:его|документ|этот документ))?(?:\s+в\s+(?:онли\s?офис|onlyoffice))?", text, re.I):
            return "open_document", {"path": document}, False
        return None

    def observe(self, name, arguments, output, can_send=False):
        if not output.get("ok"):
            return
        result = output["result"]
        self.updated_at = time.monotonic()
        if result.get("status") == "ambiguous" and result.get("candidates") and arguments:
            self.pending = {"name": name, "arguments": dict(arguments), "candidates": result["candidates"][:8],
                            "can_send": can_send, "at": self.updated_at}
            return
        if result.get("recipient") and arguments and arguments.get("platform"):
            self.context["dialog"] = {"platform": arguments["platform"], "recipient": str(result["recipient"]["id"])}
            self.context["recipient_name"] = result["recipient"].get("name", "")
            self.pending = None
        if name in {"open_youtube_video", "open_youtube_result", "search_youtube"} or result.get("video_id"):
            self.context["youtube_query"] = result.get("query", "")
            self.context["youtube_title"] = result.get("title", "")
        if name == "open_application" or result.get("app_id"):
            self.context["application"] = result.get("app_id") or arguments.get("app_id")
        if name in {"read_document", "create_document", "fill_document", "open_document"} and result.get("path"):
            self.context["document"] = result["path"]
