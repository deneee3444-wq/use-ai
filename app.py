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
from flask import Flask, Response, jsonify, make_response, render_template, request

app = Flask(__name__)
app.secret_key = os.urandom(24)
# debug=True olsa bile hatalar HTML değil JSON dönsün (frontend'teki "Unexpected token <" fix)
app.config["PROPAGATE_EXCEPTIONS"] = False

# ===================== CONSTANTS =====================
API_BASE = "https://use.ai"
AGENTS_BASE = "https://agents.use.ai"
FILES_BASE = "https://files.use.ai"
WS_BASE = "wss://use.ai/agent"
ORIGIN = "https://use.ai"
REFERER = "https://use.ai/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
)
APP_PASSWORD = "123"

# Akış davranışı
IDLE_TIMEOUT = 180.0  # bu kadar saniye hiç veri gelmezse akış ölmüş sayılır
PING_INTERVAL = 15.0  # SSE keepalive aralığı
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
    {"id": "nano-banana", "label": "Nano Banana", "provider": "openrouter"},
    {"id": "nano-banana-2", "label": "Nano Banana 2", "provider": "openrouter"},
    {
        "id": "nano-banana-pro",
        "label": "Nano Banana Pro",
        "provider": "openrouter",
    },
    {"id": "seedream-4.5", "label": "Seedream 4.5", "provider": "openrouter"},
    {"id": "flux-2-pro", "label": "FLUX.2 Pro", "provider": "openrouter"},
    {"id": "flux-2-flex", "label": "FLUX.2 Flex", "provider": "openrouter"},
    {"id": "flux-2-max", "label": "FLUX.2 Max", "provider": "openrouter"},
]
DEFAULT_IMAGE_MODEL_ID = "nano-banana-2"

ASPECT_RATIOS = [
    ("1:1", "Kare"),
    ("4:3", "Standart"),
    ("3:4", "Dikey"),
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
    return request.cookies.get("ua_sid")


def get_sess():
    sid = get_sid()
    return _sessions.get(sid) if sid else None


def new_sess(sid):
    _sessions[sid] = {
        "app_unlocked": False,
        "client": None,
        "model": DEFAULT_MODEL,
        "history": [],
        "conversations": [],
        "active_local_conv_id": None,
        "web_search": False,
        "image_mode": False,
        "image_model": DEFAULT_IMAGE_MODEL_ID,
        "aspect_ratio": DEFAULT_ASPECT,
        "auto_attach": False,
        "aborted": False,
        "active_ws": None,
        "total_credits": 0,
        "total_cost": 0.0,
    }
    return _sessions[sid]


def rand_email() -> str:
    """10 haneli rastgele prefix üreterek @spamok.com döndürür."""
    local = "".join(
        random.choices(string.ascii_lowercase + string.digits, k=10)
    )
    return f"{local}@spamok.com"


def new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
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
        }
    )
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

    def init_session(self):
        """[ÇÖZÜM 1] İlk olarak GET /tr çağrısı yaparak sunucu çerezlerini (guest_mixpanel_id, guest_user_id) toplar."""
        self.session = new_session()
        r = self.session.get(
            f"{API_BASE}/tr",
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "sec-fetch-dest": "document",
                "sec-fetch-mode": "navigate",
                "sec-fetch-site": "none",
                "sec-fetch-user": "?1",
                "upgrade-insecure-requests": "1",
            },
        )
        r.raise_for_status()

        # Çerezleri otomatik yakala, yoksa yeni UUID üret
        self.mixpanel_id = self.session.cookies.get(
            "guest_mixpanel_id"
        ) or str(uuid.uuid4())
        self.guest_id = self.session.cookies.get("guest_user_id") or str(
            uuid.uuid4()
        )

    def email_login(self):
        if self.session is None:
            self.init_session()

        self.email = rand_email()
        payload = {"email": self.email, "mixpanelUserId": self.mixpanel_id}
        r = self.session.post(
            f"{API_BASE}/v1/auth/email-login",
            headers={"content-type": "application/json"},
            data=json.dumps(payload),
        )
        r.raise_for_status()

    def sign_in(self):
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
        r = self.session.get(
            f"{API_BASE}/v1/auth/get-session",
            params={"disableCookieCache": "true"},
        )
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

    def vote(self, chat_id: str | None = None):
        if chat_id:
            self.chat_id = chat_id
        elif not self.chat_id:
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
        return self.chat_id

    def refresh_auth(self):
        """Bayatlamış jwt/app_token'ı tazeler (uzun bekleme sonrası WS handshake fix)."""
        try:
            self.get_session()
        except Exception:
            try:
                self.email_login()
                self.sign_in()
                self.get_session()
            except Exception:
                pass
        try:
            self.app_attestation()
        except Exception:
            pass
        try:
            if self.chat_id:
                self.vote(self.chat_id)
        except Exception:
            pass

    def bootstrap(self, model: str = DEFAULT_MODEL):
        self.init_session()  # 1. GET /tr ile çerezleri topla
        self.email_login()  # 2. Email login
        self.sign_in()  # 3. Credentials sign in
        self.get_session()  # 4. Get session & JWT
        self.set_model(model)  # 5. Model seçimi
        self.app_attestation()  # 6. App attestation token
        self.vote()  # 7. Initial vote / room hazirlik (self.chat_id set & voted)
        self.messages = []


