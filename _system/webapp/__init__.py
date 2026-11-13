"""网页服务（kb web）：
  shared.py   帮助函数、后台循环（定时同步 Bug、刷新来源、管家巡检、文件变化推送）、各页面数据拼装
  router.py   接口注册表（@get / @post，page_only = 只能本人在网页上操作）
  routes/     各领域的接口，一个接口一个函数：static periods dev stack bugs anr plugins settings base steward
  server.py   请求处理器（鉴权、本人操作检查、分发）和 main()
加接口：在对应领域文件里写一个函数加装饰器；加领域：routes/ 下新文件，并写进 server.ROUTE_MODULES。
"""
