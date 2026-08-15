#!/usr/bin/env python3
"""UseAI - Flask Web Interface"""

import json
import mimetypes
import os
import random
import string
import time
import urllib.parse
import uuid
from datetime import datetime
import requests
import websocket
from flask import Flask, render_template, request, jsonify, Response, make_response

app = Flask(__name__)
app.secret_key = os.urandom(24)
# debug=True olsa bile hatalar HTML değil JSON dönsün (frontend'teki "Unexpected token <" fix)
app.config['PROPAGATE_EXCEPTIONS'] = False

# ===================== CONSTANTS =====================
API_BASE = "https://api.use.ai"
AGENTS_BASE = "https://agents.use.ai"
FILES_BASE = "https://files.use.ai"
WS_BASE = "wss://use.ai/agent"
ORIGIN = "https://use.ai"
REFERER = "https://use.ai/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36")
APP_PASSWORD = "123"

# Akış davranışı
IDLE_TIMEOUT = 180.0      # bu kadar saniye hiç veri gelmezse akış ölmüş sayılır
PING_INTERVAL = 15.0     # SSE keepalive aralığı
WS_CONNECT_TIMEOUT = 25  # handshake timeout

# ---------- MODEL KATALOĞU (chat) ----------
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
        "Gemini 3.6 Flash": "gateway-gemini-3-6-flash",
        "Grok 4.5": "gateway-grok-4-5",
        "Grok 4.3": "gateway-grok-4-3",
        "Kimi K3": "gateway-kimi-k3",
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

# ---------- IMAGE MODELS ----------
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
    ("1:1",  "Kare"),
    ("4:3",  "Standart"),
    ("3:4",  "Dikey"),
    ("16:9", "Geniş ekran"),
    ("9:16", "Mobil"),
    ("21:9", "Ultra geniş"),
]
DEFAULT_ASPECT = "16:9"
IMAGE_COUNT = 1
IMAGE_STYLE = "none"

_sessions = {}

# ===================== HELPERS =====================
def get_sid():
    return request.cookies.get('ua_sid')

def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None

def new_sess(sid):
    _sessions[sid] = {
        'app_unlocked': False,
        'client': None,
        'model': DEFAULT_MODEL,
        'history': [],
        'conversations': [],
        'active_local_conv_id': None,
        'web_search': False,
        'image_mode': False,
        'image_model': DEFAULT_IMAGE_MODEL_ID,
        'aspect_ratio': DEFAULT_ASPECT,
        'aborted': False,
        'active_ws': None,
        'total_credits': 0,
        'total_cost': 0.0,
    }
    return _sessions[sid]

def rand_email() -> str:
    local = "".join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(8, 12)))
    return f"{local}@spamok.com"

def new_session() -> requests.Session:
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

def guess_mime(path: str, filename: str = None) -> str:
    if filename:
        mt, _ = mimetypes.guess_type(filename)
    else:
        mt, _ = mimetypes.guess_type(path)
    return mt or "application/octet-stream"

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

    def email_login(self):
        self.session = new_session()
        self.email = rand_email()
        r = self.session.post(
            f"{API_BASE}/v1/auth/email-login",
            headers={"content-type": "application/json"},
            data=json.dumps({"email": self.email}),
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
        )
        r.raise_for_status()
        data = r.json()
        self.user_id = data["userId"]
        self.auth_token = r.headers.get("set-auth-token", "")

    def get_session(self):
        r = self.session.get(f"{API_BASE}/v1/auth/get-session")
        r.raise_for_status()
        self.jwt = r.headers.get("set-auth-jwt", "")
        data = r.json()
        self.user_id = data["user"]["id"]

    def set_model(self, model: str = DEFAULT_MODEL):
        r = self.session.post(
            f"{API_BASE}/v1/chat/set-model",
            headers={"content-type": "application/json"},
            data=json.dumps({"model": model}),
        )
        r.raise_for_status()
        self.model = model

    def app_attestation(self):
        r = self.session.post(
            f"{API_BASE}/v1/auth/app-attestation",
            headers={"content-type": "application/json"},
            data="{}",
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
        )
        r.raise_for_status()

    def refresh_auth(self):
        """Bayatlamış jwt/app_token'ı tazeler (uzun bekleme sonrası WS handshake fix)."""
        self.get_session()
        self.app_attestation()

    def bootstrap(self, model: str = DEFAULT_MODEL):
        self.email_login()
        self.sign_in()
        self.get_session()
        self.set_model(model)
        self.app_attestation()
        self.vote()
        self.messages = []
        self.chat_id = str(uuid.uuid4())