def get_filename_from_url(url: str | None, default_name: str | None = None) -> str:
    """URL'in sonundaki gerçek dosya ismini (decoded) döner."""
    if default_name and str(default_name).strip():
        name = str(default_name).strip()
        if "%2F" in name or "%2f" in name:
            name = urllib.parse.unquote(name).split("/")[-1]
        elif "/" in name:
            name = name.split("/")[-1]
        if name:
            return name
    if not url:
        return "Dosya"
    unquoted = urllib.parse.unquote(str(url))
    return unquoted.split("?")[0].split("/")[-1] or "Dosya"


def normalize_url(url: str | None) -> str:
    """Her zaman tam (https://...) URL döndürür."""
    if not url:
        return ""
    u = str(url).strip()
    if u.startswith(("http://", "https://", "data:")):
        return u
    if u.startswith("//"):
        return f"https:{u}"
    if u.startswith("/"):
        return f"{FILES_BASE}{u}"
    return f"https://{u}"


def append_history(
    history: list[dict],
    role: str,
    text: str,
    attachments: list[dict] | None = None,
    images: list[str | dict] | None = None,
) -> dict:
    entry = {
        "role": role,
        "text": text,
        "at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if attachments:
        entry["attachments"] = [
            {
                "filename": a.get("filename") or a.get("name") or get_filename_from_url(normalize_url(a.get("url"))),
                "mediaType": a.get("mediaType") or a.get("type") or guess_mime("", filename=a.get("filename") or a.get("name", "")),
                "url": normalize_url(a.get("url")),
            }
            for a in attachments
        ]
    if images:
        entry["generatedImages"] = _clean_image_list(images)
    history.append(entry)
    return entry


def _clean_image_list(items):
    """Görsel listesini (str veya dict) temiz dict listesine çevirir."""
    result = []
    for item in items:
        if isinstance(item, dict):
            url = normalize_url(item.get("url"))
            fname = item.get("filename") or item.get("name") or get_filename_from_url(url)
            mtype = item.get("mediaType") or item.get("type") or "image/jpeg"
        else:
            url = normalize_url(item)
            fname = get_filename_from_url(url)
            mtype = "image/jpeg"
        result.append({"filename": fname, "mediaType": mtype, "url": url})
    return result


def format_history_prefix(history: list[dict]) -> str:
    if not history:
        return ""
    history_json = json.dumps(history, ensure_ascii=False, indent=2)
    return (
        "--- ÖNCEKİ KONUŞMA GEÇMİŞİ (JSON) ---\n"
        f"{history_json}\n"
        "--- GEÇMİŞ SONU ---\n\n"
        "Yukarıdaki JSON önceki konuşmamdır (role='user' ben, role='assistant' sen). "
        "Ekli dosyaların/görsellerin tam URL'leri 'attachments[].url' ve "
        "'generatedImages[].url' alanlarındadır. "
        "Buna göre aşağıdaki yeni mesajıma cevap ver:\n\n"
    )


def make_local_conv_id():
    return str(uuid.uuid4())


def _derive_title(history):
    title = "Konuşma"
    for turn in history:
        if turn.get("role") == "user":
            text = turn.get("text")
            if not text and "content" in turn:
                content = turn.get("content")
                if isinstance(content, list):
                    text = next(
                        (
                            i.get("text", "")
                            for i in content
                            if i.get("type") == "text"
                        ),
                        "",
                    )
                else:
                    text = str(content or "")
            if not text and turn.get("attachments"):
                text = turn["attachments"][0].get("filename", "Konuşma")
            title = text or "Konuşma"
            title = (title[:48] + "…") if len(title) > 48 else title
            break
    return title or "Konuşma"


def set_turn_content(turn, text, image_urls=None):
    """Asistan turunu YERİNDE günceller."""
    turn["text"] = text
    if image_urls:
        turn["generatedImages"] = _clean_image_list(image_urls)


def save_conv_to_history(sess):
    history = sess.get("history")
    if not history:
        return

    valid_turns = [
        t
        for t in history
        if t.get("text") or t.get("attachments") or t.get("generatedImages")
    ]
    if not valid_turns:
        return

    convs = sess.setdefault("conversations", [])
    local_id = sess.get("active_local_conv_id")

    if not local_id:
        local_id = make_local_conv_id()
        sess["active_local_conv_id"] = local_id

    for c in convs:
        if c.get("conv_id") == local_id:
            c["history"] = history
            if not c.get("title_locked"):
                c["title"] = _derive_title(history)
            return

    convs.insert(
        0,
        {
            "conv_id": local_id,
            "title": _derive_title(history),
            "history": history,
        },
    )
    sess["conversations"] = convs[:30]


def _switch_to_conv(sess, conv_id):
    convs = sess.get("conversations", [])
    for c in convs:
        if c.get("conv_id") == conv_id:
            save_conv_to_history(sess)

            client = sess.get("client")
            if client:
                client.messages = []
                try:
                    client.vote(str(uuid.uuid4()))
                except Exception:
                    client.chat_id = str(uuid.uuid4())

            sess["history"] = c["history"]
            sess["active_local_conv_id"] = conv_id
            return True, conv_id, len(c["history"]) // 2
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


def stream_message(
    client,
    text_message,
    attachments,
    web_search,
    image_mode,
    image_model_id,
    aspect_ratio,
    sess,
    on_start=None,
    on_delta=None,
    on_images=None,
):
    agent_room = str(uuid.uuid4())
    user_msg_id = "".join(
        random.choices(string.ascii_letters + string.digits, k=16)
    )

    parts = []
    if attachments:
        for a in attachments:
            parts.append(
                {
                    "type": "file",
                    "mediaType": a.get("mediaType")
                    or a.get("type", "image/jpeg"),
                    "filename": a.get("filename") or a.get("name", "file"),
                    "url": normalize_url(a.get("url")),
                }
            )
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

    source = (
        "image_funnel"
        if image_mode
        else ("websearch" if web_search else "chat_page")
    )

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

    if not client.chat_id:
        try:
            client.vote(str(uuid.uuid4()))
        except Exception:
            client.chat_id = str(uuid.uuid4())

    for retry_cycle in range(2):
        if retry_cycle > 0:
            try:
                client.refresh_auth()
            except Exception:
                pass
            time.sleep(0.3)
            payload["chatId"] = client.chat_id
            payload["userId"] = client.user_id
            payload["userEmail"] = client.email
            payload["email"] = client.email
            payload["mixpanelUserId"] = client.mixpanel_id

        current_room = str(uuid.uuid4())
        ws = None
        connect_err = None

        try:
            ws_headers = _build_ws_headers(client)
            ws = websocket.create_connection(
                _build_ws_url(client, current_room),
                origin=ORIGIN,
                header=ws_headers,
                timeout=WS_CONNECT_TIMEOUT,
            )
        except Exception as e:
            connect_err = e
            ws = None
            if retry_cycle == 0:
                continue
            else:
                yield f"data: {json.dumps({'type': 'error', 'code': f'WS_CONNECT_FAILED: {connect_err}'})}\n\n"
                return

        client.messages.append(user_message)
        sess["active_ws"] = ws
        ws.settimeout(0.5)

        assistant_text = ""
        assistant_id = ""
        start_fired = False
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
                    if sess.get("aborted"):
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
                        if now - last_ping > PING_INTERVAL and not sess.get(
                            "aborted"
                        ):
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
                            if not start_fired:
                                start_fired = True
                                if on_start:
                                    on_start()
                                yield f"data: {json.dumps({'type': 'start', 'message_id': assistant_id})}\n\n"

                        elif ct == "text-delta":
                            delta = chunk.get("delta", "")
                            if delta:
                                if not start_fired:
                                    start_fired = True
                                    if on_start:
                                        on_start()
                                    yield f"data: {json.dumps({'type': 'start', 'message_id': assistant_id})}\n\n"
                                assistant_text += delta
                                if on_delta:
                                    on_delta(assistant_text)
                                if not sess.get("aborted"):
                                    yield f"data: {json.dumps({'type': 'chunk', 'content': delta})}\n\n"

                        elif (
                            ct.startswith("tool-image-")
                            and chunk.get("state") == "input-available"
                        ):
                            if not start_fired:
                                start_fired = True
                                if on_start:
                                    on_start()
                                yield f"data: {json.dumps({'type': 'start', 'message_id': assistant_id})}\n\n"
                            inp = chunk.get("input") or {}
                            shortCopy = inp.get("shortCopy")
                            if shortCopy and not sess.get("aborted"):
                                yield f"data: {json.dumps({'type': 'image_status', 'message': shortCopy})}\n\n"

                        elif (
                            ct.startswith("tool-image-")
                            and chunk.get("state") == "output-available"
                        ):
                            if not start_fired:
                                start_fired = True
                                if on_start:
                                    on_start()
                                yield f"data: {json.dumps({'type': 'start', 'message_id': assistant_id})}\n\n"
                            output = chunk.get("output") or {}
                            imgs = output.get("images") or []
                            urls = []
                            for im in imgs:
                                u = im.get("url")
                                if u:
                                    urls.append(u)
                                    image_urls.append(u)
                                    image_parts.append(
                                        {
                                            "type": "image",
                                            "url": u,
                                            "mediaType": im.get(
                                                "mimeType", "image/jpeg"
                                            ),
                                            "width": im.get("width"),
                                            "height": im.get("height"),
                                        }
                                    )
                            if urls:
                                if on_images:
                                    on_images(assistant_text, image_urls)
                                if not sess.get("aborted"):
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
            if sess.get("active_ws") == ws:
                sess.pop("active_ws", None)

            if not rate_limited and (assistant_text or image_parts):
                asst_parts = []
                if assistant_text:
                    asst_parts.append({"type": "text", "text": assistant_text})
                asst_parts.extend(image_parts)

                client.messages.append(
                    {
                        "id": assistant_id
                        or "".join(
                            random.choices(
                                string.ascii_letters + string.digits, k=16
                            )
                        ),
                        "role": "assistant",
                        "parts": asst_parts,
                        "metadata": {
                            "createdAt": time.strftime(
                                "%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()
                            ),
                            "modelId": client.model,
                        },
                    }
                )
            elif (
                (rate_limited or not start_fired)
                and client.messages
                and client.messages[-1].get("id") == user_msg_id
            ):
                client.messages.pop()

            if start_fired and not rate_limited and (assistant_text or image_urls):
                if on_images:
                    on_images(assistant_text, image_urls)
                elif on_delta:
                    on_delta(assistant_text)

        if client_gone:
            return

        # Hiç veri/start gelmeden boş kapandıysa ve 1. denemedeysek: sessizce auth tazele ve tekrar bağlan
        if (
            not finished
            and not rate_limited
            and not start_fired
            and not assistant_text
            and retry_cycle == 0
        ):
            continue

        if not finished and not rate_limited:
            if assistant_text or image_urls:
                yield f"data: {json.dumps({'type': 'stream_interrupted', 'full_response': assistant_text})}\n\n"
            else:
                code = fatal_error or "STREAM_CLOSED_EMPTY"
                yield f"data: {json.dumps({'type': 'error', 'code': code})}\n\n"
        break


# ===================== ROUTES =====================
@app.errorhandler(Exception)
def _json_error_handler(e):
    code = getattr(e, "code", 500)
    if not isinstance(code, int):
        code = 500
    return jsonify({"error": str(e), "status": code}), code


@app.route("/")
@app.route("/chat/<conv_id>")
def index(conv_id=None):
    resp = make_response(render_template("index.html"))
    if not request.cookies.get("ua_sid"):
        sid = str(uuid.uuid4())
        resp.set_cookie("ua_sid", sid, max_age=86400 * 30, samesite="Lax")
    return resp


@app.route("/api/models")
def api_models():
    result = []
    for category, items in MODELS.items():
        for name, mid in items.items():
            result.append({"id": mid, "label": name, "category": category})
    return jsonify({"models": result})


@app.route("/api/image_models")
def api_image_models():
    return jsonify({"models": IMAGE_MODELS, "default": DEFAULT_IMAGE_MODEL_ID})


@app.route("/api/aspect_ratios")
def api_aspect_ratios():
    return jsonify(
        {
            "ratios": [{"id": r[0], "label": r[1]} for r in ASPECT_RATIOS],
            "default": DEFAULT_ASPECT,
        }
    )


@app.route("/api/toggle_feature", methods=["POST"])
def api_toggle_feature():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Oturum yok"}), 401
    data = request.json or {}
    feature = data.get("feature")
    value = data.get("value")
    if feature:
        if feature == "web_search":
            sess["web_search"] = bool(value)
        elif feature == "image_mode":
            sess["image_mode"] = bool(value)
        elif feature == "image_model":
            sess["image_model"] = value
        elif feature == "aspect_ratio":
            sess["aspect_ratio"] = value
        elif feature == "auto_attach":
            sess["auto_attach"] = bool(value)
    else:
        if "web_search" in data:
            sess["web_search"] = bool(data["web_search"])
        if "image_mode" in data:
            sess["image_mode"] = bool(data["image_mode"])
        if "image_model" in data:
            sess["image_model"] = data["image_model"]
        if "aspect_ratio" in data:
            sess["aspect_ratio"] = data["aspect_ratio"]
        if "auto_attach" in data:
            sess["auto_attach"] = bool(data["auto_attach"])
    return jsonify({"success": True})


@app.route("/api/status")
def api_status():
    sess = get_sess()
    if not sess or not sess.get("app_unlocked"):
        return jsonify({"initialized": False})
    return jsonify(
        {
            "initialized": True,
            "account_created": bool(sess.get("client")),
            "email": sess["client"].email if sess.get("client") else "",
            "model": sess.get("model", DEFAULT_MODEL),
            "message_count": len(sess.get("history", [])) // 2,
            "total_credits": sess.get("total_credits", 0),
            "total_cost": round(sess.get("total_cost", 0.0), 5),
        }
    )


@app.route("/api/init", methods=["POST"])
def api_init():
    data = request.json or {}
    if data.get("password") != APP_PASSWORD:
        return jsonify({"success": False, "error": "Hatalı şifre."}), 401

    sid = get_sid() or str(uuid.uuid4())
    sess = new_sess(sid)
    sess["app_unlocked"] = True

    resp = jsonify(
        {"success": True, "account_created": False, "model": sess["model"]}
    )
    resp.set_cookie("ua_sid", sid, max_age=86400 * 30, samesite="Lax")
    return resp


@app.route("/api/logout", methods=["POST"])
def api_logout():
    sid = get_sid()
    if sid and sid in _sessions:
        del _sessions[sid]
    resp = jsonify({"success": True})
    resp.set_cookie("ua_sid", "", expires=0)
    return resp


@app.route("/api/send", methods=["POST"])
def api_send():
    sess = get_sess()
    if not sess or not sess.get("client"):
        return jsonify({"error": "Oturum bulunamadı."}), 401

    sess["aborted"] = False

    data = request.json or {}
    message = data.get("message", "").strip()
    attachments = data.get("attachments", [])

    if not message:
        return jsonify({"error": "Mesaj boş."}), 400

    client = sess["client"]

    prior_history = sess.get("history", [])
    if prior_history and not client.messages:
        api_message = format_history_prefix(prior_history) + message
    else:
        api_message = message

    auto_attach = data.get("auto_attach", sess.get("auto_attach", False))
    if auto_attach:
        existing_urls = {a.get("url") for a in attachments if a.get("url")}
        for turn in sess.get("history", []):
            for past_att in turn.get("attachments", []):
                p_url = past_att.get("url")
                if p_url and p_url not in existing_urls:
                    existing_urls.add(p_url)
                    fname = past_att.get("filename") or get_filename_from_url(p_url)
                    mtype = past_att.get("mediaType") or guess_mime("", filename=fname)
                    attachments.append({
                        "url": p_url, "filename": fname,
                        "mediaType": mtype,
                    })
            for gen_img in turn.get("generatedImages", []):
                g_url = gen_img.get("url") if isinstance(gen_img, dict) else gen_img
                if g_url and g_url not in existing_urls:
                    existing_urls.add(g_url)
                    fname = gen_img.get("filename") or get_filename_from_url(g_url) if isinstance(gen_img, dict) else get_filename_from_url(g_url)
                    mtype = gen_img.get("mediaType") or "image/jpeg" if isinstance(gen_img, dict) else "image/jpeg"
                    attachments.append({
                        "url": g_url, "filename": fname,
                        "mediaType": mtype,
                    })

    is_new_conv = not sess.get("active_local_conv_id")
    new_local_conv_id = make_local_conv_id() if is_new_conv else None
    if is_new_conv:
        sess["active_local_conv_id"] = new_local_conv_id

    history_committed = False
    assistant_turn = None

    def commit_history_on_start():
        nonlocal history_committed, assistant_turn
        if history_committed:
            return
        history_committed = True
        target_history = sess.setdefault("history", [])
        append_history(
            target_history,
            "user",
            message,
            attachments=attachments or None,
        )
        assistant_turn = append_history(
            target_history,
            "assistant",
            "",
        )
        save_conv_to_history(sess)

    web_search = data.get("web_search", sess.get("web_search", False))
    image_mode = data.get("image_mode", sess.get("image_mode", False))
    image_model_id = data.get(
        "image_model", sess.get("image_model", DEFAULT_IMAGE_MODEL_ID)
    )
    aspect_ratio = data.get(
        "aspect_ratio", sess.get("aspect_ratio", DEFAULT_ASPECT)
    )

    def on_start():
        commit_history_on_start()

    def on_delta(text_so_far):
        if not history_committed:
            commit_history_on_start()
        if assistant_turn is not None:
            set_turn_content(assistant_turn, text_so_far, None)

    def on_images(text_so_far, urls):
        if not history_committed:
            commit_history_on_start()
        if assistant_turn is not None:
            set_turn_content(assistant_turn, text_so_far, urls)

    conv_id_sent = False

    def generate():
        nonlocal conv_id_sent

        try:
            for event in stream_message(
                client,
                api_message,
                attachments,
                web_search,
                image_mode,
                image_model_id,
                aspect_ratio,
                sess,
                on_start=on_start,
                on_delta=on_delta,
                on_images=on_images,
            ):
                if is_new_conv and not conv_id_sent:
                    if '"type": "start"' in event or '"type": "chunk"' in event or history_committed:
                        conv_id_sent = True
                        yield f"data: {json.dumps({'type': 'conv_id', 'conv_id': new_local_conv_id})}\n\n"
                yield event
        except GeneratorExit:
            pass
        finally:
            try:
                if history_committed:
                    save_conv_to_history(sess)
            except Exception:
                pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "close",
        },
    )


