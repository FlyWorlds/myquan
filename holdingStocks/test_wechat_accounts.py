from __future__ import annotations
import copy
from unittest.mock import patch
import pytest
from wechat_accounts import delivery_configs, config_for_slot, bind_scanned_account


def config():
    return dict(account='bot1', target='user1@im.wechat', channel='openclaw-weixin',
                secondary=dict(account='bot2', target='user2@im.wechat', enabled=True))


def test_two_destinations_are_explicit_and_test_messages_are_scoped_to_one():
    cfg = config()
    original = copy.deepcopy(cfg)
    assert [c['account'] for c in delivery_configs(cfg)] == ['bot1', 'bot2']
    assert len(delivery_configs(config_for_slot('secondary', cfg))) == 1
    assert config_for_slot('secondary', cfg)['target'] == 'user2@im.wechat'
    assert cfg == original


def test_partial_failure_retries_only_the_missing_recipient_and_does_not_block_other():
    from wechat_notify import PendingNotification, _deliver_pending
    item = PendingNotification(dedupe_key='fill|1', message='test', code='600330', alert_type='fill')
    calls = []
    def sender(message, *, config, retries=None):
        calls.append(config['account'])
        return (config['account'] == 'bot2', 'network timeout')
    assert not _deliver_pending(item, config(), send_fn=sender)[0]
    assert calls == ['bot1', 'bot2'] and item.delivered_to == ['bot2|user2@im.wechat']
    calls.clear()
    def recovered(message, *, config, retries=None):
        calls.append(config['account'])
        return True, 'ok'
    assert _deliver_pending(item, config(), send_fn=recovered)[0]
    assert calls == ['bot1']
    calls.clear()
    assert _deliver_pending(item, config(), send_fn=recovered)[0] and not calls


def test_binding_second_account_never_replaces_first_configuration():
    before = {'bot1': dict(user='user1', updated=1)}
    after = dict(before, bot2=dict(user='user2', updated=2))
    raw = {'account': 'bot1', 'target': 'user1@im.wechat', 'enabled': True}
    with patch('wechat_notify.load_config', return_value=raw), \
         patch('wechat_notify._database_documents', return_value=True), \
         patch('runtime_documents.read_document', return_value=(7, raw)), \
         patch('runtime_documents.write_document') as write, \
         patch('wechat_accounts._repair_configured_account_index'):
        bind_scanned_account('secondary', before, after)
    saved = write.call_args.args[1]
    assert saved['account'] == 'bot1' and saved['target'] == 'user1@im.wechat'
    assert saved['secondary']['account'] == 'bot2'
    assert write.call_args.args[2] == 7
    assert 'secondary' not in raw


def test_same_wechat_cannot_be_registered_as_both_recipients():
    cfg = config()
    with patch('wechat_notify.load_config', return_value=cfg), patch('runtime_documents.write_document') as write:
        with pytest.raises(ValueError, match='另一个微信'):
            bind_scanned_account('secondary', {}, {'new-bot': dict(user='user1', updated=2)})
        write.assert_not_called()


def test_delivery_receipts_survive_requeue():
    import wechat_notify as notify
    notify.reset_wechat_delivery_state_for_tests()
    with patch.object(notify, '_persist_outbox'):
        notify.enqueue_notification(message='test', dedupe_key='fill|test', code='600330', alert_type='fill',
            is_fill=True, delivered_to=['bot1|user1@im.wechat'], config={'enabled': True})
        item = notify._pop_next_pending(config={})
    assert item.delivered_to == ['bot1|user1@im.wechat']
    notify.reset_wechat_delivery_state_for_tests()


def test_secondary_scan_binds_only_new_identity_then_reloads_both_channels():
    import io
    from unittest.mock import Mock
    from wechat_login import WechatLogin
    login = WechatLogin('secondary')
    empty = dict(channel='openclaw-weixin', account='', target='')
    bound = dict(channel='openclaw-weixin', account='bot2', target='user2@im.wechat')
    proc = Mock(stdout=io.StringIO('✅ 与微信连接成功！\n'))
    proc.poll.return_value = 0
    with patch.object(login, '_config', side_effect=[empty, bound, bound]), \
         patch('wechat_accounts.account_inventory', side_effect=[{}, {'bot2': dict(user='user2', updated=2)}]), \
         patch('wechat_accounts.bind_scanned_account') as bind, \
         patch('wechat_notify._env_with_node', return_value={}), \
         patch('wechat_notify._resolve_openclaw_node', return_value=('node', ['cli.mjs'])), \
         patch('wechat_login.subprocess.Popen', return_value=proc), \
         patch('wechat_notify.ensure_openclaw_gateway', return_value=(True, 'ok')), \
         patch('wechat_notify.wait_weixin_channel_ready', return_value=(True, 'ok')):
        login._run()
    assert login.state['status'] == 'connected'
    assert bind.call_args.args[0] == 'secondary'
    assert login._view()['slot'] == 'secondary'