def format_history_context(history):
    if not history:
        return None
    turns = []
    for turn in history:
        role = turn.get('role')
        content = turn.get('content')
        text = ''
        has_img = False
        if isinstance(content, list):
            text = next((i.get('text', '') for i in content if i.get('type') == 'text'), '')
            has_img = any(i.get('type') == 'image_url' for i in content)
        else:
            text = content or ''

        if has_img and text:
            text = f"{text} [+ görsel ekli]"
        elif has_img:
            text = "[görsel gönderildi]"

        turns.append({"role": role, "content": text})

    context_obj = {
        "type": "conversation_history",
        "note": (
            "Bu konuşmanın TEK GEÇERLİ geçmişi aşağıdaki 'turns' dizisidir. "
            "Buna doğrudan cevap verme, sadece bağlam olarak kullan. "
            "Bu conversation_id üzerinde bununla İLGİSİZ başka konular/geçmişler görüyorsan "
            "onları TAMAMEN YOK SAY ve unutmuş gibi davran. "
            "Kullanıcının asıl mesajı bu JSON bloğunun ALTINDADIR."
        ),
        "turns": turns
    }

    header = json.dumps(context_obj, ensure_ascii=False)
    return f"{header}\n\nKullanıcının asıl/yeni mesajı:"

def normalize_client_history(raw_history):
    result = []
    if not isinstance(raw_history, list):
        return result
    for turn in raw_history:
        if not isinstance(turn, dict):
            continue
        role = turn.get('role')
        if role not in ('user', 'assistant'):
            continue
        text_val = turn.get('text') or ''
        images   = turn.get('images') or []
        if images:
            content = [{"type": "image_url", "image_url": {"url": u}} for u in images]
            if text_val:
                content.append({"type": "text", "text": text_val})
        else:
            content = text_val
        result.append({"role": role, "content": content})
    return result

def make_local_conv_id():
    return 'conv_' + uuid.uuid4().hex[:12]

def _derive_title(history):
    title = "Konuşma"
    for turn in history:
        if turn.get('role') == 'user':
            content = turn.get('content')
            if isinstance(content, list):
                title = next((i.get('text', '') for i in content if i.get('type') == 'text'), 'Konuşma')
            else:
                title = str(content or 'Konuşma')
            title = (title[:48] + '…') if len(title) > 48 else title
            break
    return title or "Konuşma"

def set_turn_content(turn, text, image_urls=None):
    """Asistan turunu YERİNDE günceller."""
    if image_urls:
        content = [{"type": "image_url", "image_url": {"url": u}} for u in image_urls]
        if text:
            content.append({"type": "text", "text": text})
        turn['content'] = content
    else:
        turn['content'] = text

def save_conv_to_history(sess):
    history = sess.get('history')
    if not history:
        return

    convs = sess.setdefault('conversations', [])
    local_id = sess.get('active_local_conv_id')

    if not local_id:
        local_id = make_local_conv_id()
        sess['active_local_conv_id'] = local_id

    for c in convs:
        if c.get('conv_id') == local_id:
            c['history'] = history
            if not c.get('title_locked'):
                c['title'] = _derive_title(history)
            return

    convs.insert(0, {
        'conv_id': local_id,
        'title': _derive_title(history),
        'history': history,
    })
    sess['conversations'] = convs[:30]

def _switch_to_conv(sess, conv_id):
    convs = sess.get('conversations', [])
    for c in convs:
        if c.get('conv_id') == conv_id:
            save_conv_to_history(sess)

            client = sess.get('client')
            if client:
                client.messages = []
                client.chat_id = str(uuid.uuid4())

            sess['history'] = c['history']
            sess['active_local_conv_id'] = conv_id
            return True, conv_id, len(c['history']) // 2
    return False, None, 0

