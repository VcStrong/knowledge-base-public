# From 大大王.DT
"""Firebase Crashlytics 适配器（经 BigQuery 导出）。"""
import base64
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime
from urllib.parse import urlencode
from .base import SourceError, http, local_time
from .crash import java_stack, native_stack, anr_stack, CrashSource


class CrashlyticsSource(CrashSource):
    """Firebase Crashlytics 没有可用的公开接口（v1alpha 不支持服务账号），只能走「导出到 BigQuery」：
    Firebase 控制台 → 项目设置 → 集成 → BigQuery 打开 Crashlytics 导出；服务账号要 BigQuery Job User + Data Viewer 角色。"""
    adapter = 'Firebase Crashlytics'
    guess = ('firebase', 'crashlytics', 'bigquery')
    fields = '服务账号〔机密，整段 JSON 密钥〕'
    options = [('包名', '应用包名，如 com.acme.app（必填）', ''),
               ('项目', 'BigQuery 导出所在的 GCP 项目 ID（空 = 服务账号里的 project_id）', ''),
               ('计费项目', '跑查询记账的项目（空 = 同上）', ''),
               ('数据集', '', 'firebase_crashlytics'),
               ('表', '空 = 包名的点换成下划线 + _ANDROID', ''),
               ('实时表', '填「是」用 _REALTIME 表（需要开了流式导出）', ''),
               ('位置', '数据集所在位置，如 US / asia-east1（空 = 自动）', ''),
               ('天数', '只看最近几天', '7'),
               ('包含非致命', '填「是」也同步 NON_FATAL', ''),
               ('上限', '最多同步多少个问题（按次数排）', '200')]

    def _sa(self):
        f = next((n for n in ('服务账号', '服务账号JSON', 'JSON', '密钥', 'service_account') if self.cred.has(n)), '')
        if not f:
            raise SourceError(f'{self.cred.entry.get("编号")} 缺少「服务账号」字段（整段 JSON 密钥）')
        try:
            return json.loads(self.cred.secret(f))
        except ValueError:
            raise SourceError('「服务账号」不是合法的 JSON：粘贴从 GCP 下载的整段密钥文件内容')

    def _token(self):
        if getattr(self, '_tok', None) and self._tok[1] > time.time() + 60:
            return self._tok[0]
        sa = self._sa()
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        now_ = int(time.time())
        head = b64(json.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode())
        claim = b64(json.dumps({'iss': sa['client_email'], 'scope': 'https://www.googleapis.com/auth/bigquery.readonly',
                                'aud': 'https://oauth2.googleapis.com/token', 'iat': now_, 'exp': now_ + 3600}).encode())
        signing = f'{head}.{claim}'.encode()
        fd, kp = tempfile.mkstemp(suffix='.pem')
        try:
            os.chmod(kp, 0o600)
            with os.fdopen(fd, 'w') as fh:
                fh.write(sa['private_key'])
            r = subprocess.run(['openssl', 'dgst', '-sha256', '-sign', kp], input=signing, capture_output=True, timeout=20)
        finally:
            os.unlink(kp)
        if r.returncode:
            raise SourceError(f'服务账号签名失败（openssl）：{r.stderr[:200]}')
        jwt = f'{head}.{claim}.{b64(r.stdout)}'
        _, _, t = http('POST', 'https://oauth2.googleapis.com/token',
                       {'Content-Type': 'application/x-www-form-urlencoded'},
                       {'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer', 'assertion': jwt}, what='Google 登录')
        self._tok = (t['access_token'], time.time() + int(t.get('expires_in') or 3600))
        return self._tok[0]

    def _table(self):
        pkg = self.o('包名')
        if not pkg and not self.o('表'):
            raise SourceError('Firebase Crashlytics 要填「包名」选项')
        proj = self.o('项目') or self._sa().get('project_id')
        t = self.o('表') or re.sub(r'\.', '_', pkg) + '_ANDROID'
        if self.o('实时表') in ('是', 'true', '1', 'yes') and not t.endswith('_REALTIME'):
            t += '_REALTIME'
        return f'`{proj}.{self.o("数据集")}.{t}`', proj

    def _query(self, sql):
        bill = self.o('计费项目') or self.o('项目') or self._sa().get('project_id')
        body = {'query': sql, 'useLegacySql': False, 'maxResults': 1000, 'timeoutMs': 60000}
        if self.o('位置'):
            body['location'] = self.o('位置')
        hdr = {'Authorization': 'Bearer ' + self._token()}
        _, _, r = http('POST', f'https://bigquery.googleapis.com/bigquery/v2/projects/{bill}/queries', hdr, body, timeout=90, what='BigQuery')
        job = r.get('jobReference') or {}
        rows, fields = list(r.get('rows') or []), [f['name'] for f in (r.get('schema') or {}).get('fields') or []]
        tok, waited = r.get('pageToken'), 0
        while not r.get('jobComplete', True) or tok:
            if not r.get('jobComplete', True):
                waited += 1
                if waited > 20:
                    raise SourceError('BigQuery 查询超时')
                time.sleep(2)
            q = {'timeoutMs': 30000, 'maxResults': 1000, 'pageToken': tok, 'location': job.get('location')}
            _, _, r = http('GET', f'https://bigquery.googleapis.com/bigquery/v2/projects/{job.get("projectId") or bill}/queries/{job["jobId"]}?'
                           + urlencode({k: v for k, v in q.items() if v}), hdr, what='BigQuery')
            fields = fields or [f['name'] for f in (r.get('schema') or {}).get('fields') or []]
            rows += r.get('rows') or []
            tok = r.get('pageToken')
        return [dict(zip(fields, [c.get('v') for c in row.get('f') or []])) for row in rows]

    def account(self):
        return ''

    def _sql(self, limit):
        t, _ = self._table()
        days = int(self.o('天数') or 7)
        types = "('FATAL','ANR','NON_FATAL')" if self.o('包含非致命') in ('是', 'true', '1', 'yes') else "('FATAL','ANR')"
        return f"""SELECT issue_id, ANY_VALUE(issue_title) AS title, ANY_VALUE(issue_subtitle) AS subtitle, ANY_VALUE(error_type) AS error_type,
  COUNT(*) AS events, COUNT(DISTINCT installation_uuid) AS users,
  FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', MIN(event_timestamp)) AS first_seen, FORMAT_TIMESTAMP('%Y-%m-%dT%H:%M:%SZ', MAX(event_timestamp)) AS last_seen,
  ARRAY_AGG(application.display_version ORDER BY event_timestamp DESC LIMIT 1)[OFFSET(0)] AS version,
  ARRAY_AGG(bundle_identifier ORDER BY event_timestamp DESC LIMIT 1)[OFFSET(0)] AS bundle,
  TO_JSON_STRING(ARRAY_AGG(STRUCT(exceptions, threads, blame_frame) ORDER BY event_timestamp DESC LIMIT 1)[OFFSET(0)]) AS sample
FROM {t}
WHERE event_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY) AND error_type IN {types}
GROUP BY issue_id ORDER BY events DESC LIMIT {int(limit)}"""

    @staticmethod
    def _frames(fs):
        return [(f.get('symbol') or '', f.get('file') or '', f.get('line')) for f in fs or []]

    def _stack(self, kind, sample):
        try:
            s = json.loads(sample or '{}')
        except ValueError:
            return '', 'Java崩溃'
        excs, ths = s.get('exceptions') or [], s.get('threads') or []
        if kind == 'ANR':
            main = next((t for t in ths if t.get('thread_name') == 'main'), None) or next((t for t in ths if t.get('crashed')), None) or {}
            return anr_stack(self._frames(main.get('frames'))), 'ANR'
        crashed = next((t for t in ths if t.get('crashed') and t.get('signal_name')), None)
        if not excs and crashed:
            return native_stack(f'{crashed.get("signal_code") or ""} ({crashed["signal_name"]})'.strip(),
                                [(f.get('address'), f.get('library'), f.get('symbol')) for f in crashed.get('frames') or []]), 'Native崩溃'
        top = [e for e in excs if not e.get('nested')] + [e for e in excs if e.get('nested')]
        return java_stack([(e.get('type'), e.get('exception_message'), self._frames(e.get('frames'))) for e in top]), 'Java崩溃'

    def test(self):
        t, proj = self._table()
        rows = self._query(self._sql(5))
        return f'✓ BigQuery 可用：{t}\n例：' + ('；'.join(f'{r["issue_id"][:8]} {r.get("title") or ""}（{r.get("error_type")}，{r.get("events")} 次）' for r in rows) or '最近没有崩溃')

    def sync(self, state, ctx):
        rows = self._query(self._sql(int(self.o('上限') or 200)))
        _, proj = self._table()
        for r in rows:
            kind = {'ANR': 'ANR'}.get(r.get('error_type'), 'Java崩溃')
            stack, kind = self._stack(kind, r.get('sample'))
            pkg = self.o('包名') or r.get('bundle') or ''
            yield {'外部ID': r['issue_id'], '标题': ' · '.join(x for x in (r.get('title'), r.get('subtitle')) if x), '类型': kind, '堆栈': stack,
                   '次数': r.get('events') or 1, '用户数': r.get('users') or 0, '版本': r.get('version') or '',
                   '首次': local_time(r.get('first_seen')), '最近': local_time(r.get('last_seen')),
                   '链接': f'https://console.firebase.google.com/project/{proj}/crashlytics/app/android:{pkg}/issues/{r["issue_id"]}',
                   '状态': r.get('error_type') or ''}
        state['同步'] = {'BigQuery': f'{datetime.now():%Y-%m-%d %H:%M} 最近 {self.o("天数")} 天 {len(rows)} 个问题'}
