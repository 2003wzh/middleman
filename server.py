from __future__ import annotations

import json
import os
import hashlib
import hmac
import re
import secrets
import smtplib
import time
from email.message import EmailMessage
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from typing import Any
from urllib.parse import quote, urlparse

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
KEYS_FILE = DATA_DIR / "api_keys.json"
ORDERS_FILE = DATA_DIR / "orders.json"
USERS_FILE = DATA_DIR / "users.json"
EMAIL_CODES_FILE = DATA_DIR / "email_codes.json"
SESSIONS_FILE = DATA_DIR / "sessions.json"
ADMIN_TOKENS_FILE = ROOT / "secrets" / "admin_tokens.json"

SESSION_COOKIE = "middleman_session"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60
CODE_TTL_SECONDS = 10 * 60
PROTECTED_PAGES = {"/", "/index.html", "/pay.html", "/apikey.html"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

PLANS = {
    "codex-config": {
        "id": "codex-config",
        "price": 20,
        "title": "Codex 自动化部署",
        "description": "已有可用网络环境，直接完成部署配置。",
        "requiresNetworkTool": False,
    },
    "codex-network": {
        "id": "codex-network",
        "price": 30,
        "title": "Codex 自动化部署 + 网络环境准备指引",
        "description": "先完成网络环境准备，再进入部署配置。",
        "requiresNetworkTool": True,
    },
    "5": {
        "id": "5",
        "price": 5,
        "title": "API key 基础包",
        "description": "适合轻量体验和临时使用。",
        "requiresNetworkTool": False,
    },
    "10": {
        "id": "10",
        "price": 10,
        "title": "API key 标准包",
        "description": "适合日常配置和持续使用。",
        "requiresNetworkTool": False,
    },
    "20": {
        "id": "20",
        "price": 20,
        "title": "API key 进阶包",
        "description": "适合更高频的部署和调试使用。",
        "requiresNetworkTool": False,
    },
}

LEGACY_KEY_PLANS = {"5", "10", "20"}

PAYMENT_METHODS = {
    "alipay": {
        "id": "alipay",
        "title": "支付宝",
        "account": os.environ.get("PAY_ALIPAY_ACCOUNT", "扫码支付，付款备注填写订单号"),
        "qr": os.environ.get("PAY_ALIPAY_QR", "/assets/alipay-qr.svg"),
        "note": "请使用支付宝扫码付款，付款备注填写订单号。",
        "enabled": True,
    },
    "wechat": {
        "id": "wechat",
        "title": "微信支付（暂未开启）",
        "account": "暂未开启",
        "qr": "",
        "note": "微信支付暂未开启，请使用支付宝付款。",
        "enabled": False,
    },
}

ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me-admin-token")
LOCK = Lock()

if not os.environ.get("PAY_ALIPAY_QR") and (ROOT / "assets" / "alipay-qr.png").exists():
    PAYMENT_METHODS["alipay"]["qr"] = "/assets/alipay-qr.png"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_data_files() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if not KEYS_FILE.exists():
        write_json(KEYS_FILE, {"plans": {}})
    if not ORDERS_FILE.exists():
        write_json(ORDERS_FILE, [])
    if not USERS_FILE.exists():
        write_json(USERS_FILE, {"users": []})
    if not EMAIL_CODES_FILE.exists():
        write_json(EMAIL_CODES_FILE, {"codes": []})
    if not SESSIONS_FILE.exists():
        write_json(SESSIONS_FILE, {"sessions": []})


def read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    with path.open("r", encoding="utf-8-sig") as file:
        return json.load(file)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)
        file.write("\n")
    tmp.replace(path)


def unix_now() -> int:
    return int(time.time())


def normalize_email(email: str) -> str:
    value = email.strip().lower()
    if not EMAIL_RE.match(value):
        raise ValueError("请填写有效邮箱。")
    return value


def hash_password(password: str) -> str:
    if len(password) < 6:
        raise ValueError("密码至少 6 位。")
    salt = secrets.token_hex(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(stored: str, password: str) -> bool:
    try:
        algorithm, iterations_text, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            int(iterations_text),
        ).hex()
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def users_data() -> dict[str, Any]:
    return read_json(USERS_FILE, {"users": []})


def find_user_by_email(email: str) -> dict[str, Any] | None:
    data = users_data()
    return next((user for user in data.get("users", []) if user.get("email") == email), None)


def find_user_by_id(user_id: str) -> dict[str, Any] | None:
    data = users_data()
    return next((user for user in data.get("users", []) if user.get("id") == user_id), None)


