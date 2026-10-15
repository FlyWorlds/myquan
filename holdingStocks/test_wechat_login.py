from __future__ import annotations

import io
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from wechat_login import WechatLogin
from transport.http import build_watch_request_handler


class LoginTests(unittest.TestCase):
    def test_relogin_uses_only_the_same_recipient_account(self):
        from wechat_notify import _current_weixin_account
        with TemporaryDirectory() as temp, patch.dict(os.environ, {'OPENCLAW_STATE_DIR': temp}):
            state = Path(temp)/'openclaw-weixin'
            (state/'accounts').mkdir(parents=True)
            (state/'accounts.json').write_text(json.dumps(['new-im-bot']))
            path = state/'accounts/new-im-bot.json'
            path.write_text(json.dumps(dict(userId='same-user', token='SECRET')))
            cfg = dict(channel='openclaw-weixin', account='old-im-bot', target='same-user@im.wechat')
            updated = _current_weixin_account(cfg)
            self.assertEqual(updated['account'], 'new-im-bot')
            self.assertEqual(updated['target'], cfg['target'])
            self.assertEqual(cfg['account'], 'old-im-bot')
            path.write_text(json.dumps(dict(userId='different-user', token='SECRET')))
            self.assertEqual(_current_weixin_account(cfg), cfg)
            path.write_text(json.dumps(dict(userId='same-user', token='SECRET')))
            (state/'accounts/old-im-bot.json').write_text('{}')
            self.assertEqual(_current_weixin_account(cfg), cfg)

    def test_global_npm_cli_uses_its_sibling_node(self):
        from wechat_notify import _resolve_openclaw_node
        with TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'bin').mkdir()
            node = root/'bin/node'
            node.touch()
            mjs = root/'lib/node_modules/openclaw/openclaw.mjs'
            mjs.parent.mkdir(parents=True)
            mjs.touch()
            cli = root/'bin/openclaw'
            cli.symlink_to(mjs)
            with patch('shutil.which', return_value=str(cli)):
                exe, args = _resolve_openclaw_node('openclaw', {'PATH': str(root/'bin')})
            self.assertEqual(exe, str(node))
            self.assertEqual(args, [str(mjs.resolve())])

    def test_test_push_waits_for_send_acknowledgement(self):
        login = WechatLogin()
        with patch('wechat_login.threading.Thread') as thread:
            self.assertEqual(login.send_test()['testPush']['status'], 'sending')
            login.send_test()
        thread.assert_called_once()
        with patch('wechat_notify.send_test_alert', return_value=(True, 'message-id: private')) as send:
            login._send_test()
        send.assert_called_once_with()
        self.assertEqual(login.test_push['status'], 'sent')
        self.assertNotIn('private', json.dumps(login.test_push))

    def test_expired_session_test_push_reports_action_instead_of_success(self):
        login = WechatLogin()
        with patch('wechat_notify.send_test_alert', return_value=(False, 'prepare failed ret=-2 token=SECRET')):
            login._send_test()
        self.assertEqual(login.test_push['status'], 'error')
        self.assertIn('先给机器人发一条消息', login.test_push['message'])
        self.assertNotIn('SECRET', json.dumps(login.test_push))

    def test_test_push_exception_is_safe_to_display(self):
        login = WechatLogin()
        with patch('wechat_notify.send_test_alert', side_effect=RuntimeError('SECRET')):
            login._send_test()
        self.assertEqual(login.test_push['status'], 'error')
        self.assertNotIn('SECRET', json.dumps(login.test_push))

    def test_qr_scan_refresh_and_confirm_only_expose_public_state(self):
        login = WechatLogin()
        login._line('log: 二维码链接: https://liteapp.weixin.qq.com/q/test-code')
        self.assertEqual(login.state['status'], 'waiting')
        self.assertEqual(login.state['loginUrl'], 'https://liteapp.weixin.qq.com/q/test-code')
        login._line('👀 已扫码，在微信继续操作...')
        self.assertEqual(login.state['status'], 'scanned')
        login._line('⏳ 二维码已过期，正在刷新...')
        self.assertIsNone(login.state['loginUrl'])
        login._line('https://liteapp.weixin.qq.com/q/new-code')
        self.assertTrue(login.state['loginUrl'].endswith('new-code'))
        login._line('✅ 与微信连接成功！')
        self.assertEqual(login.state['status'], 'connected')
        self.assertIsNone(login.state['loginUrl'])

    def test_unrelated_output_and_tokens_are_never_returned(self):
        login = WechatLogin()
        for line in ('https://evil.example/login', 'javascript:alert(1)',
                     'bot_token=SECRET', 'https://user:SECRET@liteapp.weixin.qq.com/q/test'):
            login._line(line)
        self.assertNotIn('SECRET', json.dumps(login.state))
        self.assertIsNone(login.state['loginUrl'])

    def test_repeated_start_reuses_one_login(self):
        login = WechatLogin()
        with patch('wechat_login.threading.Thread') as thread:
            self.assertEqual(login.start()['status'], 'starting')
            login.start()
        thread.assert_called_once()
        login.close()
        self.assertEqual(login.start()['status'], 'error')

    def test_exit_zero_without_confirmation_is_not_success(self):
        login = WechatLogin()
        proc = Mock(stdout=io.StringIO('https://liteapp.weixin.qq.com/q/test\n'))
        proc.poll.return_value = 0
        proc.wait.return_value = 0
        with patch('wechat_notify.load_config', return_value={}), \
             patch('wechat_notify._env_with_node', return_value={}), \
             patch('wechat_notify._resolve_openclaw_node', return_value=('node', ['cli.mjs'])), \
             patch('wechat_login.subprocess.Popen', return_value=proc) as spawn:
            login._run()
        self.assertEqual(login.state['status'], 'error')
        self.assertIsNone(login.state['loginUrl'])
        self.assertEqual(spawn.call_args.args[0], ['node', 'cli.mjs', 'channels', 'login', '--channel', 'openclaw-weixin'])

    def test_close_kills_a_pending_login_process(self):
        login = WechatLogin()
        login.process = Mock()
        login.process.poll.return_value = None
        login.close()
        login.process.kill.assert_called_once()


class LoginHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        handler = build_watch_request_handler(root=root, watch_meta_file=root/'watch.json',
            watch_ui_dist=root/'dist', ws_hub=Mock(), snap_lock=threading.Lock(),
            get_last_snapshot=lambda: None, get_strategies_api=lambda: [], get_factors_api=lambda: [],
            handle_sectors_api=lambda _: (404, {}), watch_ui_dist_ready=lambda: False)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.opener = build_opener(ProxyHandler({}))
        self.login = Mock()
        self.login.status.return_value = dict(status='idle', loginUrl=None)
        self.login.start.return_value = dict(status='starting', loginUrl=None)
        self.patch = patch('wechat_login.login', self.login)
        self.patch.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.patch.stop()
        self.temp.cleanup()

    def test_opening_dialog_only_reads_status_and_post_starts_login(self):
        with self.opener.open(self.base+'/api/wechat/login', timeout=3) as response:
            self.assertEqual(json.load(response)['status'], 'idle')
            self.assertIn('no-store', response.headers['Cache-Control'])
        self.login.start.assert_not_called()
        request = Request(self.base+'/api/wechat/login', data=b'', method='POST', headers={'Origin': self.base})
        with self.opener.open(request, timeout=3) as response:
            self.assertEqual(json.load(response)['status'], 'starting')
        self.login.start.assert_called_once()

    def test_other_websites_cannot_start_or_read_login(self):
        for method in ('GET', 'POST'):
            request = Request(self.base+'/api/wechat/login', method=method,
                headers={'Origin': 'https://evil.example'})
            with self.assertRaises(HTTPError) as result:
                self.opener.open(request, timeout=3)
            self.assertEqual(result.exception.code, 403)
        self.login.start.assert_not_called()
        self.login.status.assert_not_called()

    def test_explicit_test_push_post_and_cross_origin_rejection(self):
        self.login.send_test.return_value = dict(testPush=dict(status='sending', message='正在发送'))
        request = Request(self.base+'/api/wechat/test', data=b'', method='POST', headers={'Origin': self.base})
        with self.opener.open(request, timeout=3) as response:
            self.assertEqual(json.load(response)['testPush']['status'], 'sending')
        self.login.send_test.assert_called_once()
        request = Request(self.base+'/api/wechat/test', data=b'', method='POST', headers={'Origin': 'https://evil.example'})
        with self.assertRaises(HTTPError) as result:
            self.opener.open(request, timeout=3)
        self.assertEqual(result.exception.code, 403)
        self.login.send_test.assert_called_once()

    def test_untrusted_host_is_rejected(self):
        request = Request(self.base+'/api/wechat/login', headers={'Host': 'evil.example'})
        with self.assertRaises(HTTPError) as result:
            self.opener.open(request, timeout=3)
        self.assertEqual(result.exception.code, 403)
        self.login.status.assert_not_called()
