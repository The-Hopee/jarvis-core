"""Live ambiguous contact lookup only; never click a chat or send a message."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.vk_browser import PROFILE
from jarvis.vk_worker import VKPage
from jarvis.config import USER_DIR

def main():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        context=pw.chromium.launch_persistent_context(str(PROFILE),headless=True,locale='ru-RU',args=['--mute-audio'])
        try:
            page=context.new_page();vk=VKPage(page)
            result=vk.open_dialog('Сергей')
            report={'status':result.get('status'),'candidates':len(result.get('candidates',[])),
                    'ambiguous_recipient_not_opened':result.get('status')=='ambiguous' and result.get('recipient') is None}
            (USER_DIR/'benchmarks/stage09-vk-lookup.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
        finally:context.close()

if __name__=='__main__':main()