@app.route("/api/abort", methods=["POST"])
def api_abort():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Oturum bulunamadı."}), 401

    sess["aborted"] = True
    return jsonify({"success": True})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    sess = get_sess()
    if not sess or not sess.get("client"):
        return jsonify({"error": "Oturum yok"}), 401
    if "file" not in request.files:
        return jsonify({"error": "Dosya eksik"}), 400

    file = request.files["file"]
    client = sess["client"]

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
        return jsonify({"error": f"Yükleme hatası: {str(e)}"}), 500

    if r.status_code in (200, 201):
        try:
            data = r.json()
        except Exception:
            return jsonify({"error": "Yanıt ayrıştırılamadı"}), 500
        if data.get("success"):
            full_url = normalize_url(data["url"])
            return jsonify(
                {
                    "url": full_url,
                    "type": mime,
                    "name": filename,
                    "mediaType": mime,
                    "filename": filename,
                }
            )
        return jsonify({"error": f"Upload başarısız: {data}"}), 500
    return jsonify({"error": f"Yükleme başarısız ({r.status_code})"}), 500


@app.route("/api/files")
def api_files():
    sess = get_sess()
    if not sess:
        return jsonify({"files": []})

    seen = set()
    files = []

    def add_file(url, filename=None, media_type=None, source_type="attachment"):
        if not url:
            return
        full_url = normalize_url(url)
        if not full_url or full_url in seen:
            return
        seen.add(full_url)

        mtype = media_type or guess_mime(
            "", filename=filename or full_url.split("/")[-1]
        )
        if source_type == "generated" and not (mtype and mtype.startswith("image/")):
            mtype = "image/jpeg"

        fname = filename or get_filename_from_url(full_url)

        files.append({"filename": fname, "mediaType": mtype, "url": full_url})

    def collect_from_turns(turns):
        for turn in turns:
            for a in turn.get("attachments", []):
                add_file(
                    a.get("url"),
                    a.get("filename") or a.get("name"),
                    a.get("mediaType") or a.get("type"),
                    "attachment",
                )
            for img in turn.get("generatedImages", []):
                if isinstance(img, dict):
                    add_file(img.get("url"), img.get("filename") or img.get("name"), img.get("mediaType") or img.get("type") or "image/jpeg", "generated")
                elif isinstance(img, str):
                    add_file(img, None, "image/jpeg", "generated")

    # 1. Mevcut aktif konuşma geçmişi
    collect_from_turns(sess.get("history", []))

    # 2. Kayıtlı diğer tüm konuşmalar
    for conv in sess.get("conversations", []):
        collect_from_turns(conv.get("history", []))

    return jsonify({"files": files})


