"""Explicit live smoke: one diagnostic note to the owner's own VK Saved Messages."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import USER_DIR
from jarvis.vk_browser import PROFILE
from jarvis.vk_worker import VKPage

def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(PROFILE),headless=True,locale='ru-RU',args=['--mute-audio'])
        try:
            page=context.new_page();vk=VKPage(page)
            operation='home-self-test-'+uuid.uuid4().hex
            text='Jarvis: проверка отправки в собственное Избранное. '+operation[-8:]
            result=vk.send_message('Избранное',text,operation)
            duplicate=vk.send_message('Избранное',text,operation) if result.get('status')=='sent' else {}
            report={'status':result.get('status'),'self_only':result.get('recipient_id')=='self','duplicate_reused_receipt':duplicate.get('reused_receipt',False)}
            (USER_DIR/'benchmarks/stage09-vk-self-send.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
        finally:context.close()

if __name__=='__main__':main()
