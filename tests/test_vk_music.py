"""Actual Chromium audio, browser-session isolation and spoken music routing."""
import io
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jarvis.assistant import Assistant, describe_tool, local_intent
from jarvis.config import Settings
from jarvis.conversation import Conversation
from jarvis.http import ServiceError
from jarvis.ipc import KernelError
from jarvis.messaging import MessageLedger
from jarvis.music_intents import music_intent
from jarvis.services import LocalServices
from jarvis.tools import ToolRegistry
from jarvis.vk_browser import VKBrowser
from jarvis.vk_music import VKMusicPage
from jarvis.vk_worker import VKSession
from test_assistant import FakeKernel

HTML = '''<!doctype html><html lang="ru"><body>
<input placeholder="Поиск музыки" id="search">
<div data-testid="music-loading" hidden>Загрузка</div><div id="tracks"></div>
<div data-testid="music-player"><span data-testid="track-title" id="now-title"></span><span data-testid="track-artist" id="now-artist"></span>
<button data-testid="player-play" onclick="if(current>=0){if(player.paused)player.play();else player.pause()}">Play</button></div>
<button data-testid="player-next" onclick="select((current+1)%songs.length)">Следующий трек</button>
<button data-testid="player-previous" onclick="select((current+songs.length-1)%songs.length)">Предыдущий трек</button>
<script>
const songs=[{id:'1_10',title:'Альфа',artist:'Исполнитель'},{id:'1_20',title:'Бета',artist:'Исполнитель'}];
window.player=new Audio(); window.clicks=0; window.stall=false; let current=-1;
function states() { document.querySelector('#now-title').textContent=songs[current]?.title||'';
 document.querySelector('#now-artist').textContent=songs[current]?.artist||'';
 document.querySelectorAll('.audio_row').forEach(r=>{
 const active=songs[current]?.id===r.dataset.fullId && !player.paused;
 r.dataset.playing=active?'true':'false';
 r.querySelector('button').setAttribute('aria-label',active?'Пауза':'Play');
}); }
function render(query='') {
 document.querySelector('#tracks').innerHTML='';
 for(const song of songs.filter(t=>(t.artist+' '+t.title).toLowerCase().includes(query.toLowerCase()))) {
   const row=document.createElement('div');row.className='audio_row';row.dataset.fullId=song.id;
   row.dataset.audio='PRIVATE_STREAM_URL_AND_TOKEN';
   row.innerHTML='<span class="audio_row__performers"></span><span class="audio_row__title_inner"></span><button data-testid="track-play" aria-label="Play">▶</button><button data-testid="add-track">Добавить</button>';
   row.querySelector('.audio_row__performers').textContent=song.artist;
   row.querySelector('.audio_row__title_inner').textContent=song.title;
   row.querySelector('[data-testid="track-play"]').onclick=()=>select(songs.indexOf(song));
   document.querySelector('#tracks').append(row);
 } states();
}
function select(index) {
 window.clicks++;
 if(window.stall){document.querySelectorAll('.audio_row')[index].dataset.playing='true';return;}
 if(current===index && !player.paused){player.pause();return;}
 if(current!==index){player.pause();player.src='/test-'+index+'.wav';current=index;}
 player.play().catch(()=>{});
}
player.addEventListener('play',states);player.addEventListener('pause',states);
document.querySelector('#search').addEventListener('keydown',e=>{
 if(e.key==='Enter'){
   document.querySelector('[data-testid="music-loading"]').hidden=false;
   setTimeout(()=>{render(e.target.value);document.querySelector('[data-testid="music-loading"]').hidden=true;},100);
 }
}); render();
</script></body></html>'''

DIALOG = '''<input id="im_dialogs_search"><a href="/im?sel=42" onclick="event.preventDefault();history.replaceState({},'',this.href);document.querySelector('.im-page--title-main').textContent='Петя'">
<span class="im-dialog--name">Петя</span></a><div class="im-page--title-main"></div>'''

