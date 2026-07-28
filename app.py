#!/usr/bin/env python3
"""UseAI - Flask Web Interface"""

import json
import mimetypes
import os
import random
import string
import sys
import time
import uuid
from datetime import datetime

import requests
import websocket
from flask import Flask, render_template, request, jsonify, Response, make_response

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ===================== CONSTANTS =====================
APP_PASSWORD = "123"

API_BASE = "https://api.use.ai"
AGENTS_BASE = "https://agents.use.ai"
FILES_BASE = "https://files.use.ai"
WS_BASE = "wss://agents.use.ai"
ORIGIN = "https://use.ai"
REFERER = "https://use.ai/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")

MODELS = {
    "POPÜLER MODELLER": {
        "Sonnet 5": "gateway-sonnet-5",
        "GPT-5.6 Terra": "gateway-gpt-5-6-terra",
        "GPT-5.6 Luna": "gateway-gpt-5-6-luna",
        "GPT-5.4": "gateway-gpt-5-4",
        "Gemini 3.1 Pro": "gateway-gemini-3-1-pro",
        "GLM 5.2": "gateway-glm-5-2",
    },
    "AKILLI MODELLER": {
        "Fable 5": "gateway-fable-5",
        "Opus 5": "gateway-opus-5",
        "Opus 4.8": "gateway-opus-4-8",
        "GPT-5.6 Sol": "gateway-gpt-5-6",
        "GPT-5.5": "gateway-gpt-5-5",
        "Grok 4.3": "gateway-grok-4-3",
    },
    "CLAUDE": {
        "Sonnet 4.6": "gateway-sonnet-4-6",
        "Opus 4.7": "gateway-opus-4-7",
        "Opus 4.6": "gateway-opus-4-6",
        "Opus 4.5": "gateway-opus-4-5",
    },
    "CHATGPT": {
        "GPT-5.3": "gateway-gpt-5-3",
        "GPT-5.1": "gateway-gpt-5-1",
        "GPT-5": "gateway-gpt-5",
        "GPT-5 Mini": "gateway-gpt-5-mini",
    },
    "DİĞER MODELLER": {
        "Gemini 3 Flash": "gateway-gemini-3-flash",
        "DeepSeek V4 Pro": "gateway-deepseek-v4-pro",
        "DeepSeek V4 Flash": "gateway-deepseek-v4-flash",
        "Qwen 3.5": "gateway-qwen-3-5-397b",
        "Kimi K2.6": "gateway-kimi-k2-6",
    },
    "ESKİ MODELLER": {
        "Gemini 3 Pro": "gateway-gemini-3-pro",
        "Gemini 2.5 Flash": "gateway-gemini-2.5-flash",
        "Opus 4.1": "gateway-opus-4-1",
        "DeepSeek": "gateway-deepseek-r1",
        "Grok 4": "gateway-grok-4",
        "Qwen 3 Max": "gateway-qwen-3-max",
        "Kimi K2": "gateway-deepinfra-kimi-k2",
        "Llama 3.3": "gateway-llama-3-3-70b-versatile",
        "GPT-4o Mini": "gateway-gpt-4o-mini",
        "GPT-4o": "gateway-gpt-4o",
    },
}

DEFAULT_MODEL = "gateway-opus-5"

IMAGE_MODELS = [
    {"id": "nano-banana",     "label": "Nano Banana",     "provider": "openrouter"},
    {"id": "nano-banana-2",   "label": "Nano Banana 2",   "provider": "openrouter"},
    {"id": "nano-banana-pro", "label": "Nano Banana Pro", "provider": "openrouter"},
    {"id": "seedream-4.5",    "label": "Seedream 4.5",    "provider": "openrouter"},
    {"id": "flux-2-pro",      "label": "FLUX.2 Pro",      "provider": "openrouter"},
    {"id": "flux-2-flex",     "label": "FLUX.2 Flex",     "provider": "openrouter"},
    {"id": "flux-2-max",      "label": "FLUX.2 Max",      "provider": "openrouter"},
]
DEFAULT_IMAGE_MODEL_ID = "nano-banana-2"

ASPECT_RATIOS = [
    ("1:1",  "Kare (1:1)"),
    ("4:3",  "Standart (4:3)"),
    ("3:4",  "Dikey (3:4)"),
    ("16:9", "Geniş Ekran (16:9)"),
    ("9:16", "Mobil (9:16)"),
    ("21:9", "Ultra Geniş (21:9)"),
]
DEFAULT_ASPECT = "16:9"

