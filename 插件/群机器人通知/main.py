"""群机器人通知插件：把知识库的通知发到飞书 / 钉钉 / 企业微信 / Slack 群。

  main.py notify <标题>     知识库调用：标准输入是正文
  main.py <一句话>          终端 / AI（kb_plugin_call）调用：发一条测试消息
机器人地址和密钥由知识库从基础信息（KB_PLUGIN_BASE）传进来，这里不存。
"""
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request


def conf():
    c = json.loads(os.environ.get('KB_PLUGIN_CONFIG') or '{}')
    b = (json.loads(os.environ.get('KB_PLUGIN_BASE') or '{}')).get('机器人') or {}
    url = b.get('Webhook') or b.get('webhook') or b.get('地址') or ''
    if not url:
        raise SystemExit('没配好：在插件配置里选基础信息条目，条目里要有字段「Webhook」')
    return c.get('平台') or '飞书', url, b.get('密钥') or b.get('Secret') or '', (c.get('网页地址') or '').strip()


def body(platform, text, secret):
    if platform == '飞书':
        d = {'msg_type': 'text', 'content': {'text': text}}
        if secret:
            ts = str(int(time.time()))
            d.update(timestamp=ts, sign=base64.b64encode(hmac.new(f'{ts}\n{secret}'.encode(), b'', hashlib.sha256).digest()).decode())
        return d
    if platform in ('钉钉', '企业微信'):
        return {'msgtype': 'text', 'text': {'content': text}}
    return {'text': text}


def send(title, text):
    platform, url, secret, web = conf()
    msg = f'{title}\n{text}'.strip() + (f'\n{web}' if web else '')
    if platform == '钉钉' and secret:
        ts = str(int(time.time() * 1000))
        sign = base64.b64encode(hmac.new(secret.encode(), f'{ts}\n{secret}'.encode(), hashlib.sha256).digest()).decode()
        url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'timestamp': ts, 'sign': sign})
    req = urllib.request.Request(url, json.dumps(body(platform, msg[:3500], secret), ensure_ascii=False).encode(),
                                 {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=15) as r:
        res = r.read().decode('utf-8', 'replace')
    try:
        j = json.loads(res)
    except ValueError:
        j = {}
    code = j.get('code', j.get('errcode', 0)) if isinstance(j, dict) else 0
    if code not in (0, None):
        raise SystemExit(f'{platform} 返回错误：{res[:300]}')
    return f'已发到{platform}群'


def main():
    a = sys.argv[1:]
    if a and a[0] == 'notify':
        print(send(a[1] if len(a) > 1 else '知识库', sys.stdin.read()))
    else:
        print(send('知识库 · 测试', ' '.join(a) or '测试一下：群机器人配好了'))


if __name__ == '__main__':
    main()