# ===================== CHAT STREAM =====================
def _build_ws_url(client, agent_room):
    encoded_email = urllib.parse.quote(client.email)
    return (
        f"{WS_BASE}/agents/budget-agent/{agent_room}"
        f"?token={client.jwt}"
        f"&app_token={client.app_token}"
        f"&userId={client.user_id}"
        f"&userType=regular"
        f"&userEmail={encoded_email}"
        f"&planType=free"
        f"&isTestUser=false"
    )

def _build_ws_headers(client):
    cookie_str = ""
    if client and client.session:
        cookie_str = "; ".join(
            [f"{k}={v}" for k, v in client.session.cookies.get_dict().items()]
        )
    headers = [
        f"User-Agent: {UA}",
        "Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control: no-cache",
        "Pragma: no-cache",
    ]
    if cookie_str:
        headers.append(f"Cookie: {cookie_str}")
    return headers

def stream_message(client, text_message, attachments, web_search, image_mode,
                   image_model_id, aspect_ratio, sess,
                   on_delta=None, on_images=None):
    agent_room = str(uuid.uuid4())

    user_msg_id = "".join(random.choices(string.ascii_letters + string.digits, k=16))

    parts = []
    if attachments:
        for a in attachments:
            parts.append({
                "type": "file",
                "mediaType": a.get("mediaType") or a.get("type", "image/jpeg"),
                "filename": a.get("filename", "file"),
                "url": a["url"],
            })
    if text_message:
        parts.append({"type": "text", "text": text_message})

    resolved_img_model = image_model_id or DEFAULT_IMAGE_MODEL_ID
    provider = next(
        (m["provider"] for m in IMAGE_MODELS if m["id"] == resolved_img_model),
        "openrouter",
    )

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

    user_message = {
        "id": user_msg_id,
        "role": "user",
        "parts": parts,
        "metadata": msg_metadata,
    }

    # ---- BAĞLANTI (generator içinde) ----
    ws = None
    connect_err = None
    for attempt in range(2):
        try:
            ws_headers = _build_ws_headers(client)
            ws = websocket.create_connection(
                _build_ws_url(client, agent_room),
                origin=ORIGIN,
                header=ws_headers,
                timeout=WS_CONNECT_TIMEOUT,
            )
            break
        except Exception as e:
            connect_err = e
            ws = None
            if attempt == 0:
                try:
                    client.refresh_auth()
                except Exception:
                    pass
                time.sleep(0.4)

    if ws is None:
        yield f"data: {json.dumps({'type': 'error', 'code': f'WS_CONNECT_FAILED: {connect_err}'})}\n\n"
        return

    client.messages.append(user_message)

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
        "selectedModel": client.model,
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

    sess['active_ws'] = ws
    ws.settimeout(0.5)

    assistant_text = ""
    assistant_id = ""
    image_parts = []
    image_urls = []
    aborted_time = None
    rate_limited = False
    finished = False
    fatal_error = None
    client_gone = False
    last_data = time.time()
    last_ping = time.time()

    try:
        try:
            ws.send(json.dumps(payload))

            while True:
                if sess.get('aborted'):
                    if aborted_time is None:
                        aborted_time = time.time()
                    elif time.time() - aborted_time > 1.5:
                        break

                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    now = time.time()
                    if now - last_data > IDLE_TIMEOUT:
                        break
                    if now - last_ping > PING_INTERVAL and not sess.get('aborted'):
                        last_ping = now
                        yield ": keepalive\n\n"
                    continue
                except Exception:
                    break

                if not raw:
                    break

                last_data = time.time()

                try:
                    msg = json.loads(raw)
                except Exception:
                    continue

                if msg.get("type") == "rate-limit-error":
                    rate_limited = True
                    finished = True
                    yield f"data: {json.dumps({'type': 'error', 'code': 'RATE_LIMITED'})}\n\n"
                    break

                chunk = msg.get("chunk")
                if chunk:
                    ct = chunk.get("type", "")
                    if ct == "start":
                        assistant_id = chunk.get("messageId", "")

                    elif ct == "text-delta":
                        delta = chunk.get("delta", "")
                        if delta:
                            assistant_text += delta
                            if on_delta:
                                on_delta(assistant_text)
                            if not sess.get('aborted'):
                                yield f"data: {json.dumps({'type': 'chunk', 'content': delta})}\n\n"

                    elif ct.startswith("tool-image-") and chunk.get("state") == "input-available":
                        inp = chunk.get("input") or {}
                        shortCopy = inp.get("shortCopy")
                        if shortCopy and not sess.get('aborted'):
                            yield f"data: {json.dumps({'type': 'image_status', 'message': shortCopy})}\n\n"

                    elif ct.startswith("tool-image-") and chunk.get("state") == "output-available":
                        output = chunk.get("output") or {}
                        imgs = output.get("images") or []
                        urls = []
                        for im in imgs:
                            u = im.get("url")
                            if u:
                                urls.append(u)
                                image_urls.append(u)
                                image_parts.append({
                                    "type": "image",
                                    "url": u,
                                    "mediaType": im.get("mimeType", "image/jpeg"),
                                    "width": im.get("width"),
                                    "height": im.get("height"),
                                })
                        if urls:
                            if on_images:
                                on_images(assistant_text, image_urls)
                            if not sess.get('aborted'):
                                yield f"data: {json.dumps({'type': 'image_result', 'urls': urls})}\n\n"

                    elif ct == "finish":
                        pass

                if msg.get("type") == "stream-complete":
                    finished = True
                    yield f"data: {json.dumps({'type': 'done', 'full_response': assistant_text})}\n\n"
                    break

        except GeneratorExit:
            client_gone = True
            raise
        except Exception as e:
            fatal_error = str(e)

    finally:
        try:
            ws.close()
        except Exception:
            pass
        if sess.get('active_ws') == ws:
            sess.pop('active_ws', None)

        if not rate_limited and (assistant_text or image_parts):
            asst_parts = []
            if assistant_text:
                asst_parts.append({"type": "text", "text": assistant_text})
            asst_parts.extend(image_parts)

            client.messages.append({
                "id": assistant_id or "".join(random.choices(string.ascii_letters + string.digits, k=16)),
                "role": "assistant",
                "parts": asst_parts,
                "metadata": {
                    "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                    "modelId": client.model,
                },
            })
        elif rate_limited and client.messages and client.messages[-1]["role"] == "user":
            client.messages.pop()

        if on_images:
            on_images(assistant_text, image_urls)
        elif on_delta:
            on_delta(assistant_text)

    if client_gone:
        return

    if not finished and not rate_limited:
        if assistant_text or image_urls:
            yield f"data: {json.dumps({'type': 'stream_interrupted', 'full_response': assistant_text})}\n\n"
        else:
            code = fatal_error or 'STREAM_CLOSED_EMPTY'
            yield f"data: {json.dumps({'type': 'error', 'code': code})}\n\n"

