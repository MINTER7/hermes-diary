# Hermes Diary

**随手记下生活，日记留在自己手里，想在哪里看就送到哪里。**

[English](README.md) · 简体中文

一个可通过原生技能管理器安装的 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 日记技能。把零散的生活记录整理成每日 Markdown 日记，保存在本地，也可发送到 **Telegram、Discord、Slack 或自定义 HTTPS Webhook**。

```text
周六 · 2026.09.19 · 深圳

[08:10] — 上班前去面包店买了早餐。
[12:30] — 和朋友一起吃午饭。
[18:45] — 完成了演示文稿初稿。
```

记录使用你平时说话的语言。汇总程序只添加标题、拼接已有条目，不额外调用 AI 改写日记正文。

## 能做什么

- **本地 Markdown**：离开 Hermes 仍然可以直接阅读、备份和迁移。
- **原生安装更新**：通过 Hermes 技能管理器维护代码。
- **中文和英文标题**：支持 IANA 时区、摄氏/华氏温度、自定义每日汇总时间。
- **多种推送方式**：本地、Telegram、Discord、Slack、通用 Webhook 五选一。
- **天气可选**：新用户默认关闭；需要时按明确设置的城市查询。
- **可恢复发送**：长日记自动分段，保存已确认进度，不确定送达时暂停等待核对。

这是社区技能，运行目标为 **Linux**，包括持久运行的 Linux 服务器或 WSL 环境；并非 Hermes 或各聊天平台的官方产品。

## 三步开始

需要 Hermes Agent、Python **3.9+**、Bash 和系统 `tzdata`。运行程序只使用 Python 标准库。定时任务额外需要已经安装且运行中的 **cron**；手动记录不需要 cron。

### 1. 安装

```bash
hermes skills install MINTER7/hermes-diary/skills/diary-fragment
```

安装只下载并扫描技能文件，**不会自动创建定时任务或发送消息**。

### 2. 开启新的 Hermes 会话

```text
/diary-fragment 帮我初始化本地日记，使用中文标题和 Asia/Shanghai 时区，先关闭天气和自动推送。
```

Hermes 加载技能时可能显示安全凭据输入提示。**只在本地记录时全部跳过**；需要推送时只填所选渠道的凭据，已有配置可以复用。不要把 Token 或 Webhook 地址发到聊天里。

### 3. 记录与预览

```text
/diary-fragment 记一下，12:30 和朋友一起吃了午饭。
/diary-fragment 看看今天的日记，先不要发送。
```

中英文可以混合记录。切换标题语言不会翻译、覆盖或重写已有内容。

## 选择日记的去向

所有模式都保留本地原始记录和汇总 Markdown。每个 profile 一次选择**一个推送目标**，本版本不同时群发多个平台。

| 模式 | 行为 | 需要配置 |
| --- | --- | --- |
| `local`，新用户默认 | 只在本地保存日记 | 不需要推送凭据 |
| `telegram` | 使用 Telegram Bot API 发送 | 日记专用 Bot Token 和聊天/频道 ID |
| `discord` | 发到频道或已有讨论串 | Incoming Webhook 地址 |
| `slack` | 发到 Webhook 绑定的会话 | Incoming Webhook 地址 |
| `webhook` | 向自定义 HTTPS 接口 POST JSON | 接口地址，可选 Bearer Token |

通用 Webhook 可以连接能接收[约定格式](skills/diary-fragment/references/delivery.md)的自动化服务或自建接口，不表示已经原生支持所有聊天软件和邮箱。日记的推送配置与 Hermes 聊天网关相互独立。

例如对 Hermes 说：

```text
/diary-fragment 每天 Asia/Shanghai 时间 23:30 把日记发到 Discord，使用中文标题，先不查天气。
```

Hermes 会引导配置。使用 Discord 或 Slack 不需要 Telegram 机器人。

## 在终端配置

使用 Hermes 显示的实际技能路径。下面是默认路径；使用分类目录或自定义 profile 时请替换路径，并在保存日记的那台机器上操作：