IMAGE_COUNT = 1
IMAGE_STYLE = "none"


# ===================== HELPER FUNCTIONS =====================
def rand_email() -> str:
    local = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(8, 12)))
    return f"{local}@spamok.com"


def new_session_http() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "accept": "*/*",
        "accept-language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "origin": ORIGIN,
        "referer": REFERER,
        "user-agent": UA,
        "sec-ch-ua": '"Not;A=Brand";v="8", "Chromium";v="150", "Google Chrome";v="150"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-site",
    })
    return s


def format_history_prefix(history: list[dict]) -> str:
    if not history:
        return ""
    simplified = []
    for entry in history:
        simplified.append({
            "role": entry.get("role"),
            "text": entry.get("text", ""),
            "attachments": entry.get("attachments"),
            "generatedImages": entry.get("images")
        })
    history_json = json.dumps(simplified, ensure_ascii=False, indent=2)
    return (
        "--- ÖNCEKİ KONUŞMA GEÇMİŞİ (JSON) ---\n"
        f"{history_json}\n"
        "--- GEÇMİŞ SONU ---\n\n"
        "Yukarıdaki JSON önceki konuşmamdır (role='user' ben, role='assistant' sen). "
        "Buna göre aşağıdaki yeni mesajıma cevap ver:\n\n"
    )