# ===================== ROUTES =====================
@app.errorhandler(Exception)
def _json_error_handler(e):
    code = getattr(e, 'code', 500)
    if not isinstance(code, int):
        code = 500
    return jsonify({'error': str(e), 'status': code}), code

@app.route('/')
def index():
    resp = make_response(render_template('index.html'))
    if not request.cookies.get('ua_sid'):
        sid = str(uuid.uuid4())
        resp.set_cookie('ua_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp

@app.route('/api/models')
def api_models():
    result = []
    for category, items in MODELS.items():
        for name, mid in items.items():
            result.append({'id': mid, 'label': name, 'category': category})
    return jsonify({'models': result})

@app.route('/api/image_models')
def api_image_models():
    return jsonify({'models': IMAGE_MODELS, 'default': DEFAULT_IMAGE_MODEL_ID})

@app.route('/api/aspect_ratios')
def api_aspect_ratios():
    return jsonify({'ratios': [{'id': r[0], 'label': r[1]} for r in ASPECT_RATIOS], 'default': DEFAULT_ASPECT})

@app.route('/api/toggle_feature', methods=['POST'])
def api_toggle_feature():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401
    data = request.json or {}
    feature = data.get('feature')
    value = data.get('value')
    if feature:
        if feature == 'web_search':
            sess['web_search'] = bool(value)
        elif feature == 'image_mode':
            sess['image_mode'] = bool(value)
        elif feature == 'image_model':
            sess['image_model'] = value
        elif feature == 'aspect_ratio':
            sess['aspect_ratio'] = value
    else:
        if 'web_search' in data:
            sess['web_search'] = bool(data['web_search'])
        if 'image_mode' in data:
            sess['image_mode'] = bool(data['image_mode'])
        if 'image_model' in data:
            sess['image_model'] = data['image_model']
        if 'aspect_ratio' in data:
            sess['aspect_ratio'] = data['aspect_ratio']
    return jsonify({'success': True})

@app.route('/api/status')
def api_status():
    sess = get_sess()
    if not sess or not sess.get('app_unlocked'):
        return jsonify({'initialized': False})
    return jsonify({
        'initialized': True,
        'account_created': bool(sess.get('client')),
        'email': sess['client'].email if sess.get('client') else '',
        'model': sess.get('model', DEFAULT_MODEL),
        'message_count': len(sess.get('history', [])) // 2,
        'total_credits': sess.get('total_credits', 0),
        'total_cost': round(sess.get('total_cost', 0.0), 5),
    })

@app.route('/api/init', methods=['POST'])
def api_init():
    data = request.json or {}
    if data.get('password') != APP_PASSWORD:
        return jsonify({'success': False, 'error': 'Hatalı şifre.'}), 401

    sid = get_sid() or str(uuid.uuid4())
    sess = new_sess(sid)
    sess['app_unlocked'] = True

    resp = jsonify({'success': True, 'account_created': False, 'model': sess['model']})
    resp.set_cookie('ua_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp

@app.route('/api/logout', methods=['POST'])
def api_logout():
    sid = get_sid()
    if sid and sid in _sessions:
        del _sessions[sid]
    resp = jsonify({'success': True})
    resp.set_cookie('ua_sid', '', expires=0)
    return resp

@app.route('/api/send', methods=['POST'])
def api_send():
    sess = get_sess()
    if not sess or not sess.get('client'):
        return jsonify({'error': 'Oturum bulunamadı.'}), 401

    sess['aborted'] = False

    data = request.json or {}
    message = data.get('message', '').strip()
    attachments = data.get('attachments', [])

    if not message:
        return jsonify({'error': 'Mesaj boş.'}), 400

    client = sess['client']

    prior_history = sess.get('history', [])
    if prior_history and not client.messages:
        ctx = format_history_context(prior_history)
        api_message = f"{ctx}\n{message}"
    else:
        api_message = message

    is_new_conv = not sess.get('active_local_conv_id')
    new_local_conv_id = make_local_conv_id() if is_new_conv else None
    if is_new_conv:
        sess['active_local_conv_id'] = new_local_conv_id

    user_content = (
        [{"type": "image_url", "image_url": {"url": a["url"]}} for a in attachments]
        + [{"type": "text", "text": message}]
    ) if attachments else message

    target_history = sess['history']
    assistant_turn = {"role": "assistant", "content": ""}

    target_history.append({"role": "user", "content": user_content})
    target_history.append(assistant_turn)

    save_conv_to_history(sess)

    web_search = data.get('web_search', sess.get('web_search', False))
    image_mode = data.get('image_mode', sess.get('image_mode', False))
    image_model_id = data.get('image_model', sess.get('image_model', DEFAULT_IMAGE_MODEL_ID))
    aspect_ratio = data.get('aspect_ratio', sess.get('aspect_ratio', DEFAULT_ASPECT))

    def on_delta(text_so_far):
        set_turn_content(assistant_turn, text_so_far, None)

    def on_images(text_so_far, urls):
        set_turn_content(assistant_turn, text_so_far, urls)

    def generate():
        if new_local_conv_id:
            yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': new_local_conv_id})}\n\n"

        try:
            for event in stream_message(
                client, api_message, attachments, web_search, image_mode,
                image_model_id, aspect_ratio, sess,
                on_delta=on_delta, on_images=on_images,
            ):
                yield event
        except GeneratorExit:
            pass
        finally:
            try:
                save_conv_to_history(sess)
            except Exception:
                pass

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                             'Connection': 'close'})

