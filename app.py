#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import urllib.error
import urllib.request

PORT = 8765

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT, "config.json")
REQUIRED = ("base_url", "api_key", "model")

PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>对话</title>
<style>
* { box-sizing: border-box; }
html, body { height: 100%; margin: 0; }
body {
  font: 16px/1.55 -apple-system, "PingFang SC", "Noto Sans SC", sans-serif;
  background: #f4f1ea;
  color: #1d1a16;
}
#app {
  max-width: 760px;
  height: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  padding: 20px 16px 16px;
}
header h1 { font-size: 22px; font-weight: 600; margin: 0; }
#status { margin: 4px 0 0; color: #6e675e; font-size: 13px; min-height: 1.4em; word-break: break-word; }
#log { flex: 1; overflow: auto; padding: 16px 0; }
.row { display: flex; margin: 8px 0; }
.row.user { justify-content: flex-end; }
.bubble {
  max-width: 80%;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  background: #fff;
  border: 1px solid #e4ddd2;
}
.row.user .bubble { background: #1d1a16; color: #f4f1ea; border-color: #1d1a16; }
.pending { color: #8a8378; }
.empty { color: #8a8378; margin: 0; }
form { display: flex; gap: 8px; }
textarea {
  flex: 1;
  resize: none;
  padding: 10px;
  font: inherit;
  border: 1px solid #d9d1c5;
  background: #fff;
  color: inherit;
}
button {
  padding: 0 16px;
  font: inherit;
  background: #1d1a16;
  color: #f4f1ea;
  border: 0;
  cursor: pointer;
}
button:disabled { opacity: 0.45; cursor: default; }
</style>
</head>
<body>
<div id="app">
  <header>
    <h1>对话</h1>
    <p id="status"></p>
  </header>
  <main id="log"></main>
  <form id="form">
    <textarea id="input" rows="3" placeholder="输入消息，Enter 发送"></textarea>
    <button id="send" type="submit">发送</button>
  </form>
</div>
<script>
var logEl = document.getElementById("log");
var input = document.getElementById("input");
var statusEl = document.getElementById("status");
var sendBtn = document.getElementById("send");
var messages = [];
var sending = false;

function node(tag, cls, text) {
  var n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text;
  return n;
}

function render() {
  logEl.textContent = "";
  if (!messages.length) {
    logEl.appendChild(node("p", "empty", "写一条消息开始对话"));
    return;
  }
  for (var i = 0; i < messages.length; i++) {
    var m = messages[i];
    var row = node("div", "row " + m.role);
    row.appendChild(node("div", "bubble", m.content));
    logEl.appendChild(row);
  }
  logEl.scrollTop = logEl.scrollHeight;
}

function setStatus() {
  fetch("/api/status").then(function (r) { return r.json(); }).then(function (d) {
    if (d.ready) statusEl.textContent = d.model;
    else statusEl.textContent = "请编辑 config.json，填写 " + d.missing.join("、");
  }).catch(function () {
    statusEl.textContent = "状态获取失败";
  });
}

function sendMessage() {
  var text = input.value.trim();
  if (!text || sending) return;
  sending = true;
  sendBtn.disabled = true;
  messages.push({role: "user", content: text});
  input.value = "";
  render();
  var pending = node("div", "row assistant");
  pending.appendChild(node("div", "bubble pending", "……"));
  logEl.appendChild(pending);
  logEl.scrollTop = logEl.scrollHeight;
  fetch("/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({messages: messages})
  }).then(function (r) { return r.json(); }).then(function (d) {
    if (d.error) {
      messages.pop();
      input.value = text;
      statusEl.textContent = d.error;
      render();
      return;
    }
    messages.push({role: "assistant", content: d.reply});
    render();
  }).catch(function () {
    messages.pop();
    input.value = text;
    statusEl.textContent = "请求失败";
    render();
  }).then(function () {
    sending = false;
    sendBtn.disabled = false;
    input.focus();
  });
}

document.getElementById("form").addEventListener("submit", function (e) {
  e.preventDefault();
  sendMessage();
});
input.addEventListener("keydown", function (e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});
render();
setStatus();
</script>
</body>
</html>
"""


def read_config():
    if not os.path.exists(CONFIG_PATH):
        raise ValueError("缺少 config.json")
    with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("config.json 必须是对象")
    return data


def missing_fields(cfg):
    missing = []
    for key in REQUIRED:
        value = cfg.get(key)
        if not isinstance(value, str) or not value.strip():
            missing.append(key)
    return missing


def status():
    try:
        cfg = read_config()
    except (ValueError, json.JSONDecodeError) as exc:
        return {"ready": False, "missing": list(REQUIRED), "model": "", "error": str(exc)}
    missing = missing_fields(cfg)
    model = cfg.get("model") if isinstance(cfg.get("model"), str) else ""
    return {"ready": not missing, "missing": missing, "model": model.strip()}


def normalize_messages(raw):
    if not isinstance(raw, list) or not raw:
        raise ValueError("messages 不能为空")
    if len(raw) > 40:
        raise ValueError("历史消息过多")
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("消息格式不正确")
        role = item.get("role")
        content = item.get("content")
        if role not in ("system", "user", "assistant"):
            raise ValueError("不支持的 role")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("消息内容为空")
        if len(content) > 16000:
            raise ValueError("单条消息过长")
        cleaned.append({"role": role, "content": content})
    return cleaned


def call_model(messages):
    cfg = read_config()
    missing = missing_fields(cfg)
    if missing:
        raise ValueError("请在 config.json 填写 " + "、".join(missing))

    url = cfg["base_url"].strip().rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": cfg["model"].strip(),
        "messages": messages,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + cfg["api_key"].strip())

    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:800]
        raise RuntimeError("模型接口返回 %s：%s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        raise RuntimeError("无法连接模型接口：%s" % exc.reason)

    body = json.loads(resp.read().decode("utf-8"))
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("模型接口返回了无法识别的内容")
    if content is None:
        raise RuntimeError("模型没有返回文本")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return content


class Handler(BaseHTTPRequestHandler):
    def path_only(self):
        return self.path.split("?", 1)[0]

    def send_bytes(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_bytes(code, raw, "application/json; charset=utf-8")

    def do_GET(self):
        path = self.path_only()
        if path == "/":
            self.send_bytes(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self.send_json(200, status())
            return
        self.send_error(404)

    def do_POST(self):
        if self.path_only() != "/api/chat":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "请求不合法"})
            return
        if length < 0 or length > 1000000:
            self.send_json(400, {"error": "请求过大"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            messages = normalize_messages(data.get("messages"))
            reply = call_model(messages)
        except Exception as exc:
            self.send_json(400, {"error": str(exc)})
            return
        self.send_json(200, {"reply": reply})


class ThreadingServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True


def main():
    server = ThreadingServer(("0.0.0.0", PORT), Handler)
    sys.stderr.write("listening on 0.0.0.0:%s\n" % PORT)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