@app.route("/api/new_chat", methods=["POST"])
def api_new_chat():
    sess = get_sess()
    if not sess or not sess.get("client"):
        return jsonify({"error": "Oturum yok"}), 401

    data = request.json or {}
    carry = data.get("carry_history", False)
    carry_conv_id = data.get("conv_id")

    carry_history = None
    carry_local_id = None
    if carry:
        if carry_conv_id:
            for c in sess.get("conversations", []):
                if c.get("conv_id") == carry_conv_id:
                    carry_history = c["history"]
                    carry_local_id = carry_conv_id
                    break
        if carry_history is None and sess.get("history"):
            carry_history = sess["history"]
            carry_local_id = sess.get("active_local_conv_id")

    save_conv_to_history(sess)

    client = sess["client"]
    client.messages = []
    try:
        client.vote(str(uuid.uuid4()))
    except Exception:
        client.chat_id = str(uuid.uuid4())

    new_conv_id = None
    if carry_history:
        sess["history"] = carry_history
        sess["active_local_conv_id"] = carry_local_id
        new_conv_id = carry_local_id
        save_conv_to_history(sess)
    else:
        sess["history"] = []
        sess["active_local_conv_id"] = None

    return jsonify(
        {"success": True, "new_conv_id": new_conv_id, "carried": bool(carry_history)}
    )


