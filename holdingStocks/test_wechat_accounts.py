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
         patch('runtime_documents.write_document') as write:
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
