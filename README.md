# 本地知识库（kb）

把每一期需求的资料集中放在一处，交给 Claude Code 等编程 AI 使用；资料齐了，在网页上一键让 AI 按团队流程开发，并跟进 Bug、崩溃和构建。可以装在自己的 Mac 上（只给自己用），也可以装在远端服务器上用浏览器访问。密码在 Mac 上存钥匙串，在服务器上存加密文件。

怎么用见 [使用说明](使用说明.md)。

## 安装

需要 macOS、Python 3.9+、git，以及已登录的 [Claude Code](https://claude.com/claude-code)。

```sh
git clone https://github.com/VcStrong/knowledge-base-public.git ~/knowledge-base
cd ~/knowledge-base && ./install.sh          # 想登录后自动启动网页：./install.sh --autostart
```

装好后新开一个终端，按下面三步检查：

1. 运行 `kb`，能看到总览。
2. 运行 `kb web`，网页能打开。
3. 在 Claude Code 里输入 `/mcp`，能看到 `kb` 已连接。

密码不会跟着程序到新电脑，要在新电脑上重新登录：`kb login <网址> <用户名>`。

## 装在远端服务器（Linux）

```sh
git clone <仓库地址> ~/knowledge-base && cd ~/knowledge-base
./install.sh --host 0.0.0.0 --autostart        # 会先让你设网页访问密码；开机自启用 systemd
```

- **打开网页**：浏览器访问 `http://<服务器>:11555`，输入访问密码。放在公网前面加 HTTPS 反向代理（nginx / Caddy，保留 Host 头）。
- **本机的 Claude Code 连它**：在服务器上 `kb token add 我的Mac`，按提示在本机运行 `claude mcp add --transport http kb …`。
- **改密码**：`kb passwd`（所有浏览器要重新登录）。**令牌**：`kb token list` / `kb token del <名称>`。
- **密码存哪**：知识库目录 `.机密/store.enc`，主密钥在 `~/.config/kb/master.key`（或环境变量 `KB_MASTER_KEY`）。两个分开备份，丢了主密钥就打不开。
- **代码仓库**：服务器上的路径是「本机仓库」；别的机器上的仓库写 `user@主机:/路径`，服务器要能 ssh 免密登录过去，那台机器装好 claude。
- **手机**：只认插在服务器上的手机。

## 换电脑、升级、卸载

- **换电脑**：只带程序，不带资料。新电脑照上面的步骤安装即可，资料从零开始。要带某一期，就把 `期/<期名>/` 拷过去，再运行 `kb index docs`。
- **升级**：运行 `git pull`，然后重启网页，并在 Claude Code 里输入 `/mcp` 重连。
- **卸载**：
  1. 运行 `claude mcp remove kb -s user`。
  2. 删掉 `~/.zshrc` 里的 `kb` 别名。
  3. 删除 `~/knowledge-base`。

## 仓库里有什么

只有程序、说明文档和通用插件：`kb`、`install.sh`、`_system/`、`插件/`（工作统计、Jenkins、Hermes会话）、两份 `.md`。`.gitignore` 用白名单，期、基础信息、设置、索引都不会进仓库。

改进知识库后提交推送，其他电脑 `git pull` 即可：

```sh
cd ~/knowledge-base && git add -A && git commit -m "说明改了什么" && git push
```