def send_verification_email(email: str, code: str) -> bool:
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        print(f"[dev email code] {email}: {code}")
        return False

    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "")
    sender = os.environ.get("SMTP_FROM", username or "no-reply@localhost")

    message = EmailMessage()
    message["Subject"] = "Middleman 邮箱验证码"
    message["From"] = sender
    message["To"] = email
    message.set_content(f"你的验证码是：{code}\n\n验证码 10 分钟内有效。")

    with smtplib.SMTP(host, port, timeout=12) as smtp:
        smtp.starttls()
        if username:
            smtp.login(username, password)
        smtp.send_message(message)
    return True


def create_email_code(email: str) -> dict[str, Any]:
    email = normalize_email(email)
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = unix_now()
    data = read_json(EMAIL_CODES_FILE, {"codes": []})
    codes = [
        item for item in data.get("codes", [])
        if item.get("email") != email and int(item.get("expiresAt", 0)) > now
    ]
    codes.append({
        "email": email,
        "code": code,
        "createdAt": now,
        "expiresAt": now + CODE_TTL_SECONDS,
    })
    write_json(EMAIL_CODES_FILE, {"codes": codes})
    sent = send_verification_email(email, code)
    return {"sent": sent, "devCode": "" if sent else code}


def consume_email_code(email: str, code: str) -> None:
    email = normalize_email(email)
    value = code.strip()
    now = unix_now()
    data = read_json(EMAIL_CODES_FILE, {"codes": []})
    remaining = []
    matched = False

    for item in data.get("codes", []):
        expired = int(item.get("expiresAt", 0)) <= now
        same_email = item.get("email") == email
        same_code = hmac.compare_digest(str(item.get("code", "")), value)
        if same_email and same_code and not expired:
            matched = True
            continue
        if not expired:
            remaining.append(item)

    write_json(EMAIL_CODES_FILE, {"codes": remaining})
    if not matched:
        raise ValueError("验证码错误或已过期。")


def register_user(email: str, password: str, invite_code: str, code: str) -> dict[str, Any]:
    email = normalize_email(email)
    if find_user_by_email(email):
        raise ValueError("这个邮箱已经注册，请直接登录。")
    consume_email_code(email, code)

    user = {
        "id": "USR-" + secrets.token_hex(8).upper(),
        "email": email,
        "passwordHash": hash_password(password),
        "inviteCode": invite_code.strip()[:80],
        "createdAt": utc_now(),
        "verifiedAt": utc_now(),
    }
    data = users_data()
    data.setdefault("users", []).append(user)
    write_json(USERS_FILE, data)
    return user


def create_session(user: dict[str, Any]) -> str:
    session_id = secrets.token_urlsafe(32)
    now = unix_now()
    data = read_json(SESSIONS_FILE, {"sessions": []})
    sessions = [
        item for item in data.get("sessions", [])
        if int(item.get("expiresAt", 0)) > now
    ]
    sessions.append({
        "id": session_id,
        "userId": user["id"],
        "email": user["email"],
        "createdAt": now,
        "expiresAt": now + SESSION_TTL_SECONDS,
    })
    write_json(SESSIONS_FILE, {"sessions": sessions})
    return session_id