@app.route("/api/reset", methods=["POST"])
def api_reset():
    data = request.json or {}
    carry = data.get("carry_history", False)
    carry_conv_id = data.get("conv_id")

    sid = get_sid() or str(uuid.uuid4())
    old_sess = get_sess()
    model = old_sess.get("model", DEFAULT_MODEL) if old_sess else DEFAULT_MODEL

    carry_history = None
    carry_local_id = None
    if carry and old_sess:
        if carry_conv_id:
            for c in old_sess.get("conversations", []):
                if c.get("conv_id") == carry_conv_id:
                    carry_history = c["history"]
                    carry_local_id = carry_conv_id
                    break
        if carry_history is None and old_sess.get("history"):
            carry_history = old_sess["history"]
            carry_local_id = old_sess.get("active_local_conv_id")

    if old_sess:
        save_conv_to_history(old_sess)
    old_conversations = [
        c
        for c in (old_sess.get("conversations", []) if old_sess else [])
        if any(
            t.get("text") or t.get("attachments") or t.get("generatedImages")
            for t in c.get("history", [])
        )
    ]

    sess = new_sess(sid)
    sess["app_unlocked"] = True
    sess["model"] = model
    sess["conversations"] = old_conversations

    try:
        client = UseAIClient()
        client.bootstrap(model=model)
        sess["client"] = client
    except Exception as e:
        if old_sess:
            _sessions[sid] = old_sess
        return (
            jsonify({"success": False, "error": f"Hesap oluşturulamadı: {str(e)}"}),
            500,
        )

    new_conv_id = None
    if carry_history:
        sess["history"] = carry_history
        sess["active_local_conv_id"] = carry_local_id
        new_conv_id = carry_local_id
        save_conv_to_history(sess)

    resp_data = {
        "success": True,
        "email": client.email,
        "model": model,
        "carried": bool(carry_history),
        "new_conv_id": new_conv_id,
    }
    resp = jsonify(resp_data)
    resp.set_cookie("ua_sid", sid, max_age=86400 * 30, samesite="Lax")
    return resp