# ===================== USEAI CLIENT =====================
class UseAIClient:
    def __init__(self):
        self.session: requests.Session | None = None
        self.email: str = ""
        self.user_id: str = ""
        self.mixpanel_id: str = ""
        self.guest_id: str = ""
        self.auth_token: str = ""
        self.jwt: str = ""
        self.app_token: str = ""
        self.messages: list[dict] = []
        self.chat_id: str = ""
        self.device_id: str = str(uuid.uuid4())
        self.model: str = DEFAULT_MODEL
        self.is_ready: bool = False

    def email_login(self):
        self.session = new_session_http()
        self.email = rand_email()
        r = self.session.post(
            f"{API_BASE}/v1/auth/email-login",
            headers={"content-type": "application/json"},
            data=json.dumps({"email": self.email}),
            timeout=15,
        )
        r.raise_for_status()

    def sign_in(self):
        self.mixpanel_id = str(uuid.uuid4())
        self.guest_id = str(uuid.uuid4())
        payload = {
            "email": self.email,
            "mixpanelUserId": self.mixpanel_id,
            "guestId": self.guest_id,
            "mid": self.mixpanel_id,
            "turnstileBypass": True,
        }
        r = self.session.post(
            f"{API_BASE}/v1/auth/sign-in/credentials",
            headers={"content-type": "application/json"},
            data=json.dumps(payload),
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        self.user_id = data["userId"]
        self.auth_token = r.headers.get("set-auth-token", "")

    def get_session(self):
        r = self.session.get(f"{API_BASE}/v1/auth/get-session", timeout=15)
        r.raise_for_status()
        self.jwt = r.headers.get("set-auth-jwt", "")
        data = r.json()
        self.user_id = data["user"]["id"]

    def set_model(self, model: str = DEFAULT_MODEL):
        r = self.session.post(
            f"{API_BASE}/v1/chat/set-model",
            headers={"content-type": "application/json"},
            data=json.dumps({"model": model}),
            timeout=15,
        )
        r.raise_for_status()
        self.model = model

    def app_attestation(self):
        r = self.session.post(
            f"{API_BASE}/v1/auth/app-attestation",
            headers={"content-type": "application/json"},
            data="{}",
            timeout=15,
        )
        r.raise_for_status()
        self.app_token = r.json()["token"]

    def vote(self):
        self.chat_id = str(uuid.uuid4())
        r = self.session.get(
            f"{AGENTS_BASE}/vote",
            params={"chatId": self.chat_id},
            headers={
                "authorization": f"Bearer {self.jwt}",
                "x-guest-user-id": f"guest:{self.guest_id}",
            },
            timeout=15,
        )
        r.raise_for_status()

    def bootstrap(self, model: str = DEFAULT_MODEL):
        self.email_login()
        self.sign_in()
        self.get_session()
        self.set_model(model)
        self.app_attestation()
        self.vote()
        self.messages = []
        self.chat_id = str(uuid.uuid4())
        self.is_ready = True

    def upload_file_bytes(self, file_bytes: bytes, filename: str, content_type: str) -> dict:
        if not self.is_ready or not self.jwt:
            self.bootstrap(self.model)

        mime = content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        files = {
            "name": (None, filename),
            "type": (None, mime),
            "file": (filename, file_bytes, mime),
        }
        r = self.session.post(
            f"{FILES_BASE}/upload",
            files=files,
            headers={"authorization": f"Bearer {self.jwt}"},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get("success"):
            raise RuntimeError(f"Yükleme başarısız: {data}")

        rel = data["url"]
        full_url = f"{FILES_BASE}{rel}" if rel.startswith("/") else rel

        return {
            "type": "file",
            "mediaType": mime,
            "filename": filename,
            "url": full_url,
        }


# ===================== FLASK SESSIONS =====================
_sessions = {}


def get_sid():
    return request.cookies.get('useai_sid')


def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None


def new_sess(sid):
    client = UseAIClient()
    _sessions[sid] = {
        'app_unlocked': False,
        'auto_renew': True,
        'client': client,
        'model': DEFAULT_MODEL,
        'web_search': False,
        'image_mode': False,
        'image_model_id': DEFAULT_IMAGE_MODEL_ID,
        'aspect_ratio': DEFAULT_ASPECT,
        'history': [],
        'conversations': [],
        'active_local_conv_id': None,
    }
    return _sessions[sid]


def make_local_conv_id():
    return 'conv_' + uuid.uuid4().hex[:12]


def save_conv_to_history(sess):
    history = sess.get('history', [])
    if not history:
        return

    def derive_title():
        for turn in history:
            if turn.get('role') == 'user':
                t = turn.get('text', 'Konuşma')
                return (t[:48] + '…') if len(t) > 48 else t
        return 'Konuşma'

    convs = sess.setdefault('conversations', [])
    local_id = sess.get('active_local_conv_id')

    if local_id:
        for c in convs:
            if c.get('conv_id') == local_id:
                if not c.get('title_locked'):
                    c['title'] = derive_title()
                c['history'] = history[:]
                return
        convs.insert(0, {
            'conv_id': local_id,
            'title': derive_title(),
            'history': history[:],
        })
    else:
        new_id = make_local_conv_id()
        sess['active_local_conv_id'] = new_id
        convs.insert(0, {
            'conv_id': new_id,
            'title': derive_title(),
            'history': history[:],
        })

    sess['conversations'] = convs[:50]


# ===================== ROUTES =====================
@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    if not request.cookies.get('useai_sid'):
        sid = str(uuid.uuid4())
        resp.set_cookie('useai_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/status')
def api_status():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'initialized': False})
    
    client = sess['client']
    return jsonify({
        'initialized': True,
        'email': client.email if client else '',
        'user_id': client.user_id if client else '',
        'model': sess.get('model', DEFAULT_MODEL),
        'auto_renew': sess.get('auto_renew', True),
        'web_search': sess.get('web_search', False),
        'image_mode': sess.get('image_mode', False),
        'image_model_id': sess.get('image_model_id', DEFAULT_IMAGE_MODEL_ID),
        'aspect_ratio': sess.get('aspect_ratio', DEFAULT_ASPECT),
        'message_count': len(sess.get('history', [])) // 2,
    })


