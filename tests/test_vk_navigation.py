"""VK redirect/login regression checks with real Chromium and local routes."""
import re
import unittest
from unittest.mock import patch

from playwright.sync_api import sync_playwright, Error as BrowserError
from jarvis.vk_navigation import (VKLoginRequired, VKNavigationError, classify,
                                  confirm_login, navigate, wait_ready)

READY = '<button data-testid="header-profile-menu-button">Профиль</button><div data-testid="me_convo_list"></div>'
LOGIN = '<input type="password"><button>Войти</button>'


class VKNavigationTests(unittest.TestCase):
    def setUp(self):
        self.playwright=sync_playwright().start()
        self.addCleanup(self.playwright.stop)
        self.browser=self.playwright.chromium.launch(headless=True)
        self.addCleanup(self.browser.close)
        self.context=self.browser.new_context()
        self.requests=[]
        self.context.route(re.compile(r'https://vk\.(?:com|ru)/'),self.route)
        self.page=self.context.new_page()

    def route(self,route):
        url=route.request.url
        self.requests.append(url)
        if '/index.php' in url:
            html='<script>setTimeout(()=>location.replace("https://vk.ru/im"),180)</script>'
        elif '/login' in url:
            html=LOGIN
        elif '/blank' in url:
            html='<div>Загрузка</div>'
        else:
            html=READY
        route.fulfill(content_type='text/html; charset=utf-8',body=html)

    def test_confirmation_waits_for_index_redirect_without_another_navigation(self):
        self.page.goto('https://vk.ru/index.php?to=callback')
        result=confirm_login(self.context,timeout=2)
        self.assertIs(result,self.page)
        self.assertEqual(self.page.url,'https://vk.ru/im')
        self.assertEqual(self.requests,['https://vk.ru/index.php?to=callback','https://vk.ru/im'])

    def test_interrupted_goto_waits_for_redirect_destination_without_replaying(self):
        original=self.page.goto
        def interrupted(*_a,**_kw):
            original('https://vk.ru/index.php?to=callback')
            raise BrowserError('Navigation is interrupted by another navigation')
        with patch.object(self.page,'goto',side_effect=interrupted) as goto:
            self.assertEqual(navigate(self.page,'/im','messenger',timeout=2),'authenticated')
        goto.assert_called_once()
        self.assertEqual(self.page.url,'https://vk.ru/im')

    def test_existing_callback_settles_before_a_new_goto_is_attempted(self):
        self.page.goto('https://vk.ru/index.php?to=callback')
        with patch.object(self.page,'goto',side_effect=AssertionError('must not interrupt callback')):
            self.assertEqual(navigate(self.page,'/im','messenger',timeout=2),'authenticated')

    def test_confirmation_accepts_another_authenticated_tab_without_forcing_messenger(self):
        self.page.goto('https://vk.ru/login')
        authenticated=self.context.new_page()
        authenticated.goto('https://vk.ru/feed')
        with patch.object(authenticated,'goto',side_effect=AssertionError('must not navigate')):
            self.assertIs(confirm_login(self.context,timeout=0.3),authenticated)
        self.assertEqual(authenticated.url,'https://vk.ru/feed')

    def test_url_without_visible_account_markers_is_not_successful_login(self):
        self.page.goto('https://vk.ru/blank')
        with self.assertRaises(VKLoginRequired):
            confirm_login(self.context,timeout=0.1)
        self.assertFalse(self.page.is_closed())
        self.page.goto('https://vk.ru/login')
        with self.assertRaises(VKLoginRequired):
            wait_ready(self.page,'messenger',timeout=0.1)

    def test_modern_qr_landing_is_login_not_infinite_loading(self):
        self.page.goto('https://vk.ru/')
        self.page.set_content('<h1>Вход ВКонтакте</h1><button>Войти другим способом</button>')
        with self.assertRaises(VKLoginRequired):
            wait_ready(self.page,'music',timeout=0.1)

    def test_network_failures_are_friendly_errors_and_not_retried(self):
        with patch.object(self.page,'goto',side_effect=BrowserError('net::ERR_NAME_NOT_RESOLVED')) as goto:
            with self.assertRaises(VKNavigationError):
                navigate(self.page,'/im','messenger',timeout=0.3)
        goto.assert_called_once()

    def test_only_vk_hosts_and_service_markers_are_trusted(self):
        self.assertEqual(classify({'protocol':'https:','host':'attacker.example','path':'/im','ready':True,'profile':True}),'external')
        self.assertEqual(classify({'protocol':'https:','host':'vk.ru','path':'/im','ready':True},'messenger'),'loading')
        self.assertEqual(classify({'protocol':'https:','host':'vk.ru','path':'/im','ready':True,'messenger':True},'messenger'),'authenticated')


if __name__=='__main__':
    unittest.main()