@app.route('/api/abort', methods=['POST'])
def api_abort():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum bulunamadı.'}), 401

    sess['aborted'] = True
    return jsonify({'success': True})

@app.route('/api/upload', methods=['POST'])
def api_upload():
    sess = get_sess()
    if not sess or not sess.get('client'):
        return jsonify({'error': 'Oturum yok'}), 401
    if 'file' not in request.files:
        return jsonify({'error': 'Dosya eksik'}), 400

    file = request.files['file']
    client = sess['client']

    filename = file.filename
    mime = guess_mime("", filename=filename)
    file_bytes = file.read()

    files = {
        "name": (None, filename),
        "type": (None, mime),
        "file": (filename, file_bytes, mime),
    }
    try:
        r = client.session.post(
            f"{FILES_BASE}/upload",
            files=files,
            headers={"authorization": f"Bearer {client.jwt}"},
            timeout=60,
        )
    except Exception as e:
        return jsonify({'error': f'Yükleme hatası: {str(e)}'}), 500

    if r.status_code in (200, 201):
        try:
            data = r.json()
        except Exception:
            return jsonify({'error': 'Yanıt ayrıştırılamadı'}), 500
        if data.get("success"):
            rel = data["url"]
            full_url = f"{FILES_BASE}{rel}" if rel.startswith("/") else rel
            return jsonify({
                'url': full_url,
                'type': mime,
                'name': filename,
                'mediaType': mime,
                'filename': filename,
            })
        return jsonify({'error': f'Upload başarısız: {data}'}), 500
    return jsonify({'error': f'Yükleme başarısız ({r.status_code})'}), 500

