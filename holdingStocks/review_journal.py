"""Persistent review journal, stored independently of trading data."""
import base64
import json
import sqlite3
import uuid
from datetime import date, datetime
from pathlib import Path

DB = Path(__file__).parent / 'review_journal.sqlite3'

from threading import RLock
from runtime_documents import read_document, write_document
_LOCK = RLock()
_INDEX = 'review_journal_index'

def _write_item(item):
    # Immutable chunks keep image uploads below the document API's 2MB limit.
    text = json.dumps(item, ensure_ascii=False)
    prefix = 'review_journal_' + uuid.uuid4().hex
    keys = []
    for i in range(0, len(text), 500000):
        key = prefix + '_' + str(i // 500000)
        write_document(key, {'data': text[i:i + 500000]}, 0)
        keys.append(key)
    return keys

def _index():
    revision, index = read_document(_INDEX)
    if index is None:
        index = {}
        if DB.exists():
            with sqlite3.connect(DB) as db:
                for row in db.execute('SELECT payload FROM entries'):
                    item = json.loads(row[0])
                    index[item['id']] = _write_item(item)
        revision = write_document(_INDEX, index, revision)
    return revision, index

def _read_item(keys):
    return json.loads(''.join(read_document(key)[1]['data'] for key in keys))

def entries():
    with _LOCK:
        _, index = _index()
        return sorted([_read_item(keys) for keys in index.values()], key=lambda x: (x['date'], x['createdAt']), reverse=True)

def save(body):
    with _LOCK:
        revision, index = _index()
        key = body.get('id') or uuid.uuid4().hex
        old = _read_item(index[key]) if key in index else None
        if body.get('id') and not old:
            raise ValueError('笔记不存在')
        action = body.get('action')
        if action in ('delete', 'like'):
            if not old:
                raise ValueError('笔记不存在')
            if action == 'delete':
                del index[key]
                write_document(_INDEX, index, revision)
                return {'id': key, 'deleted': True}
            if not isinstance(body.get('liked'), bool):
                raise ValueError('点赞状态无效')
            old['liked'] = body['liked']
            old['likes'] = int(old['liked'])
            index[key] = _write_item(old)
            write_document(_INDEX, index, revision)
            return old
        now = datetime.now().astimezone().isoformat()
        if body.get('action') == 'comment':
            text = str(body.get('text', '')).strip()
            if not old or not text or len(text) > 2000:
                raise ValueError('请输入不超过2000字的评论')
            old['comments'].append({'id': uuid.uuid4().hex, 'text': text, 'date': now})
            item = old
        else:
            title, content = str(body.get('title', '')).strip(), str(body.get('content', '')).strip()
            day = str(body.get('date', ''))
            date.fromisoformat(day)
            images = body.get('images', [])
            if not title or len(title) > 120 or not content or len(content) > 100000:
                raise ValueError('标题限120字，正文不能为空且不超过10万字')
            if not isinstance(images, list) or len(images) > 9:
                raise ValueError('最多上传9张图片')
            for img in images:
                header, data = img.split(',', 1)
                if header not in ('data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64', 'data:image/gif;base64') or len(base64.b64decode(data, validate=True)) > 5 * 1024 * 1024:
                    raise ValueError('图片格式不支持或超过5MB')
            item = dict(id=key, title=title, content=content, date=day, images=images, comments=old['comments'] if old else [], createdAt=old['createdAt'] if old else now, updatedAt=now, liked=old.get('liked', False) if old else False, likes=old.get('likes', 0) if old else 0)
        index[key] = _write_item(item)
        write_document(_INDEX, index, revision)
        return item