@app.route("/api/model", methods=["POST"])
def api_model():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Oturum yok"}), 401
    data = request.json or {}
    model = data.get("model", "")

    sess["model"] = model

    client = sess.get("client")
    if not client:
        return jsonify({"success": True, "model": model})

    if sess.get("active_local_conv_id"):
        client.set_model(model)
        return jsonify({"success": True, "model": model})

    client.set_model(model)
    client.messages = []
    try:
        client.vote(str(uuid.uuid4()))
    except Exception:
        client.chat_id = str(uuid.uuid4())
    sess["history"] = []
    sess["active_local_conv_id"] = None

    return jsonify({"success": True, "model": model})


@app.route("/api/clear", methods=["POST"])
def api_clear():
    sess = get_sess()
    if not sess or not sess.get("client"):
        return jsonify({"error": "Oturum yok"}), 401
    save_conv_to_history(sess)
    sess["history"] = []
    sess["active_local_conv_id"] = None
    client = sess["client"]
    client.messages = []
    try:
        client.vote(str(uuid.uuid4()))
    except Exception:
        client.chat_id = str(uuid.uuid4())
    return jsonify({"success": True})


@app.route("/api/history")
def api_history():
    sess = get_sess()
    if not sess:
        return jsonify({"history": []})
    simplified = []
    for turn in list(sess.get("history", [])):
        role = turn.get("role")
        text = turn.get("text") or ""

        # attachments
        clean_atts = []
        for a in turn.get("attachments", []):
            u = normalize_url(a.get("url"))
            fname = a.get("filename") or a.get("name") or get_filename_from_url(u)
            mtype = a.get("mediaType") or a.get("type") or guess_mime("", filename=fname)
            clean_atts.append({"filename": fname, "mediaType": mtype, "url": u})

        # generatedImages
        clean_gen_imgs = []
        for g in turn.get("generatedImages", []):
            if isinstance(g, dict):
                u = normalize_url(g.get("url"))
                fname = g.get("filename") or g.get("name") or get_filename_from_url(u)
                mtype = g.get("mediaType") or g.get("type") or "image/jpeg"
            else:
                u = normalize_url(g)
                fname = get_filename_from_url(u)
                mtype = "image/jpeg"
            clean_gen_imgs.append({"filename": fname, "mediaType": mtype, "url": u})

        images = [g["url"] for g in clean_gen_imgs] + [
            a["url"] for a in clean_atts if a["mediaType"].startswith("image/")
        ]

        content = turn.get("content")
        if content and not text:
            if isinstance(content, list):
                text = next(
                    (
                        i.get("text", "")
                        for i in content
                        if i.get("type") == "text"
                    ),
                    "",
                )
                for ci in content:
                    if ci.get("type") == "image_url":
                        iu = normalize_url(ci.get("image_url", {}).get("url"))
                        if iu and iu not in images:
                            images.append(iu)
            else:
                text = str(content)

        simplified.append(
            {
                "role": role,
                "text": text,
                "images": images,
                "at": turn.get("at", ""),
                "attachments": clean_atts,
                "generatedImages": clean_gen_imgs,
            }
        )
    return jsonify(
        {
            "history": simplified,
            "conv_id": sess.get("active_local_conv_id"),
            "streaming": bool(sess.get("active_ws")),
        }
    )