@app.route('/api/new_chat', methods=['POST'])
def api_new_chat():
    sess = get_sess()
    if not sess or not sess.get('client'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    carry = data.get('carry_history', False)
    carry_conv_id = data.get('conv_id')

    carry_history = None
    carry_local_id = None
    if carry:
        if carry_conv_id:
            for c in sess.get('conversations', []):
                if c.get('conv_id') == carry_conv_id:
                    carry_history = c['history']
                    carry_local_id = carry_conv_id
                    break
        if carry_history is None and sess.get('history'):
            carry_history = sess['history']
            carry_local_id = sess.get('active_local_conv_id')

    save_conv_to_history(sess)

    client = sess['client']
    client.messages = []
    client.chat_id = str(uuid.uuid4())

    new_conv_id = None
    if carry_history:
        sess['history'] = carry_history
        sess['active_local_conv_id'] = carry_local_id
        new_conv_id = carry_local_id
        save_conv_to_history(sess)
    else:
        sess['history'] = []
        sess['active_local_conv_id'] = None

    return jsonify({'success': True, 'new_conv_id': new_conv_id, 'carried': bool(carry_history)})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    data = request.json or {}
    carry = data.get('carry_history', False)
    carry_conv_id = data.get('conv_id')

    sid = get_sid() or str(uuid.uuid4())
    old_sess = get_sess()
    model = old_sess.get('model', DEFAULT_MODEL) if old_sess else DEFAULT_MODEL

    carry_history = None
    carry_local_id = None
    if carry and old_sess:
        if carry_conv_id:
            for c in old_sess.get('conversations', []):
                if c.get('conv_id') == carry_conv_id:
                    carry_history = c['history']
                    carry_local_id = carry_conv_id
                    break
        if carry_history is None and old_sess.get('history'):
            carry_history = old_sess['history']
            carry_local_id = old_sess.get('active_local_conv_id')

    if old_sess:
        save_conv_to_history(old_sess)
    old_conversations = old_sess.get('conversations', []) if old_sess else []

    sess = new_sess(sid)
    sess['app_unlocked'] = True
    sess['model'] = model
    sess['conversations'] = old_conversations

    try:
        client = UseAIClient()
        client.bootstrap(model=model)
        sess['client'] = client
    except Exception as e:
        if old_sess:
            _sessions[sid] = old_sess
        return jsonify({'success': False, 'error': f'Hesap oluşturulamadı: {str(e)}'}), 500

    new_conv_id = None
    if carry_history:
        sess['history'] = carry_history
        sess['active_local_conv_id'] = carry_local_id
        new_conv_id = carry_local_id
        save_conv_to_history(sess)

    resp_data = {
        'success': True, 'email': client.email, 'model': model,
        'carried': bool(carry_history), 'new_conv_id': new_conv_id,
    }
    resp = jsonify(resp_data)
    resp.set_cookie('ua_sid', sid, max_age=86400 * 30, samesite='Lax')
    return resp

@app.route('/api/model', methods=['POST'])
def api_model():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401
    data = request.json or {}
    model = data.get('model', '')

    sess['model'] = model

    client = sess.get('client')
    if not client:
        return jsonify({'success': True, 'model': model})

    if sess.get('active_local_conv_id'):
        client.set_model(model)
        return jsonify({'success': True, 'model': model})

    client.set_model(model)
    client.messages = []
    client.chat_id = str(uuid.uuid4())
    sess['history'] = []
    sess['active_local_conv_id'] = None

    return jsonify({'success': True, 'model': model})

@app.route('/api/clear', methods=['POST'])
def api_clear():
    sess = get_sess()
    if not sess or not sess.get('client'):
        return jsonify({'error': 'Oturum yok'}), 401
    save_conv_to_history(sess)
    sess['history'] = []
    sess['active_local_conv_id'] = None
    client = sess['client']
    client.messages = []
    client.chat_id = str(uuid.uuid4())
    return jsonify({'success': True})

@app.route('/api/history')
def api_history():
    sess = get_sess()
    if not sess:
        return jsonify({'history': []})
    simplified = []
    for turn in list(sess.get('history', [])):
        role = turn.get('role')
        content = turn.get('content')
        if isinstance(content, list):
            text = next((i.get('text', '') for i in content if i.get('type') == 'text'), '')
            images = [i['image_url']['url'] for i in content if i.get('type') == 'image_url']
            simplified.append({'role': role, 'text': text, 'images': images})
        else:
            simplified.append({'role': role, 'text': content or '', 'images': []})
    return jsonify({
        'history': simplified,
        'conv_id': sess.get('active_local_conv_id'),
        'streaming': bool(sess.get('active_ws')),
    })

@app.route('/api/conversations')
def api_conversations():
    sess = get_sess()
    if not sess:
        return jsonify({'conversations': []})
    convs = sess.get('conversations', [])
    result = [
        {
            'idx': i,
            'conv_id': c.get('conv_id', str(i)),
            'title': c['title'],
            'count': len(c['history']) // 2,
        }
        for i, c in enumerate(convs)
    ]
    return jsonify({'conversations': result})

@app.route('/api/conversation/load', methods=['POST'])
def api_conversation_load():
    sess = get_sess()
    if not sess or not sess.get('client'):
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    conv_id = data.get('conv_id')
    idx = data.get('idx')

    convs = sess.get('conversations', [])

    if not conv_id and idx is not None:
        try:
            i = int(idx)
            if 0 <= i < len(convs):
                conv_id = convs[i].get('conv_id', str(i))
        except (ValueError, TypeError):
            pass

    if not conv_id:
        return jsonify({'error': 'Konuşma bulunamadı'}), 404

    ok, cid, msg_count = _switch_to_conv(sess, conv_id)
    if ok:
        return jsonify({'success': True, 'conv_id': cid, 'message_count': msg_count})
    return jsonify({'error': 'Konuşma bulunamadı'}), 404

@app.route('/api/conversation/delete', methods=['POST'])
def api_conversation_delete():
    sess = get_sess()
    if not sess:
        return jsonify({'error': 'Oturum yok'}), 401

    data = request.json or {}
    conv_id = data.get('conv_id')
    if not conv_id:
        return jsonify({'error': 'Konuşma bulunamadı'}), 404

    convs = sess.get('conversations', [])
    new_convs = [c for c in convs if c.get('conv_id') != conv_id]
    if len(new_convs) == len(convs):
        return jsonify({'error': 'Konuşma bulunamadı'}), 404
    sess['conversations'] = new_convs

    if sess.get('active_local_conv_id') == conv_id:
        sess['history'] = []
        sess['active_local_conv_id'] = None
        if sess.get('client'):
            sess['client'].messages = []
            sess['client'].chat_id = str(uuid.uuid4())

    return jsonify({'success': True})

@app.route('/api/conversation/rename', methods=['POST'])
def api_conversation_rename():
    sess = get_sess()
    if not sess:
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
    print("Use AI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(debug=True, host='0.0.0.0', port=5000, threaded=True, use_reloader=False)
