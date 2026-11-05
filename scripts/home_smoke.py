"""Live VK search/play/pause and Saved Messages opening; playback is muted."""
import json
from pathlib import Path
import sys
import uuid
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jarvis.config import USER_DIR
from jarvis.vk_browser import PROFILE
from jarvis.vk_music import VKMusicPage
from jarvis.vk_worker import VKPage

def main():
    from playwright.sync_api import sync_playwright
    result={}
    with sync_playwright() as pw:
        from jarvis.browser_privacy import protect,environment
        context=pw.chromium.launch_persistent_context(str(PROFILE),headless=True,locale='ru-RU',args=['--mute-audio'],service_workers='block',env=environment())
        blocked=set();protect(context,blocked_domains=blocked)
        try:
            music=VKMusicPage(context.new_page())
            try:
                found=music.search('Егор Крид',limit=2)
                result['music_results']=len(found.get('tracks',[]))
                result['playback_verified']=music.play_result(1,operation_id=uuid.uuid4().hex).get('playback_verified',False)
                result['audio_observed']=[{k:a[k] for k in ('paused','ready','time')} for a in music.audio()]
            finally:result['pause_verified']=music.control('pause',operation_id=uuid.uuid4().hex).get('pause_verified',False)
            opened=VKPage(context.new_page()).open_dialog('Избранное')
            result['saved_messages_opened']=opened.get('status')=='opened' and opened.get('recipient',{}).get('id')=='self'
            result['blocked_base_domains']=sorted(blocked)
        finally:context.close()
    (USER_DIR/'benchmarks/stage09-home-smoke.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
