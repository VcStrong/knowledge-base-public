# From 大大王.DT
"""「Bug平台」插件：公司 / 小组特有的系统按同一协议实现，知识库用子进程调用。"""
import json
from .base import Source, SourceError, entry


# ---------------------------------------------------------------- 插件实现的平台（公司 / 小组特有的系统）

class PluginSource(Source):
    """plugin.json「类型」= Bug平台：命令后加子命令，stdin 给 JSON（来源状态、选项、范围），stdout 回 JSON。
      test                → {"文本": "…"}
      account             → {"账号": "…"}
      sync                → {"条目": [统一条目…], "删除": [编号…], "状态": {…新的来源状态}}
      get <编号> [--no-download] → {"条目": {…}, "正文": "…", "信息": [], "评论": [[时间, 人, 动作, 内容]], "附件": [路径…]}
    账号经环境变量 KB_PLUGIN_BASE 交给插件（和其他插件一样）。"""
    def __init__(self, conf, cred, plugin=None, runner=None):
        super().__init__(conf, cred)
        self.plugin = plugin or {}
        self.kind = self.plugin.get('平台类型') or '缺陷'
        self.adapter = self.plugin.get('名称') or conf.get('适配器')
        self.runner = runner          # (args, stdin) → stdout，由 kb 提供（统一处理环境变量、超时）

    def _run(self, *args, data=None):
        out = self.runner(list(args), json.dumps(data or {}, ensure_ascii=False))
        try:
            return json.loads(out[out.index('{'):]) if '{' in out else {}
        except ValueError:
            raise SourceError(f'插件「{self.adapter}」输出的不是 JSON：{out[:300]}')

    def _ctx(self, ctx=None):
        return {'选项': self.opt, '范围': self.conf.get('范围'), '人员': sorted((ctx or {}).get('人员') or []),
                '平台': self.conf.get('平台'), '全量': bool((ctx or {}).get('全量'))}

    def account(self):
        return str(self._run('account', data=self._ctx()).get('账号') or '')

    def test(self):
        return self._run('test', data=self._ctx()).get('文本') or '（插件没有输出）'

    def sync(self, state, ctx):
        r = self._run('sync', data=dict(self._ctx(ctx), 状态=state))
        state.clear()
        state.update(r.get('状态') or {})
        for k in r.get('删除') or []:
            yield {'删除': self.key(k)}
        for x in r.get('条目') or []:
            yield entry(self, **x) if self.kind == '缺陷' else dict(x, 来源=self.id)

    def get(self, key, download=True):
        r = self._run('get', self.num(key), *([] if download else ['--no-download']), data=self._ctx())
        if not r.get('条目'):
            raise SourceError(f'插件「{self.adapter}」找不到 {key}')
        r['条目'] = entry(self, **r['条目'])
        r['评论'] = [tuple(x) for x in r.get('评论') or []]
        return r
