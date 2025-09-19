# -*- coding: utf-8 -*-
"""
NAO Bridge (Python 2.7)
- .env에서 필수 환경변수만 읽어들임 (기본값 없음, 누락시 즉시 에러)
- HTTP POST /say  {"text":"..."}  -> NAO ALTextToSpeech.say("...")

필수 환경변수(.env):
  NAO_SDK_PATH       = D:\NAO_project_2025\pynaoqi-python2.7-...
  NAO_IP             = 192.168.x.y
  NAO_PORT           = 9559
  BRIDGE_BIND_IP     = 0.0.0.0
  BRIDGE_BIND_PORT   = 8088
"""

import os
import sys
import json
from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler

# ------------------------------------------------------------
# .env 로더 (python-dotenv 없이 동작; 파일 인코딩은 UTF-8 가정)
# ------------------------------------------------------------
def load_dotenv_strict():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dotenv_path = os.path.join(base_dir, ".env")
    if not os.path.isfile(dotenv_path):
        raise EnvironmentError(".env file not found at: %s" % dotenv_path)

    try:
        f = open(dotenv_path, "rb")
        lines = f.readlines()
        f.close()
    except Exception as e:
        raise EnvironmentError("Failed to read .env: %r" % e)

    for raw in lines:
        try:
            line = raw.decode("utf-8").strip()
        except Exception:
            line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if k and (k not in os.environ):
            os.environ[k] = v

load_dotenv_strict()

# ------------------------------------------------------------
# 필수 환경변수 검증 (기본값 없음)
# ------------------------------------------------------------
REQUIRED_KEYS = [
    "NAO_SDK_PATH",
    "NAO_IP",
    "NAO_PORT",
    "BRIDGE_BIND_IP",
    "BRIDGE_BIND_PORT",
]

missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
if missing:
    raise EnvironmentError("Missing required env keys in .env: %s" % ", ".join(missing))

# 값 정리 (strip + 타입 확정)
NAO_SDK_PATH     = os.environ["NAO_SDK_PATH"].strip()
NAO_IP           = str(os.environ["NAO_IP"].strip())
NAO_PORT         = int(str(os.environ["NAO_PORT"]).strip())
BRIDGE_BIND_IP   = str(os.environ["BRIDGE_BIND_IP"].strip())
BRIDGE_BIND_PORT = int(str(os.environ["BRIDGE_BIND_PORT"]).strip())

# ------------------------------------------------------------
# NAO SDK 경로 등록 (루트 + lib 모두)
# ------------------------------------------------------------
for p in (NAO_SDK_PATH, os.path.join(NAO_SDK_PATH, "lib")):
    if not os.path.isdir(p):
        raise EnvironmentError("Invalid SDK path: %s" % p)
    if p not in sys.path:
        sys.path.append(p)

try:
    from naoqi import ALProxy
except Exception as e:
    raise ImportError("Failed to import naoqi. Check NAO_SDK_PATH/lib: %r" % e)

# ------------------------------------------------------------
# ALTextToSpeech 프록시 준비
# ------------------------------------------------------------
SERVICE = str("ALTextToSpeech")
IP      = str(NAO_IP)
PORT    = int(NAO_PORT)

# 디버그 출력 (인코딩 이슈 방지 위해 ASCII만)
sys.stdout.write("[DEBUG] SERVICE=%r IP=%r PORT=%r\n" % (SERVICE, IP, PORT))

try:
    # 4번째 인자 False로 오버로드를 명확히 선택 (char*, char*, int, bool)
    tts = ALProxy(SERVICE, IP, PORT, False)
    sys.stdout.write("[INFO] ALTextToSpeech proxy ready (%s:%d)\n" % (IP, PORT))
except Exception as e:
    raise EnvironmentError("Failed to connect ALTextToSpeech: %r" % e)

# ------------------------------------------------------------
# HTTP 핸들러
# ------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _read_json(self):
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length > 0 else "{}"
        try:
            data = json.loads(raw or "{}")
            return data
        except Exception as e:
            raise ValueError("Invalid JSON body: %r" % e)

    def _send_json(self, code, obj):
        try:
            body = json.dumps(obj)
        except Exception:
            body = '{"ok":false,"msg":"encode error"}'
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            if self.path == "/say":
                data = self._read_json()
                # text를 유니코드로 보정
                text = data.get("text")
                if text is None:
                    self._send_json(400, {"ok": False, "msg": "text is required"})
                    return

                # Python 2.7: str(바이트) 또는 unicode가 올 수 있음
                if isinstance(text, unicode):
                    text_u = text.strip()
                else:
                    # 바이트로 왔을 때 우선 UTF-8 시도, 실패 시 CP949 fallback
                    try:
                        text_u = text.decode('utf-8').strip()
                    except Exception:
                        text_u = text.decode('cp949', 'ignore').strip()

                if not text_u:
                    self._send_json(400, {"ok": False, "msg": "text is empty"})
                    return

                # NAOqi는 UTF-8 바이트 문자열을 기대하는 경우가 많음
                tts.say(text_u.encode('utf-8'))

                self._send_json(200, {"ok": True})
                return

            self._send_json(404, {"ok": False, "msg": "not found"})

        except ValueError as ve:
            self._send_json(400, {"ok": False, "msg": str(ve)})
        except Exception as e:
            # 에러 원인을 콘솔에 찍어두면 디버깅 편함
            sys.stderr.write("[ERR ] do_POST /say: %r\n" % e)
            self._send_json(500, {"ok": False, "msg": "server error"})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "service": "nao_bridge"})
        else:
            self._send_json(404, {"ok": False, "msg": "not found"})

# ------------------------------------------------------------
# 서버 시작
# ------------------------------------------------------------
if __name__ == "__main__":
    server = HTTPServer((BRIDGE_BIND_IP, BRIDGE_BIND_PORT), Handler)
    sys.stdout.write("[INFO] NAO bridge listening on http://%s:%d\n" %
                     (BRIDGE_BIND_IP, BRIDGE_BIND_PORT))
    server.serve_forever()