def find_user_by_session(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    now = unix_now()
    data = read_json(SESSIONS_FILE, {"sessions": []})
    sessions = []
    found = None
    changed = False

    for item in data.get("sessions", []):
        if int(item.get("expiresAt", 0)) <= now:
            changed = True
            continue
        sessions.append(item)
        if item.get("id") == session_id:
            found = item

    if changed:
        write_json(SESSIONS_FILE, {"sessions": sessions})
    if not found:
        return None
    return find_user_by_id(str(found.get("userId", "")))


def delete_session(session_id: str) -> None:
    data = read_json(SESSIONS_FILE, {"sessions": []})
    write_json(SESSIONS_FILE, {
        "sessions": [item for item in data.get("sessions", []) if item.get("id") != session_id]
    })


def login_user(email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    user = find_user_by_email(email)
    if not user or not verify_password(str(user.get("passwordHash", "")), password):
        raise ValueError("邮箱或密码错误。")
    return user


def public_user(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user.get("id", ""),
        "email": user.get("email", ""),
        "inviteCode": user.get("inviteCode", ""),
    }


def admin_tokens() -> set[str]:
    tokens = {ADMIN_TOKEN}
    configured = os.environ.get("ADMIN_TOKENS", "")
    tokens.update(token.strip() for token in configured.split(",") if token.strip())

    data = read_json(ADMIN_TOKENS_FILE, {"tokens": []})
    for item in data.get("tokens", []):
        if isinstance(item, str):
            tokens.add(item)
        elif isinstance(item, dict) and item.get("token"):
            tokens.add(str(item["token"]))

    return {token for token in tokens if token}


def public_plans() -> list[dict[str, Any]]:
    return [{**plan, "available": 1} for plan in PLANS.values()]


def public_payment_methods() -> list[dict[str, Any]]:
    return list(PAYMENT_METHODS.values())


def create_order(plan_id: str, contact: str, payment_method: str, user: dict[str, Any]) -> dict[str, Any]:
    if plan_id not in PLANS:
        raise ValueError("服务套餐不存在。")
    if payment_method not in PAYMENT_METHODS:
        raise ValueError("请选择支付方式。")

    payment = PAYMENT_METHODS[payment_method]
    if not payment.get("enabled"):
        raise ValueError(f"{payment['title']}暂不可用，请使用支付宝付款。")
    if len(contact) > 120:
        raise ValueError("联系方式最多 120 个字符。")
    if not contact:
        contact = "未填写"

    plan = PLANS[plan_id]
    lookup_code = secrets.token_hex(3).upper()
    order = {
        "id": f"CDX-{datetime.now().strftime('%Y%m%d')}-{secrets.token_hex(3).upper()}",
        "lookupCode": lookup_code,
        "userId": user.get("id", ""),
        "userEmail": user.get("email", ""),
        "planId": plan_id,
        "planTitle": plan["title"],
        "requiresNetworkTool": plan["requiresNetworkTool"],
        "price": plan["price"],
        "contact": contact,
        "paymentMethod": payment_method,
        "paymentTitle": payment["title"],
        "paymentAccount": payment["account"],
        "paymentQr": payment.get("qr", ""),
        "paymentNote": payment["note"],
        "status": "pending_payment",
        "apiKey": "",
        "createdAt": utc_now(),
        "fulfilledAt": "",
    }

    with LOCK:
        orders = read_json(ORDERS_FILE, [])
        orders.append(order)
        write_json(ORDERS_FILE, orders)

    return order


def find_order(order_id: str, lookup_code: str) -> dict[str, Any]:
    orders = read_json(ORDERS_FILE, [])
    order = next((item for item in orders if item["id"] == order_id and item.get("lookupCode") == lookup_code), None)
    if not order:
        raise ValueError("订单不存在，或查询码错误。")
    return order


def fulfill_order(order_id: str) -> dict[str, Any]:
    with LOCK:
        orders = read_json(ORDERS_FILE, [])
        keys = read_json(KEYS_FILE, {"plans": {}})

        order = next((item for item in orders if item["id"] == order_id), None)
        if not order:
            raise ValueError("订单不存在。")
        if order["status"] == "fulfilled":
            return order

        plan_id = order["planId"]
        if plan_id in PLANS and plan_id not in LEGACY_KEY_PLANS:
            order["status"] = "fulfilled"
            order["fulfilledAt"] = utc_now()
            order["apiKey"] = "Codex 部署服务已确认，请回到部署配置页查看交付指引。"
            write_json(ORDERS_FILE, orders)
            return order

        if plan_id not in LEGACY_KEY_PLANS:
            raise ValueError("这个订单的套餐类型无法自动发放。")

        pool = keys.get("plans", {}).get(plan_id, [])
        key_item = next((item for item in pool if not item.get("used")), None)
        if not key_item:
            raise ValueError("这个套餐没有可用 API key 了。")

        key_item["used"] = True
        key_item["orderId"] = order_id
        key_item["issuedAt"] = utc_now()

        order["status"] = "fulfilled"
        order["apiKey"] = key_item["key"]
        order["fulfilledAt"] = key_item["issuedAt"]

        write_json(KEYS_FILE, keys)
        write_json(ORDERS_FILE, orders)
        return order


def delete_order(order_id: str) -> dict[str, Any]:
    with LOCK:
        orders = read_json(ORDERS_FILE, [])
        order = next((item for item in orders if item["id"] == order_id), None)
        if not order:
            raise ValueError("订单不存在。")

        write_json(ORDERS_FILE, [item for item in orders if item["id"] != order_id])
        return order


def order_public(order: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "lookupCode",
        "userEmail",
        "planId",
        "planTitle",
        "requiresNetworkTool",
        "price",
        "contact",
        "paymentMethod",
        "paymentTitle",
        "paymentAccount",
        "paymentQr",
        "paymentNote",
        "status",
        "createdAt",
        "fulfilledAt",
    )
    value = {key: order.get(key, "") for key in fields}
    if order.get("status") == "fulfilled":
        value["apiKey"] = order.get("apiKey", "")
    return value


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        clean_path = urlparse(self.path).path
        if clean_path in PROTECTED_PAGES and not self.current_user():
            target = quote(self.path, safe="")
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", f"/login.html?next={target}")
            self.end_headers()
            return

        if clean_path == "/login.html" and self.current_user():
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/index.html")
            self.end_headers()
            return

        if clean_path == "/api/auth/me":
            user = self.current_user()
            self.send_json({"user": public_user(user) if user else None})
            return

        if self.path == "/api/plans":
            if not self.require_user():
                return
            self.send_json({"plans": public_plans(), "paymentMethods": public_payment_methods()})
            return

        if self.path.startswith("/api/orders/"):
            user = self.current_user()
            if not user:
                self.send_json({"error": "请先登录。"}, HTTPStatus.UNAUTHORIZED)
                return
            parts = self.path.split("/")
            order_id = parts[-1]
            lookup_code = self.headers.get("X-Order-Code", "").strip()
            try:
                order = find_order(order_id, lookup_code)
                if order.get("userId") and order.get("userId") != user.get("id"):
                    self.send_json({"error": "无权查看这个订单。"}, HTTPStatus.FORBIDDEN)
                    return
                self.send_json({"order": order_public(order)})
            except ValueError as exc:
                self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            return

        if self.path == "/api/admin/orders":
            if not self.require_admin():
                return
            orders = read_json(ORDERS_FILE, [])
            self.send_json({"orders": orders})
            return

        super().do_GET()

    def do_POST(self) -> None:
        try:
            if self.path == "/api/auth/send-code":
                payload = self.read_body()
                result = create_email_code(str(payload.get("email", "")))
                self.send_json({
                    "message": "验证码已发送，请查看邮箱。",
                    "devCode": result["devCode"],
                })
                return

            if self.path == "/api/auth/register":
                payload = self.read_body()
                user = register_user(
                    str(payload.get("email", "")),
                    str(payload.get("password", "")),
                    str(payload.get("inviteCode", "")),
                    str(payload.get("code", "")),
                )
                session_id = create_session(user)
                self.send_json_with_cookie({"user": public_user(user)}, session_id, HTTPStatus.CREATED)
                return

            if self.path == "/api/auth/login":
                payload = self.read_body()
                user = login_user(str(payload.get("email", "")), str(payload.get("password", "")))
                session_id = create_session(user)
                self.send_json_with_cookie({"user": public_user(user)}, session_id)
                return

            if self.path == "/api/auth/logout":
                delete_session(self.session_id())
                self.send_json({"ok": True}, cookie=f"{SESSION_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax")
                return

            if self.path == "/api/orders":
                user = self.current_user()
                if not user:
                    self.send_json({"error": "请先登录。"}, HTTPStatus.UNAUTHORIZED)
                    return
                payload = self.read_body()
                order = create_order(
                    str(payload.get("planId", "")),
                    str(payload.get("contact", "")).strip(),
                    str(payload.get("paymentMethod", "")),
                    user,
                )
                self.send_json(
                    {
                        "order": order_public(order),
                        "message": f"订单已创建。请使用支付宝付款 {order['price']} 元，备注订单号。",
                    },
                    HTTPStatus.CREATED,
                )
                return

            if self.path == "/api/admin/fulfill":
                if not self.require_admin():
                    return
                payload = self.read_body()
                order = fulfill_order(str(payload.get("orderId", "")).strip())
                self.send_json({"order": order})
                return

            if self.path == "/api/admin/delete":
                if not self.require_admin():
                    return
                payload = self.read_body()
                order = delete_order(str(payload.get("orderId", "")).strip())
                self.send_json({"deleted": True, "order": order_public(order)})
                return

            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except json.JSONDecodeError:
            self.send_json({"error": "JSON 格式错误。"}, HTTPStatus.BAD_REQUEST)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def require_admin(self) -> bool:
        token = self.headers.get("X-Admin-Token", "")
        if token not in admin_tokens():
            self.send_json({"error": "管理员 token 错误。"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def session_id(self) -> str:
        raw = self.headers.get("Cookie", "")
        cookie = SimpleCookie()
        cookie.load(raw)
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else ""

    def current_user(self) -> dict[str, Any] | None:
        return find_user_by_session(self.session_id())

    def require_user(self) -> bool:
        if not self.current_user():
            self.send_json({"error": "请先登录。"}, HTTPStatus.UNAUTHORIZED)
            return False
        return True

    def send_json_with_cookie(self, value: Any, session_id: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        cookie = (
            f"{SESSION_COOKIE}={session_id}; Path=/; Max-Age={SESSION_TTL_SECONDS}; "
            "HttpOnly; SameSite=Lax"
        )
        self.send_json(value, status, cookie=cookie)

    def send_json(self, value: Any, status: HTTPStatus = HTTPStatus.OK, cookie: str = "") -> None:
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ensure_data_files()
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Middleman service portal: http://localhost:{port}")
    print(f"Payment page: http://localhost:{port}/pay.html")
    print(f"Admin page: http://localhost:{port}/admin.html")
    print("Set ADMIN_TOKEN before real use. Current token:", ADMIN_TOKEN)
    server.serve_forever()
