"""Two explicit WeChat destinations; credentials remain in OpenClaw's account store."""
from __future__ import annotations
import json
import os
import re
import threading
from pathlib import Path


_BIND_LOCK = threading.RLock()


def delivery_configs(config):
    if config.get('_single_destination'):
        return [config]
    
    # 自动校准 account_inventory 中的最新有效账号，防止重新扫码后凭证文件名更新导致不匹配
    try:
        inv = account_inventory()
    except Exception:
        inv = {}

    def _resolve_account(account: str | None, target: str | None) -> str:
        if not target:
            return account or ''
        def target_of(data):
            user = str(data.get('user') or '')
            return user if '@' in user else user+'@im.wechat'
        if account and account in inv and target_of(inv[account]) == target:
            return account
        # 根据 target 自动匹配最新的有效 account
        for aid, data in sorted(inv.items(), key=lambda item: item[1].get('updated', 0), reverse=True):
            if target_of(data) == target:
                return aid
        return account or ''

    primary_acc = _resolve_account(config.get('account'), config.get('target'))
    primary = dict(config, account=primary_acc, _recipient_slot='primary', _single_destination=True)
    result = [primary]
    secondary = config.get('secondary')
    if isinstance(secondary, dict) and secondary.get('enabled', True) and secondary.get('target'):
        sec_acc = _resolve_account(secondary.get('account'), secondary.get('target'))
        if (sec_acc, secondary['target']) != (primary.get('account'), primary.get('target')):
            result.append(dict(config, account=sec_acc, target=secondary['target'],
                               _recipient_slot='secondary', _single_destination=True))
    return result


def config_for_slot(slot, config):
    if slot not in ('primary', 'secondary'):
        raise ValueError('未知微信连接')
    if slot == 'primary':
        return dict(config, _recipient_slot=slot, _single_destination=True)
    secondary = config.get('secondary') or {}
    return dict(config, account=secondary.get('account', ''), target=secondary.get('target', ''),
                _recipient_slot=slot, _single_destination=True)


def account_inventory():
    root = Path(os.environ.get('OPENCLAW_STATE_DIR') or Path.home()/'.openclaw')/'openclaw-weixin'
    try:
        ids = json.loads((root/'accounts.json').read_text())
    except (OSError, ValueError):
        ids = []
    # A concurrent CLI can briefly replace the shared account index. The exact
    # account ID is reported by each login process; inventory its saved file too.
    ids = list(dict.fromkeys([*(i for i in (ids if isinstance(ids, list) else []) if isinstance(i, str)),
                              *(p.stem for p in (root/'accounts').glob('*.json'))]))
    result = {}
    for aid in ids if isinstance(ids, list) else []:
        if not isinstance(aid, str) or not re.fullmatch(r'[\w.-]+', aid):
            continue
        try:
            path = root/'accounts'/f'{aid}.json'
            data = json.loads(path.read_text())
            if data.get('token') and data.get('userId'):
                # Only identity and update time leave the credential store.
                result[aid] = dict(user=data['userId'], updated=path.stat().st_mtime_ns)
        except (OSError, ValueError, TypeError):
            continue
    return result


def bind_scanned_account(slot, before, after, *, account_id=None):
    # Only this short commit is serialized; QR generation and waiting are independent.
    with _BIND_LOCK:
        return _bind_scanned_account(slot, before, after, account_id=account_id)


def _bind_scanned_account(slot, before, after, *, account_id=None):
    if slot not in ('primary', 'secondary'):
        raise ValueError('未知微信连接')
    changed = [(aid, data) for aid, data in after.items() if before.get(aid) != data]
    if account_id is not None:
        changed = [(account_id, after[account_id])] if account_id in after else []
    if len(changed) != 1:
        raise ValueError('未能唯一确认扫码账号，请重新扫码')
    account, data = changed[0]
    user = str(data['user'])
    target = user if '@' in user else user+'@im.wechat'
    from wechat_notify import load_config, _database_documents, CONFIG_FILE
    config = load_config()
    if slot == 'secondary' and target == config.get('target'):
        raise ValueError('这是第一个微信，请使用另一个微信扫码；第一个连接仍保留')
    if slot == 'primary' and target == (config.get('secondary') or {}).get('target'):
        raise ValueError('这是第二个微信，请用第一个微信扫码；第二个连接仍保留')
    binding = dict(account=account, target=target, enabled=True)
    if _database_documents():
        from runtime_documents import read_document, write_document
        revision, raw = read_document('wechat_notify')
        raw = dict(raw or {})
        if slot == 'secondary':
            raw['secondary'] = binding
        else:
            raw.update(account=account, target=target)
        write_document('wechat_notify', raw, revision)
    else:
        raw = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        if slot == 'secondary': raw['secondary'] = binding
        else: raw.update(account=account, target=target)
        CONFIG_FILE.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
    _repair_configured_account_index(raw)
    return binding


def _repair_configured_account_index(config):
    root = Path(os.environ.get('OPENCLAW_STATE_DIR') or Path.home()/'.openclaw')/'openclaw-weixin'
    path = root/'accounts.json'
    try:
        ids = json.loads(path.read_text())
        if not isinstance(ids, list):
            ids = []
    except (OSError, ValueError):
        ids = []
    expected = [config.get('account'), (config.get('secondary') or {}).get('account')]
    # Do not touch credential files or register unrelated orphan accounts.
    valid = account_inventory()
    merged = list(dict.fromkeys(aid for aid in [*ids, *expected]
                                if isinstance(aid, str) and aid in valid))
    if merged != ids:
        root.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.myquan.tmp')
        temp.write_text(json.dumps(merged))
        temp.replace(path)