@app.route('/api/init', methods=['POST'])
def api_init():
    data = request.json or {}
    password = data.get('password', '')

    if password != APP_PASSWORD:
        return jsonify({'success': False, 'error': 'Hatalı şifre!'}), 401

    sid = get_sid() or str(uuid.uuid4())
    sess = get_sess() or new_sess(sid)
    sess['app_unlocked'] = True
    
    try:
        if not sess['client'].is_ready:
            sess['client'].bootstrap(sess['model'])
    except Exception as e:
        return jsonify({'success': False, 'error': f"Oturum başlatılamadı: {e}"}), 500

    resp = jsonify({
        'success': True,
        'email': sess['client'].email,
        'model': sess['model'],
    })
    resp.set_cookie('useai_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp


@app.route('/api/models')
def api_models():
    flat_models = []
    for cat, items in MODELS.items():
        for name, mid in items.items():
            flat_models.append({
                'id': mid,
                'name': name,
                'category': cat,
            })

    return jsonify({
        'categories': MODELS,
        'models': flat_models,
        'image_models': IMAGE_MODELS,
        'aspect_ratios': [
            {'value': ar, 'label': label} for ar, label in ASPECT_RATIOS
        ],
        'default_model': DEFAULT_MODEL,
        'default_image_model': DEFAULT_IMAGE_MODEL_ID,
        'default_aspect_ratio': DEFAULT_ASPECT,
    })


@app.route('/api/settings', methods=['POST'])
def api_settings():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    client = sess['client']

    if 'model' in data:
        model_val = data['model']
        all_mids = [mid for items in MODELS.values() for mid in items.values()]
        if model_val in all_mids:
            sess['model'] = model_val
            if client and client.is_ready:
                try:
                    client.set_model(model_val)
                except Exception:
                    pass

    if 'auto_renew' in data:
        sess['auto_renew'] = bool(data['auto_renew'])

    if 'web_search' in data:
        sess['web_search'] = bool(data['web_search'])
        if sess['web_search']:
            sess['image_mode'] = False

    if 'image_mode' in data:
        sess['image_mode'] = bool(data['image_mode'])
        if sess['image_mode']:
            sess['web_search'] = False

    if 'image_model_id' in data:
        img_id = data['image_model_id']
        if any(m['id'] == img_id for m in IMAGE_MODELS):
            sess['image_model_id'] = img_id

    if 'aspect_ratio' in data:
        ar_val = data['aspect_ratio']
        if any(ar[0] == ar_val for ar in ASPECT_RATIOS):
            sess['aspect_ratio'] = ar_val

    return jsonify({
        'success': True,
        'model': sess['model'],
        'auto_renew': sess.get('auto_renew', True),
        'web_search': sess['web_search'],
        'image_mode': sess['image_mode'],
        'image_model_id': sess['image_model_id'],
        'aspect_ratio': sess['aspect_ratio'],
    })


@app.route('/api/upload', methods=['POST'])
def api_upload():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401
    
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya bulunamadı'}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'Dosya adı boş'}), 400

    client = sess['client']
    if not client.is_ready:
        client.bootstrap(sess['model'])

    try:
        att = client.upload_file_bytes(file.read(), file.filename, file.content_type)
        return jsonify({'success': True, 'attachment': att})
    except Exception as e:
        return jsonify({'error': f"Yükleme hatası: {e}"}), 500


@app.route('/api/stop', methods=['POST'])
def api_stop():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    partial_text = (data.get('partial_text') or '').strip()
    generated_images = data.get('generated_images') or []

    if partial_text or generated_images:
        history_entry_assistant = {
            'role': 'assistant',
            'text': partial_text,
            'images': generated_images if generated_images else None,
            'at': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        sess['history'].append(history_entry_assistant)
        save_conv_to_history(sess)

    return jsonify({'success': True})


@app.route('/api/send', methods=['POST'])
def api_send():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum bulunamadı'}), 401

    data = request.json or {}
    message_text = (data.get('message') or '').strip()
    attachments = data.get('attachments', [])

    if not message_text and not attachments:
        return jsonify({'error': 'Mesaj boş'}), 400

    client = sess['client']
    if not client.is_ready:
        client.bootstrap(sess['model'])

    web_search = sess.get('web_search', False)
    image_mode = sess.get('image_mode', False)
    image_model_id = sess.get('image_model_id', DEFAULT_IMAGE_MODEL_ID)
    aspect_ratio = sess.get('aspect_ratio', DEFAULT_ASPECT)
    auto_renew = sess.get('auto_renew', True)

    is_new_conv = not sess.get('active_local_conv_id')
    if is_new_conv:
        new_local_conv_id = make_local_conv_id()
        sess['active_local_conv_id'] = new_local_conv_id
    else:
        new_local_conv_id = None

    history_entry_user = {
        'role': 'user',
        'text': message_text,
        'attachments': attachments if attachments else None,
        'at': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    sess['history'].append(history_entry_user)
    save_conv_to_history(sess)

    def generate_sse():
        nonlocal client
        if new_local_conv_id:
            yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': new_local_conv_id})}\n\n"

        assistant_text = ""
        generated_images = []
        rate_limited = False

        def run_ws_stream(text_payload, atts_payload, is_retry=False):
            nonlocal assistant_text, generated_images, rate_limited
            agent_room = str(uuid.uuid4())
            url = (
                f"{WS_BASE}/agents/budget-agent/{agent_room}"
                f"?token={client.jwt}"
                f"&app_token={client.app_token}"
                f"&userId={client.user_id}"
                f"&userType=regular"
                f"&userEmail={client.email}"
                f"&planType=free"
                f"&isTestUser=false"
            )

            user_msg_id = "".join(random.choices(string.ascii_letters + string.digits, k=16))
            parts = []
            if atts_payload:
                for a in atts_payload:
                    parts.append({
                        "type": "file",
                        "mediaType": a.get("mediaType", "application/octet-stream"),
                        "filename": a.get("filename", "file"),
                        "url": a.get("url"),
                    })
            if text_payload:
                parts.append({"type": "text", "text": text_payload})

            resolved_img_model = image_model_id or DEFAULT_IMAGE_MODEL_ID
            provider = next((m["provider"] for m in IMAGE_MODELS if m["id"] == resolved_img_model), "openrouter")

            msg_metadata = {
                "isDeepResearchMode": False,
                "isWebSearchMode": web_search,
                "isAgenticMode": False,
                "isImageGenerationMode": image_mode,
                "needsBlurPreview": True if image_mode else False,
                "deepResearchProcessor": "pro-fast",
                "userId": client.user_id,
                "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
            }
            if image_mode:
                msg_metadata["imageGenerationModel"] = resolved_img_model
                msg_metadata["imageGenerationProvider"] = provider
                msg_metadata["imageGenerationRatio"] = aspect_ratio
                msg_metadata["imageGenerationStyle"] = IMAGE_STYLE
                msg_metadata["imageCount"] = IMAGE_COUNT
                msg_metadata["source"] = "image_funnel"

            client.messages.append({
                "id": user_msg_id,
                "role": "user",
                "parts": parts,
                "metadata": msg_metadata,
            })

            source = "image_funnel" if image_mode else ("websearch" if web_search else "chat_page")
            payload = {
                "chatId": client.chat_id,
                "userId": client.user_id,
                "email": client.email,
                "userType": "regular",
                "userEmail": client.email,
                "planType": "free",
                "subscriptionStatus": "inactive",
                "isFreemium": False,
                "isTestUser": False,
                "cfModelsVariant": "OFF",
                "mixpanelUserId": client.mixpanel_id,
                "deviceId": client.device_id,
                "isWebSearchMode": web_search,
                "isDeepResearchMode": False,
                "isImageGenerationMode": image_mode,
                "agenticMode": False,
                "isStandaloneImageMode": False,
                "needsBlurPreview": True if image_mode else False,
                "deepResearchProcessor": "pro-fast",
                "selectedModel": sess.get('model', DEFAULT_MODEL),
                "locale": "tr",
                "userTimezone": "Europe/Istanbul",
                "userCountry": "Turkey (TR)",
                "messages": client.messages,
                "trigger": "submit-message",
                "source": source,
            }
            if image_mode:
                payload["imageCount"] = IMAGE_COUNT
                payload["imageGenerationModel"] = resolved_img_model
                payload["imageGenerationProvider"] = provider
                payload["imageGenerationRatio"] = aspect_ratio
                payload["imageGenerationStyle"] = IMAGE_STYLE

            ws = websocket.create_connection(url, origin=ORIGIN, header=[f"User-Agent: {UA}"])
            ws.send(json.dumps(payload))

            shown_short_copies = set()
            try:
                while True:
                    raw = ws.recv()
                    if not raw:
                        break
                    try:
                        msg = json.loads(raw)
                    except Exception:
                        continue

                    if msg.get("type") == "rate-limit-error":
                        rate_limited = True
                        break

                    chunk = msg.get("chunk")
                    if chunk:
                        ct = chunk.get("type", "")
                        if ct == "text-delta":
                            delta = chunk.get("delta", "")
                            assistant_text += delta
                            yield f"data: {json.dumps({'type': 'chunk', 'content': delta})}\n\n"

                        elif ct.startswith("tool-image-") and chunk.get("state") == "input-available":
                            inp = chunk.get("input") or {}
                            short = inp.get("shortCopy")
                            if short and short not in shown_short_copies:
                                shown_short_copies.add(short)
                                yield f"data: {json.dumps({'type': 'status', 'content': short})}\n\n"

                        elif ct.startswith("tool-image-") and chunk.get("state") == "output-available":
                            output = chunk.get("output") or {}
                            imgs = output.get("images") or []
                            for im in imgs:
                                u = im.get("url")
                                if u:
                                    generated_images.append(u)
                                    yield f"data: {json.dumps({'type': 'image', 'url': u})}\n\n"

                    if msg.get("type") == "stream-complete":
                        break
            finally:
                try:
                    ws.close()
                except Exception:
                    pass

        yield from run_ws_stream(message_text, attachments if attachments else None)

        if rate_limited:
            if auto_renew:
                yield f"data: {json.dumps({'type': 'status', 'content': 'Hesap limiti doldu, otomatik yeni hesaba geçiş yapılıyor...'})}\n\n"
                prev_history = sess.get('history', [])[:-1]
                history_prefix = format_history_prefix(prev_history)
                text_with_history = history_prefix + message_text

                client = UseAIClient()
                client.bootstrap(sess.get('model', DEFAULT_MODEL))
                sess['client'] = client

                rate_limited = False
                yield from run_ws_stream(text_with_history, attachments if attachments else None, is_retry=True)
            else:
                yield f"data: {json.dumps({'type': 'rate_limit_ask', 'last_message': message_text, 'attachments': attachments})}\n\n"
                return

        history_entry_assistant = {
            'role': 'assistant',
            'text': assistant_text,
            'images': generated_images if generated_images else None,
            'at': datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        sess['history'].append(history_entry_assistant)
        save_conv_to_history(sess)

        yield f"data: {json.dumps({'type': 'done', 'full_text': assistant_text, 'images': generated_images})}\n\n"

    return Response(
        generate_sse(),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
            'Connection': 'close',
        }
    )


@app.route('/api/new_chat', methods=['POST'])
def api_new_chat():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    save_conv_to_history(sess)
    sess['history'] = []
    sess['active_local_conv_id'] = None
    if sess['client']:
        sess['client'].messages = []
        sess['client'].chat_id = str(uuid.uuid4())

    return jsonify({'success': True})


@app.route('/api/reset', methods=['POST'])
def api_reset():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    save_conv_to_history(sess)
    
    try:
        new_client = UseAIClient()
        new_client.bootstrap(sess.get('model', DEFAULT_MODEL))
        sess['client'] = new_client
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True, 'email': new_client.email})


@app.route('/api/history')
def api_history():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'history': []})
    return jsonify({'history': sess.get('history', [])})