MODERN = '''<input data-testid="search_top_input" placeholder="Поиск" id="global-search">
<input data-testid="search_audio_input" placeholder="Поиск музыки" id="music-search">
<section data-testid="AudioCatalog_SectionMyTracks"><div data-testid="MusicTrackRow"><div data-testid="audiorow-tappable" role="button" onclick="document.body.dataset.wrongTrack='true'">
<div data-testid="MusicTrackRow_Title">Посторонняя рекомендация</div><div data-testid="MusicTrackRow_Authors">Другой исполнитель</div></div></div></section>
<section data-testid="AudioCatalog_SectionAllTracks"><div data-testid="MusicTrackRow"><div id="target-play" data-testid="audiorow-tappable" role="button" tabindex="0" aria-label="Воспроизвести" onclick="player.play()">
<div data-testid="MusicTrackRow_PlaybackControls">▶</div>
<div data-testid="MusicTrackRow_Title">Альфа</div><div data-testid="MusicTrackRow_Authors">Исполнитель</div></div></div></section>
<script>window.player=new Audio('/test-modern.wav');
player.addEventListener('playing',()=>document.querySelector('#target-play').setAttribute('aria-label','Пауза'));
player.addEventListener('pause',()=>document.querySelector('#target-play').setAttribute('aria-label','Воспроизвести'));
document.querySelector('#music-search').onkeydown=e=>{if(e.key==='Enter')document.body.dataset.musicQuery=e.target.value};
document.querySelector('#global-search').onkeydown=()=>document.body.dataset.wrongSearch='true';</script>'''


def audio_bytes():
    data=io.BytesIO()
    with wave.open(data,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000)
        wav.writeframes(b'\x00\x00'*8000*12)
    return data.getvalue()


class MusicRoutingTests(unittest.TestCase):
    def test_spoken_vk_music_and_youtube_requests_stay_separate(self):
        for text in ('включи трек Альфа в вк', 'включи в ВК трек Альфа', 'поставь песню Альфа во ВКонтакте'):
            self.assertEqual(local_intent(text), ('play_vk_music', {'query':'Альфа'}))
        self.assertEqual(local_intent('найди трек Альфа в VK Music'), ('search_vk_music', {'query':'Альфа'}))
        self.assertEqual(local_intent('поставь музыку на паузу в вк'), ('control_vk_music', {'action':'pause'}))
        self.assertEqual(local_intent('включи вторую песню в вк'), ('play_vk_music_result', {'index':2}))
        self.assertEqual(local_intent('Джарвис, открой на ютубе видео Егора Крида'), ('open_youtube_video', {'query':'Егора Крида'}))
        self.assertEqual(local_intent('открой вк'), ('open_website', {'target':'вк'}))
        self.assertIsNone(music_intent('напиши Пете в вк: включи трек Альфа'))
        self.assertIsNone(music_intent('включи видео в вк'))
        self.assertIsNone(music_intent('найди Петю в вк'))

    def test_followup_tracks_uses_last_service_and_music_guard_survives_context_reset(self):
        memory=Conversation()
        memory.observe('search_youtube', {}, {'ok':True,'result':{'query':'cats','videos':[]}})
        memory.observe('search_vk_music', {}, {'ok':True,'result':{'query':'artist','tracks':[{'title':'song'}]}})
        self.assertEqual(memory.followup('включи второй трек')[:2], ('play_vk_music_result',{'index':2}))
        self.assertEqual(memory.followup('включи вторую песню')[:2], ('play_vk_music_result',{'index':2}))
        self.assertEqual(memory.followup('пауза')[:2], ('control_vk_music',{'action':'pause'}))
        memory.observe('play_vk_music_result', {}, {'ok':True,'result':{'track':{'title':'song'},'status':'play_requested'}})
        self.assertTrue(memory.music_playing)
        memory.clear()
        self.assertTrue(memory.music_playing)
        memory.observe('control_vk_music', {}, {'ok':True,'result':{'status':'paused','pause_verified':True}})
        self.assertFalse(memory.music_playing)
        memory.observe('open_youtube_video', {}, {'ok':True,'result':{'query':'cats','video_id':'abcdefghijk'}})
        self.assertEqual(memory.followup('включи второе')[:2], ('open_youtube_result',{'index':2}))
        self.assertIsNone(memory.followup('пауза'))
        self.assertIsNone(memory.followup('включи вторую песню'))

    def test_media_choice_never_continues_an_old_pending_message(self):
        memory=Conversation()
        memory.observe('send_message', {'platform':'vk','recipient':'Петя','text':'Привет'},
                       {'ok':True,'result':{'status':'ambiguous','candidates':[{'id':'1','name':'Петя Один'},{'id':'2','name':'Петя Два'}]}},True)
        self.assertIsNone(memory.followup('включи второй трек'))
        memory.observe('search_vk_music', {}, {'ok':True,'result':{'query':'artist','tracks':[{'title':'song'}]}})
        self.assertIsNone(memory.pending)
        self.assertEqual(memory.followup('второй')[:2],('play_vk_music_result',{'index':2}))

    def test_registry_passes_current_operation_and_idle_pause_does_not_open_browser(self):
        registry=ToolRegistry(FakeKernel(),LocalServices(Settings(),FakeKernel()))
        self.addCleanup(registry.close)
        registry.begin_turn('включи Альфа в вк')
        with patch.object(registry.vk,'play_music',return_value={'status':'play_requested','playback_verified':False}) as play:
            result=registry.execute('play_vk_music',{'query':'Альфа'})
        self.assertTrue(result['ok'])
        self.assertEqual(play.call_args.kwargs['operation_id'],registry.request_id)
        self.assertNotIn('играет',describe_tool('play_vk_music',result))
        with patch.object(registry.vk,'call',side_effect=AssertionError('must not launch')):
            self.assertEqual(registry.vk.control_music('pause')['status'],'idle')

    def test_login_error_releases_profile_without_retrying_command(self):
        browser=VKBrowser()
        process=Mock()
        process.call.side_effect=KernelError('vk_login_required','Нужен вход')
        browser.process=process
        with self.assertRaises(KernelError):
            browser.search_music('Исполнитель')
        process.close.assert_called_once()
        process.call.assert_called_once()
        self.assertIsNone(browser.process)