```bash
DIARY_SKILL="${HERMES_HOME:-$HOME/.hermes}/skills/diary-fragment"
python3 "$DIARY_SKILL/scripts/setup_diary.py" check
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --delivery local --language zh --timezone Asia/Shanghai \
  --no-schedule --non-interactive
```

不加 `--non-interactive` 可以交互填写；秘密输入会隐藏显示。全新配置的默认值为：本地保存、英文标题、UTC 时区、无天气、无定时任务。城市未设置就保留为空，不会根据 IP 猜测。

每天 23:59 **只在本地汇总**：

```bash
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --reconfigure --delivery local --schedule --at 23:59 --non-interactive
```

开启 **Discord 定时推送**，在自己的 Bash 终端中输入：

```bash
read -r -s -p "Discord webhook URL: " HERMES_DIARY_WEBHOOK_URL; printf '\n'
export HERMES_DIARY_WEBHOOK_URL
python3 "$DIARY_SKILL/scripts/setup_diary.py" configure \
  --reconfigure --delivery discord --schedule --at 23:30 --non-interactive
unset HERMES_DIARY_WEBHOOK_URL
```

`read -s` 会隐藏地址，并避免把地址的字面值写进 shell 命令历史。Slack 使用 `--delivery slack` 和 Slack Webhook；自定义接口使用 `--delivery webhook`。Telegram、可选接口认证和返回值要求见[推送配置](skills/diary-fragment/references/delivery.md)。

| 参数 | 用法 |
| --- | --- |
| `--language` | `zh` 或 `en`；控制标题和首次生成的偏好模板 |
| `--timezone` | 如 `Asia/Shanghai`、`Europe/London`、`America/New_York` |
| `--city` | 如 `深圳`；用于标题和可选天气查询 |
| `--weather` / `--no-weather` | 开启 / 关闭天气查询 |
| `--temperature-unit` | `C` 摄氏或 `F` 华氏 |
| `--schedule --at HH:MM` | 开启指定当地时间的每日任务 |
| `--no-schedule` | 关闭当前 profile 的定时任务，仍可手动运行 |
| `--diary-dir` | 指定技能目录之外的数据目录 |
| `--reconfigure` | 修改已有设置，并备份旧配置 |

重新配置时保留已有定时开关，除非明确加 `--schedule` 或 `--no-schedule`。使用 `--reconfigure --city` 也会更新当前城市。已有 `notes/preferences.md` 不会被覆盖；需要改变写作偏好时直接编辑它。命令行帮助和运行诊断使用英文。

## 常用命令

统一入口为 `python3 "$DIARY_SKILL/scripts/diary_cli.py"`，后面追加：

| 命令 | 功能 |
| --- | --- |
| `context` | 获取实际时钟、非秘密配置、城市、写作偏好 |
| `record '中午和朋友吃饭' --at 12:30` | 追加一条记录 |
| `today` | 读取当天原始记录 |
| `city 深圳` | 明确设置当前城市 |
| `compose` | 生成 Markdown，不推送 |
| `run` | 汇总后按选定模式保存或发送 |
| `send` | 发送已生成日记，或继续未完成的固定内容 |
| `status` | 查看计划时间和未完成发送 |
| `logs` | 最近 100 行定时日志 |

按日操作的命令支持 `--date YYYY-MM-DD`。[完整命令与恢复说明](skills/diary-fragment/references/commands.md)

## 定时和失败恢复

cron 每分钟检查一次，程序按配置时区和时间执行，支持时区自身的夏令时变化。当天到点后处理当天日记，同时尝试补发前一天未完成的日记；更早日期需手动执行 `run --date`。

没有记录就不发消息；普通重试不重发已经确认的段落。明确的 HTTP 拒绝会延迟至少 60 秒，并遵守可识别的限流等待时间。网络超时、服务错误、进程中断等情况可能发生在远端已接收之后，因此会暂停，等待用户检查目标平台再核对状态。

这**不保证严格的“恰好发送一次”**。通用 Webhook 接收端应使用稳定事件 ID 或 `Idempotency-Key` 去重；HTTP 成功只表示接收端接受请求，不代表下游邮件或聊天消息已经送达。

