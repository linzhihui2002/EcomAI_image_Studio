import os
import base64
import json
import uuid
from config import AIConfig


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, 'uploads')
CHUNKS_DIR = os.path.join(UPLOADS_DIR, 'chunks')


def _ensure_chunks_dir():
    os.makedirs(CHUNKS_DIR, exist_ok=True)


def _get_meta_path(upload_id):
    return os.path.join(CHUNKS_DIR, f'{upload_id}_meta.json')


def _get_chunk_dir(upload_id):
    return os.path.join(CHUNKS_DIR, upload_id)


def _read_meta(upload_id):
    meta_path = _get_meta_path(upload_id)
    if not os.path.exists(meta_path):
        raise ValueError('上传会话不存在')
    with open(meta_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _write_meta(upload_id, meta):
    meta_path = _get_meta_path(upload_id)
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def init_upload(filename, total_chunks, file_size, user_id):
    _ensure_chunks_dir()

    upload_id = uuid.uuid4().hex

    meta = {
        'filename': filename,
        'total_chunks': total_chunks,
        'file_size': file_size,
        'user_id': user_id,
        'uploaded_chunks': [],
        'created_at': None,
    }

    _write_meta(upload_id, meta)

    chunk_dir = _get_chunk_dir(upload_id)
    os.makedirs(chunk_dir, exist_ok=True)

    return {
        'upload_id': upload_id,
        'total_chunks': total_chunks,
        'chunk_size': AIConfig.CHUNK_SIZE,
    }


def upload_chunk(upload_id, chunk_index, chunk_data_base64):
    meta = _read_meta(upload_id)

    if chunk_index >= meta['total_chunks']:
        raise ValueError('分块索引超出范围')

    chunk_dir = _get_chunk_dir(upload_id)

    raw_data = chunk_data_base64
    if ',' in raw_data:
        raw_data = raw_data.split(',', 1)[1]
    chunk_bytes = base64.b64decode(raw_data)

    chunk_path = os.path.join(chunk_dir, str(chunk_index))
    with open(chunk_path, 'wb') as f:
        f.write(chunk_bytes)

    if chunk_index not in meta['uploaded_chunks']:
        meta['uploaded_chunks'].append(chunk_index)
        _write_meta(upload_id, meta)

    uploaded_chunks = meta['uploaded_chunks']
    is_complete = len(uploaded_chunks) == meta['total_chunks']

    return {
        'upload_id': upload_id,
        'chunk_index': chunk_index,
        'uploaded_chunks': uploaded_chunks,
        'total_chunks': meta['total_chunks'],
        'is_complete': is_complete,
    }


def complete_upload(upload_id):
    meta = _read_meta(upload_id)

    uploaded_chunks = meta['uploaded_chunks']
    if len(uploaded_chunks) != meta['total_chunks']:
        raise ValueError('分块未全部上传完成')

    chunk_dir = _get_chunk_dir(upload_id)
    filename = meta['filename']
    merged_filename = f'{upload_id}_{filename}'
    merged_path = os.path.join(UPLOADS_DIR, merged_filename)

    os.makedirs(UPLOADS_DIR, exist_ok=True)

    with open(merged_path, 'wb') as outfile:
        for i in range(meta['total_chunks']):
            chunk_path = os.path.join(chunk_dir, str(i))
            with open(chunk_path, 'rb') as infile:
                outfile.write(infile.read())

    for i in range(meta['total_chunks']):
        chunk_path = os.path.join(chunk_dir, str(i))
        if os.path.exists(chunk_path):
            os.remove(chunk_path)
    os.rmdir(chunk_dir)

    meta_path = _get_meta_path(upload_id)
    if os.path.exists(meta_path):
        os.remove(meta_path)

    return {
        'storage_path': f'uploads/{merged_filename}',
        'file_name': filename,
        'file_size': meta['file_size'],
    }


def get_upload_status(upload_id):
    meta = _read_meta(upload_id)

    uploaded_chunks = meta['uploaded_chunks']
    is_complete = len(uploaded_chunks) == meta['total_chunks']

    return {
        'upload_id': upload_id,
        'filename': meta['filename'],
        'total_chunks': meta['total_chunks'],
        'uploaded_chunks': uploaded_chunks,
        'file_size': meta['file_size'],
        'created_at': meta.get('created_at'),
        'is_complete': is_complete,
    }