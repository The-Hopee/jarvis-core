"""DOCX creation and filling for ONLYOFFICE; source files are never overwritten.

Templates can contain {{placeholders}}, literal text, or Word content controls
with tag/alias names. Replacement spans may cross formatting runs. XML and user
document contents are data, never executable instructions.
"""
from datetime import datetime
from pathlib import Path
import re
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
import zipfile

from .http import ServiceError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
PART = re.compile(r"word/(?:document|header\d*|footer\d*)\.xml$")


def _read_package(path):
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ServiceError("Документ больше 20 MiB")
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > 2000 or sum(m.file_size for m in members) > 80 * 1024 * 1024:
                raise ServiceError("Распакованный документ превышает лимит")
            if len({m.filename for m in members}) != len(members):
                raise ServiceError("В документе повторяются имена XML-частей")
            data = {m.filename: archive.read(m) for m in members}
        if "word/document.xml" not in data:
            raise ServiceError("Файл не содержит текстовый документ DOCX")
        return data
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        raise ServiceError("Не удалось прочитать DOCX: повреждённый или зашифрованный файл") from exc


def _xml(raw):
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ServiceError("XML документа содержит неподдерживаемые объявления")
    try:
        # Preserve the original namespace prefixes, including mc:Ignorable values.
        from io import BytesIO
        for _, namespace in ET.iterparse(BytesIO(raw), events=("start-ns",)):
            prefix, uri = namespace
            if not re.fullmatch(r"ns\d+", prefix):
                ET.register_namespace(prefix, uri)
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ServiceError("Повреждён XML документа") from exc


def _set(node, text):
    node.text = text
    node.set(XML_SPACE, "preserve")


def _serialize(root, original):
    from io import BytesIO
    serialized = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # ElementTree drops unused declarations; mc:Ignorable and QName attribute
    # values can still refer to those namespaces. Keep their declarations.
    for _, (prefix, uri) in ET.iterparse(BytesIO(original), events=("start-ns",)):
        if prefix and prefix != "xml" and ("xmlns:" + prefix + "=").encode() not in serialized:
            root.set("xmlns:" + prefix, uri)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _replace_runs(paragraph, replacements, counts):
    nodes = list(paragraph.iter(W + "t"))
    joined = "".join(n.text or "" for n in nodes)
    if not joined:
        return
    # Find all matches on the original string. Inserted values are not templates
    # and must not be replaced again by another key.
    pattern = re.compile("|".join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)))
    offsets, offset = [], 0
    for node in nodes:
        offsets.append(offset)
        offset += len(node.text or "")
    for match in reversed(list(pattern.finditer(joined))):
        start, end = match.span()
        first = next(i for i, n in enumerate(nodes) if offsets[i] + len(n.text or "") > start)
        last = max(i for i in range(len(nodes)) if offsets[i] < end)
        prefix = (nodes[first].text or "")[:start - offsets[first]]
        suffix = (nodes[last].text or "")[end - offsets[last]:]
        _set(nodes[first], prefix + replacements[match[0]] + (suffix if first == last else ""))
        for index in range(first + 1, last):
            _set(nodes[index], "")
        if first != last:
            _set(nodes[last], suffix)
        counts[match[0]] += 1