@app.route("/api/conversations")
def api_conversations():
    sess = get_sess()
    if not sess:
        return jsonify({"conversations": []})
    convs = sess.get("conversations", [])
    result = []
    for i, c in enumerate(convs):
        valid_turns = [
            t
            for t in c.get("history", [])
            if t.get("text") or t.get("attachments") or t.get("generatedImages")
        ]
        if not valid_turns:
            continue
        count = len(valid_turns) // 2
        result.append(
            {
                "idx": i,
                "conv_id": c.get("conv_id") or str(uuid.uuid4()),
                "title": c["title"],
                "count": max(1, count),
            }
        )
    return jsonify({"conversations": result})


@app.route("/api/conversation/load", methods=["POST"])
def api_conversation_load():
    sess = get_sess()
    if not sess or not sess.get("client"):
        return jsonify({"error": "Oturum yok"}), 401

    data = request.json or {}
    conv_id = data.get("conv_id")
    idx = data.get("idx")

    convs = sess.get("conversations", [])

    if not conv_id and idx is not None:
        try:
            i = int(idx)
            if 0 <= i < len(convs):
                conv_id = convs[i].get("conv_id", str(i))
        except (ValueError, TypeError):
            pass

    if not conv_id:
        return jsonify({"error": "Konuşma bulunamadı"}), 404

    ok, cid, msg_count = _switch_to_conv(sess, conv_id)
    if ok:
        return jsonify({"success": True, "conv_id": cid, "message_count": msg_count})
    return jsonify({"error": "Konuşma bulunamadı"}), 404