class BrowserMusicTests(unittest.TestCase):
    def setUp(self):
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch(headless=True)
        self.addCleanup(self.browser.close)
        self.context=self.browser.new_context()
        self.context.route(re.compile(r'https://vk\.(?:com|ru)/'),self.route)
        self.page=self.context.new_page()
        self.page.goto('https://vk.com/audio')
        self.music=VKMusicPage(self.page,timeout=1.2)

    def route(self,route):
        if '/test-' in route.request.url:
            route.fulfill(content_type='audio/wav',body=audio_bytes())
        else:
            route.fulfill(content_type='text/html; charset=utf-8',body=MODERN if 'modern=1' in route.request.url else DIALOG if '/im' in route.request.url else HTML)

    def test_current_vk_widgets_use_music_search_instead_of_header_search(self):
        self.page.goto('https://vk.com/audio?modern=1')
        music=VKMusicPage(self.page,timeout=1.2)
        found=music.search('Исполнитель')
        self.assertEqual(found['tracks'][0]['title'],'Альфа')
        self.assertEqual(self.page.locator('#global-search').input_value(),'')
        self.assertEqual(self.page.locator('body').get_attribute('data-music-query'),'Исполнитель')
        self.assertTrue(music.play_result(1)['playback_verified'])
        self.assertIsNone(self.page.locator('body').get_attribute('data-wrong-track'))
        self.assertTrue(music.control('pause')['pause_verified'])
        self.assertTrue(music.control('resume')['playback_verified'])

    def test_playing_track_removed_from_results_is_verified_by_current_player(self):
        self.music.search('Исполнитель')
        self.page.evaluate('''() => {
          const top=document.createElement('div');top.dataset.testid='TopAudioPlayer_Title';document.body.append(top);
          const original=select;window.select=index=>{original(index);top.innerText=songs[index].artist+' — '+songs[index].title;document.querySelector('#tracks').innerHTML='';};
        }''')
        self.assertTrue(self.music.play_result(1)['playback_verified'])
        self.assertTrue(self.music.control('pause')['pause_verified'])

    def test_real_detached_audio_search_play_pause_resume_next_and_previous(self):
        found=self.music.search('Исполнитель')
        self.assertEqual([t['title'] for t in found['tracks']],['Альфа','Бета'])
        self.assertNotIn('PRIVATE_STREAM',json.dumps(found))
        result=self.music.play_result(1,operation_id='first')
        self.assertTrue(result['playback_verified'],result)
        self.assertEqual(self.page.locator('audio').count(),0)
        again=self.music.play_result(1,operation_id='first')
        self.assertTrue(again['reused_receipt'])
        self.assertEqual(self.page.evaluate('window.clicks'),1)
        self.assertTrue(self.music.play_result(1,operation_id='second-user-turn')['playback_verified'])
        self.assertEqual(self.page.evaluate('window.clicks'),1)
        self.assertTrue(self.music.control('pause')['pause_verified'])
        self.assertTrue(self.music.control('resume')['playback_verified'])
        self.assertEqual(self.music.control('next')['track']['title'],'Бета')
        self.assertEqual(self.music.control('previous')['track']['title'],'Альфа')
        self.assertEqual(self.music.control('status')['status'],'playing')

    def test_no_fake_success_for_stalled_player_and_no_toggle_on_duplicate_attempt(self):
        self.music.search('Альфа')
        self.page.evaluate('window.stall=true')
        self.music.timeout=0.35
        result=self.music.play_result(1,operation_id='one')
        self.assertFalse(result['playback_verified'])
        self.assertEqual(result['status'],'play_requested')
        self.assertTrue(result['do_not_retry'])
        self.music.play_result(1,operation_id='one')
        self.assertEqual(self.page.evaluate('window.clicks'),1)

    def test_searching_does_not_stop_track_and_resume_uses_player_outside_results(self):
        self.music.play('Альфа')
        self.music.search('Бета')
        self.assertEqual(self.music.control('status')['track']['title'],'Альфа')
        self.assertTrue(self.music.control('pause')['pause_verified'])
        resumed=self.music.control('resume')
        self.assertTrue(resumed['playback_verified'])
        self.assertEqual(resumed['track']['title'],'Альфа')

    def test_old_audio_cannot_confirm_a_new_track_that_failed_to_start(self):
        self.music.play('Исполнитель')
        self.page.evaluate('window.stall=true')
        self.music.timeout=0.35
        result=self.music.play_result(2,operation_id='new-stalled-track')
        self.assertFalse(result['playback_verified'])
        self.assertEqual(result['track']['title'],'Бета')
        retried=self.music.play_result(2,operation_id='another-user-turn')
        self.assertFalse(retried['playback_verified'])

    def test_manual_track_change_is_observed_before_next_command(self):
        self.music.play('Исполнитель')
        self.page.locator('[data-full-id="1_20"] [data-testid="track-play"]').click()
        self.page.wait_for_timeout(200)
        result=self.music.control('next')
        self.assertTrue(result['playback_verified'])
        self.assertEqual(result['track']['title'],'Альфа')

    def test_reordered_results_and_empty_search_never_play_wrong_track(self):
        self.music.search('Исполнитель')
        self.page.evaluate('const list=document.querySelector("#tracks");list.prepend(list.lastElementChild)')
        with self.assertRaisesRegex(ServiceError,'изменился'):
            self.music.play_result(1)
        self.assertEqual(self.page.evaluate('window.clicks'),0)
        self.music.timeout=0.5
        with self.assertRaises(ServiceError):
            self.music.search('Несуществующий исполнитель')
        self.assertEqual(self.music.results,[])

    def test_login_required_is_reported_before_attempting_playback(self):
        self.page.set_content('<input type="password"><button>Войти</button>')
        with self.assertRaisesRegex(ServiceError,'--vk-login'):
            self.music.play('Альфа')

    def test_messenger_navigation_uses_another_page_without_stopping_music(self):
        with tempfile.TemporaryDirectory() as tmp, patch('jarvis.vk_worker.MessageLedger',lambda:MessageLedger(Path(tmp)/'test.sqlite')):
            session=VKSession(self.context)
            result=session.dispatch('play_music',{'query':'Альфа','operation_id':'session'})
            self.assertTrue(result['playback_verified'])
            music_page=session.music.page
            opened=session.dispatch('open_dialog',{'recipient':'Петя'})
            self.assertEqual(opened['recipient']['name'],'Петя')
            self.assertNotEqual(session.dialogs.page,music_page)
            self.assertIn('/audio',music_page.url)
            self.assertEqual(session.dispatch('control_music',{'action':'status'})['status'],'playing')


if __name__=='__main__':
    unittest.main()