class Documents:
    def __init__(self, settings, kernel):
        self.roots = tuple(Path(p).resolve() for p in settings.document_roots)
        self.output = self.roots[0] / "Jarvis"
        self.kernel = kernel

    def resolve(self, path):
        path = Path(path)
        candidates = [path.resolve()] if path.is_absolute() else [(root / path).resolve() for root in self.roots]
        matches = [p for p in candidates if any(p.is_relative_to(root) for root in self.roots)
                   and not str(p).startswith("\\\\") and p.is_file() and p.suffix.lower() == ".docx"]
        if len(matches) != 1:
            raise ServiceError("Нужен однозначный путь к DOCX внутри JARVIS_DOCUMENT_ROOTS; можно сначала вызвать list_documents")
        return matches[0]

    def list(self, query="", limit=30):
        found, scanned = [], 0
        for root in self.roots:
            if not root.is_dir():
                continue
            # Bounded two-level scan; never traverse junctions or symlink folders.
            folders = [root]
            for folder in folders:
                try:
                    children = sorted(folder.iterdir())
                except OSError:
                    continue
                for item in children:
                    scanned += 1
                    if scanned > 5000:
                        return {"documents": found, "truncated": True}
                    if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
                        continue
                    if item.is_dir() and len(item.relative_to(root).parts) < 3:
                        folders.append(item)
                    elif item.is_file() and item.suffix.lower() == ".docx" and query.casefold() in item.name.casefold():
                        found.append({"name": item.name, "path": str(item), "bytes": item.stat().st_size})
                        if len(found) >= limit:
                            return {"documents": found, "truncated": True}
        return {"documents": found, "truncated": False}

    def read(self, path):
        source = self.resolve(path)
        package, text, controls = _read_package(source), [], []
        for name, raw in package.items():
            if not PART.fullmatch(name):
                continue
            root = _xml(raw)
            text.extend("".join(t.text or "" for t in p.iter(W + "t")) for p in root.iter(W + "p"))
            for sdt in root.iter(W + "sdt"):
                properties = sdt.find(W + "sdtPr")
                if properties is not None:
                    for key in ("tag", "alias"):
                        label = properties.find(W + key)
                        if label is not None and label.get(W + "val"):
                            controls.append(label.get(W + "val"))
        full_text = "\n".join(text)
        return {"path": str(source), "text": full_text[:24000], "truncated": len(full_text) > 24000,
                "placeholders": sorted(set(re.findall(r"\{\{[^{}]{1,100}\}\}", full_text))),
                "content_controls": sorted(set(controls)), "untrusted_document_data": True}

    def _save(self, package, filename):
        filename = filename.strip()
        if not filename.lower().endswith(".docx"):
            filename += ".docx"
        if len(filename) > 150 or re.search(r'[<>:"/\\|?*\x00-\x1f]', filename) or filename.startswith("."):
            raise ServiceError("Укажите простое имя файла DOCX без пути и специальных символов")
        if filename.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
            raise ServiceError("Зарезервированное имя файла Windows")
        self.output.mkdir(parents=True, exist_ok=True)
        destination = (self.output / filename).resolve()
        if not any(destination.is_relative_to(root) for root in self.roots) or destination.parent != self.output.resolve():
            raise ServiceError("Файл должен находиться в каталоге документов Джарвиса")
        # 'xb' fails rather than replacing an existing document, even in a race.
        try:
            with destination.open("xb") as output:
                try:
                    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
                        for name, raw in package.items():
                            archive.writestr(name, raw)
                except Exception:
                    output.close()
                    destination.unlink(missing_ok=True)
                    raise
        except FileExistsError as exc:
            raise ServiceError("Файл с таким именем уже существует. Выберите другое имя.") from exc
        return destination

    def _result(self, destination, open_after):
        result = {"path": str(destination), "status": "created", "source_overwritten": False}
        if open_after:
            try:
                result["opened"] = self.kernel.call("open_document", {"path": str(destination)})["result"]
            except RuntimeError as exc:
                result["open_error"] = str(exc)[:300]
        return result

    def open(self, path):
        return self.kernel.call("open_document", {"path": str(self.resolve(path))})["result"]

    def create(self, text, filename="", title="", open_after=True):
        paragraphs = ([f'<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">{escape(title)}</w:t></w:r></w:p>'] if title else [])
        for line in text.splitlines() or [""]:
            paragraphs.append('<w:p><w:r><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="24"/></w:rPr>'
                              + '<w:t xml:space="preserve">' + escape(line) + '</w:t></w:r></w:p>')
        package = {
            "[Content_Types].xml": b'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            "_rels/.rels": b'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            "word/document.xml": ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="' + W[1:-1] + '"><w:body>'
                                  + "".join(paragraphs) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr></w:body></w:document>').encode("utf-8")}
        filename = filename or "Документ-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6] + ".docx"
        return self._result(self._save(package, filename), open_after)

    def fill(self, path, replacements=None, fields=None, filename="", open_after=True):
        source = self.resolve(path)
        replacements, fields = replacements or {}, fields or {}
        if not replacements and not fields:
            raise ServiceError("Укажите replacements для текста или fields для полей шаблона")
        if any(not key for key in (*replacements, *fields)):
            raise ServiceError("Имя поля или заменяемый текст не может быть пустым")
        package = _read_package(source)
        counts = {key: 0 for key in replacements}
        field_counts = {key: 0 for key in fields}
        for name, raw in list(package.items()):
            if not PART.fullmatch(name):
                continue
            root = _xml(raw)
            for paragraph in root.iter(W + "p"):
                joined = "".join(node.text or "" for node in paragraph.iter(W + "t"))
                field_placeholders = {}
                for match in re.finditer(r"\{\{([^{}]{1,100})\}\}", joined):
                    key = next((key for key in fields if key.casefold().strip() == match[1].casefold().strip()), None)
                    if key is not None:
                        field_placeholders[match[0]] = key
                if replacements or field_placeholders:
                    if set(replacements).intersection(field_placeholders):
                        raise ServiceError("Одно поле указано одновременно в replacements и fields")
                    combined = {**replacements, **{placeholder: fields[key] for placeholder, key in field_placeholders.items()}}
                    paragraph_counts = dict.fromkeys(combined, 0)
                    _replace_runs(paragraph, combined, paragraph_counts)
                    for key in replacements:
                        counts[key] += paragraph_counts[key]
                    for placeholder, key in field_placeholders.items():
                        field_counts[key] += paragraph_counts[placeholder]
            for sdt in root.iter(W + "sdt"):
                properties, content = sdt.find(W + "sdtPr"), sdt.find(W + "sdtContent")
                if properties is None or content is None:
                    continue
                labels = [p.get(W + "val") for p in properties if p.tag in {W + "tag", W + "alias"}]
                key = next((key for key in labels if key in fields), None)
                if key is None:
                    continue
                nodes = list(content.iter(W + "t"))
                if not nodes:
                    paragraph = content.find(W + "p")
                    parent = paragraph if paragraph is not None else content
                    nodes = [ET.SubElement(ET.SubElement(parent, W + "r"), W + "t")]
                _set(nodes[0], fields[key])
                for node in nodes[1:]:
                    _set(node, "")
                placeholder = properties.find(W + "showingPlcHdr")
                if placeholder is not None:
                    properties.remove(placeholder)
                field_counts[key] += 1
            package[name] = _serialize(root, raw)
        missing = [k for k, count in counts.items() if not count] + [k for k, count in field_counts.items() if not count]
        if missing:
            raise ServiceError("Не найдены поля/фрагменты: " + ", ".join(missing)[:350] + ". Копия не создавалась.")
        filename = filename or source.stem[:95] + "-заполнен-" + uuid.uuid4().hex[:6] + ".docx"
        result = self._result(self._save(package, filename), open_after)
        return {**result, "source_path": str(source), "replacements": counts, "fields": field_counts}