@app.route("/api/conversation/delete", methods=["POST"])
def api_conversation_delete():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Oturum yok"}), 401

    data = request.json or {}
    conv_id = data.get("conv_id")
    if not conv_id:
        return jsonify({"error": "Konuşma bulunamadı"}), 404

    convs = sess.get("conversations", [])
    new_convs = [c for c in convs if c.get("conv_id") != conv_id]
    if len(new_convs) == len(convs):
        return jsonify({"error": "Konuşma bulunamadı"}), 404
    sess["conversations"] = new_convs

    if sess.get("active_local_conv_id") == conv_id:
        sess["history"] = []
        sess["active_local_conv_id"] = None
        if sess.get("client"):
            sess["client"].messages = []
            try:
                sess["client"].vote(str(uuid.uuid4()))
            except Exception:
                sess["client"].chat_id = str(uuid.uuid4())

    return jsonify({"success": True})


@app.route("/api/conversation/rename", methods=["POST"])
def api_conversation_rename():
    sess = get_sess()
    if not sess:
        return jsonify({"error": "Oturum yok"}), 401

    data = request.json or {}
    conv_id = data.get("conv_id")
    title = (data.get("title") or "").strip()
    if not conv_id or not title:
        return jsonify({"error": "Geçersiz istek"}), 400

    title = (title[:48] + "…") if len(title) > 48 else title

    for c in sess.get("conversations", []):
        if c.get("conv_id") == conv_id:
            c["title"] = title
            c["title_locked"] = True
            return jsonify({"success": True, "title": title})

    return jsonify({"error": "Konuşma bulunamadı"}), 404


if __name__ == "__main__":
    print("Use AI Web Interface başlatılıyor...")
    print("http://localhost:5000 adresine gidin")
    app.run(
        debug=True, host="0.0.0.0", port=5000, threaded=True, use_reloader=False
    )