def test_delivery_receipts_and_factor_specific_key_survive_restart(tmp_path):
    import json
    import time
    import wechat_notify as notify
    notify.reset_wechat_delivery_state_for_tests()
    state = tmp_path/'state.json'
    key = 'signal|2026-11-02|600330|buy_hit:factor33'
    (tmp_path/'state_outbox.json').write_text(json.dumps({'pending': [{
        'dedupe_key': key, 'message': 'test', 'code': '600330', 'alert_type': '已触买',
        'enqueued_at': time.time(), 'delivered_to': ['bot1|user1@im.wechat']}]}))
    with patch.object(notify, 'STATE_FILE', state), patch.object(notify, '_database_documents', return_value=False):
        notify._restore_outbox()
        item = notify._pop_next_pending(config={})
    assert item.dedupe_key == key and item.delivered_to == ['bot1|user1@im.wechat']
    notify.reset_wechat_delivery_state_for_tests()


def test_concurrent_scans_bind_using_their_own_reported_account_id():
    after = {'bot1': dict(user='user1', updated=1), 'bot2': dict(user='user2', updated=2)}
    raw = {'account': 'oldbot', 'target': 'olduser@im.wechat'}
    with patch('wechat_notify.load_config', return_value=raw), \
         patch('wechat_notify._database_documents', return_value=True), \
         patch('runtime_documents.read_document', return_value=(1, raw)), \
         patch('runtime_documents.write_document') as write, \
         patch('wechat_accounts._repair_configured_account_index'):
        bind_scanned_account('secondary', {}, after, account_id='bot2')
    assert write.call_args.args[1]['secondary']['account'] == 'bot2'
    assert write.call_args.args[1]['target'] == 'olduser@im.wechat'


def test_configured_account_index_recovers_concurrent_registration(tmp_path, monkeypatch):
    import json
    from wechat_accounts import _repair_configured_account_index
    monkeypatch.setenv('OPENCLAW_STATE_DIR', str(tmp_path))
    root = tmp_path/'openclaw-weixin'
    (root/'accounts').mkdir(parents=True)
    for aid, user in [('bot1', 'user1'), ('bot2', 'user2')]:
        (root/'accounts'/f'{aid}.json').write_text(json.dumps(dict(token='test', userId=user)))
    (root/'accounts.json').write_text(json.dumps(['bot2']))
    _repair_configured_account_index(config())
    assert set(json.loads((root/'accounts.json').read_text())) == {'bot1', 'bot2'}


def test_two_qr_sessions_and_refresh_are_independent():
    import threading
    import time
    from unittest.mock import Mock
    from wechat_login import WechatLogin
    class Stream:
        def __init__(self, process, url): self.process, self.url = process, url
        def __iter__(self):
            yield self.url+'\n'
            self.process.done.wait(5)
        def close(self): pass
    class Process:
        def __init__(self, number):
            self.done = threading.Event()
            self.stdout = Stream(self, f'https://liteapp.weixin.qq.com/q/session-{number}')
            self.kill = Mock(side_effect=self.done.set)
        def poll(self): return 0 if self.done.is_set() else None
        def wait(self): self.done.wait(5); return 0
    processes = []
    def spawn(*args, **kwargs):
        process = Process(len(processes)+1)
        processes.append(process)
        return process
    def until(predicate):
        end = time.monotonic()+3
        while time.monotonic()<end:
            if predicate(): return
            time.sleep(.01)
        assert predicate()
    first, second = WechatLogin(), WechatLogin('secondary')
    with patch('wechat_notify.load_config', return_value={}), \
         patch('wechat_notify._env_with_node', return_value={}), \
         patch('wechat_notify._resolve_openclaw_node', return_value=('node', ['cli.mjs'])), \
         patch('wechat_accounts.account_inventory', return_value={}), \
         patch('wechat_login.subprocess.Popen', side_effect=spawn):
        try:
            first.start()
            until(lambda: first.state['status']=='waiting')
            second.start()
            until(lambda: second.state['status']=='waiting')
            second_url = second.state['loginUrl']
            assert first.state['loginUrl'] != second_url
            first.start(force=True)
            until(lambda: len(processes)==3 and first.state['status']=='waiting')
            assert first.state['loginUrl'].endswith('session-3')
            assert second.state['loginUrl']==second_url and second.state['status']=='waiting'
            processes[1].kill.assert_not_called()
        finally:
            first.close(); second.close()
            until(lambda: first.process is None and second.process is None)


def test_login_reporter_exposes_only_its_account_id(tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path
    reporter = Path(__file__).with_name('wechat_login_report.cjs')
    folder = tmp_path/'openclaw-weixin'/'accounts'
    folder.mkdir(parents=True)
    node = shutil.which('node')
    script = 'require("node:fs").writeFileSync(process.argv[1], JSON.stringify({token:"SECRET",userId:"private-user"}))'
    result = subprocess.run([node, '--require', str(reporter), '-e', script, str(folder/'bot2.json')],
                            capture_output=True, text=True, check=True)
    assert result.stdout.strip() == 'MYQUAN_WECHAT_ACCOUNT:bot2'
    assert 'SECRET' not in result.stdout and 'private-user' not in result.stdout