@app.route('/api/conversations')
def api_conversations():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'conversations': []})
    convs = sess.get('conversations', [])
    result = [
        {
            'conv_id': c.get('conv_id'),
            'title': c.get('title', 'Konuşma'),
            'count': len(c.get('history', [])) // 2,
        }
        for c in convs
    ]
    return jsonify({'conversations': result})


@app.route('/api/conversation/load', methods=['POST'])
def api_conversation_load():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    conv_id = data.get('conv_id')
    if not conv_id:
        return jsonify({'error': 'Geçersiz id'}), 400

    convs = sess.get('conversations', [])
    for c in convs:
        if c.get('conv_id') == conv_id:
            save_conv_to_history(sess)
            sess['history'] = c['history'][:]
            sess['active_local_conv_id'] = conv_id
            if sess['client']:
                sess['client'].messages = []
                sess['client'].chat_id = str(uuid.uuid4())
            return jsonify({'success': True, 'history': sess['history']})

    return jsonify({'error': 'Konuşma bulunamadı'}), 404


@app.route('/api/conversation/delete', methods=['POST'])
def api_conversation_delete():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    conv_id = data.get('conv_id')
    if not conv_id:
        return jsonify({'error': 'Geçersiz id'}), 400

    convs = sess.get('conversations', [])
    new_convs = [c for c in convs if c.get('conv_id') != conv_id]
    sess['conversations'] = new_convs

    if sess.get('active_local_conv_id') == conv_id:
        sess['history'] = []
        sess['active_local_conv_id'] = None

    return jsonify({'success': True})


@app.route('/api/conversation/rename', methods=['POST'])
def api_conversation_rename():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    conv_id = data.get('conv_id')
    title = (data.get('title') or '').strip()
    if not conv_id or not title:
        return jsonify({'error': 'Geçersiz istek'}), 400

    title = (title[:48] + '…') if len(title) > 48 else title
    for c in sess.get('conversations', []):
        if c.get('conv_id') == conv_id:
            c['title'] = title
            c['title_locked'] = True
            return jsonify({'success': True, 'title': title})

    return jsonify({'error': 'Konuşma bulunamadı'}), 404


if __name__ == '__main__':
    print("UseAI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True)