一次已完成的日记发送是一份固定内容。之后新增的条目仍保存在原始文件中；需要发送修订版时先 `compose`，再明确 `resend`。更换推送目标后，对已经有发送状态的日期也需显式 `resend`，避免意外转发已有日记。建议把计划时间设在临近一天结束时。

开启天气后，标题中的天气是**汇总时查询到的天气**。历史日记未保存的天气和城市会标注“未记录”；已有的汇总文件可以保留先前标题，不会伪造历史信息。

## 文件与隐私

新 profile 的数据默认保存在 `${HERMES_HOME:-~/.hermes}/diary/data/`；旧版保留原数据目录，包括原有 `~/diary`。

```text
<HERMES_HOME>/diary/
├── config.env           # 设置及凭据，权限 600
├── config.env.bak       # 重新配置时生成的旧配置备份
├── setup.json           # 初始化状态，不含凭据
└── data/                # 新配置默认目录，可更改
    ├── 2026-09-19.md     # 原始记录
    ├── composed/        # 每日汇总
    ├── notes/           # 城市、偏好
    ├── state/           # 文件锁、发送内容和进度
    └── cron.log         # 定时日志
```

新用户默认不推送。`local` 模式且关闭天气时，日记程序不发送网络请求；你与 Hermes 的对话仍遵循 Hermes 与模型服务的配置。开启天气会把设置的城市发送给 [wttr.in](https://github.com/chubin/wttr.in)，开启推送会把日记内容发送到你选择的目标。

凭据保存在本地权限受限的文件中，**并非加密存储**。配置、备份、日记和发送状态都不应上传到公开仓库。Webhook 地址本身也是凭据；状态输出和发送日志文件不保存其原文或 Bot Token。Webhook 发送不跟随重定向。

使用专用 `HERMES_DIARY_*` 环境变量，不会挪用 Hermes 聊天网关的 `TELEGRAM_BOT_TOKEN`。环境覆盖只影响当前进程；要让 cron 使用更改后的值，执行 `configure --reconfigure` 持久保存。见[配置参考](skills/diary-fragment/references/setup.md)和[配置示例](config/config.example.env)。

## 更新、迁移与卸载

```bash
hermes skills check
hermes skills update diary-fragment
```

程序只保存在技能包中，配置和数据独立保存。同路径正常更新无需复制程序或重建 cron。

v2.2 及更早版本使用原来的 `HERMES_HOME` 安装/更新技能，再执行 `setup_diary.py configure --non-interactive`。保留旧 Telegram 配置、中文标题、时区、数据目录、偏好和旧版发送进度。v2.2 的初始化状态会保留定时开关，可识别的更早版本 cron 会迁移；主动修改设置时加 `--reconfigure`。

卸载前先关闭定时：

```bash
python3 "$DIARY_SKILL/scripts/setup_diary.py" disable
hermes skills uninstall diary-fragment
```

日记与配置保留。没有自动卸载回调；若先卸载技能，cron 条目会因程序不存在而静默跳过，但仍需清理。[配置与迁移说明](skills/diary-fragment/references/setup.md)

## 开发与验证

```bash
python3 -m unittest discover -s tests -v
```

离线测试覆盖旧版迁移、多语言标题、温度单位、本地模式、各渠道请求格式、Unicode 分段、重试、不确定送达、目标切换、锁、定时和独立安装。测试使用临时目录与模拟服务，不发送真实消息、不修改真实 crontab。CI 配置为 Linux Python 3.9 和 3.12。

真实账号、真实 cron 服务和远程 Hermes 安装仍需在部署环境验证，离线测试通过不代表任意机器人或 Webhook 已配置正确。

根目录 `install.sh`、`update.sh`、`uninstall.sh` 用于兼容本地源码安装；公开分发优先使用前面的原生安装命令。[发布步骤](PUBLISHING.md)

## 许可证

[MIT](LICENSE)。欢迎贡献代码和翻译。反馈问题时请勿附带真实日记、Token 或 Webhook 地址。
