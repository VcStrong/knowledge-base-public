"""接口注册表：每个接口是一个函数，用装饰器登记，server 按路径分发。

    @get('/api/brief')
    def _get_brief(self, u, q): ...                  # self 是请求处理器（_send / _guard），q 是查询参数

    @post('/api/brief/act', page_only=True)          # page_only：只能在知识库网页上由本人点（拍板、推动这类），带令牌的 MCP / 脚本调不了
    def _post_act(self, u, n, body): ...              # body 是解析好的 JSON；raw=True 时不解析，处理函数自己读 n 字节（上传文件）

同一路径重复登记直接报错，免得后写的悄悄盖掉先写的。
"""

ROUTES = {'GET': {}, 'POST': {}}


class Route:
    __slots__ = ('fn', 'page_only', 'raw')

    def __init__(self, fn, page_only=False, raw=False):
        self.fn, self.page_only, self.raw = fn, page_only, raw


def _reg(method, paths, page_only=False, raw=False):
    def deco(fn):
        for p in paths:
            if p in ROUTES[method]:
                raise RuntimeError(f'{method} {p} 重复登记：{ROUTES[method][p].fn.__module__} 和 {fn.__module__}')
            ROUTES[method][p] = Route(fn, page_only, raw)
        return fn
    return deco


def get(*paths):
    return _reg('GET', paths)


def post(*paths, page_only=False, raw=False):
    return _reg('POST', paths, page_only, raw)


def find(method, path):
    return ROUTES[method].get(path)
