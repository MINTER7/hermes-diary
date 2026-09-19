# Publishing / 发布指南

Target repository: **MINTER7/hermes-diary**.

## 中文步骤

1. 先在 GitHub 将 `MINTER7/-` 重命名为 `hermes-diary`；本发布包不会替你修改远程仓库。
2. 打开新版发布目录中的 `hermes-diary` 文件夹，把**里面的全部内容**上传到仓库根目录。根目录应直接有 README.md、README.zh-CN.md、skills、tests 等，不要只上传 ZIP 或多套一层文件夹。
3. 特别检查 `.github/workflows/tests.yml`、`.gitignore`、`.gitattributes` 是否上传，避免漏掉以点开头的文件。
4. 提交后查看 Actions 中的 Offline tests。用未登录或无痕窗口确认仓库和 `skills/diary-fragment/SKILL.md` 可以读取。
5. 在真实 Linux Hermes 环境执行安装命令、初始化本地模式，再按需要验证目标平台。安装下载成功、配置保存成功、真实推送成功是三个不同的验证阶段。

```bash
hermes skills install MINTER7/hermes-diary/skills/diary-fragment
```

英文介绍可填写：

> A native Hermes Agent diary skill. Capture everyday moments in Markdown, with English/Chinese headings and optional daily delivery to Telegram, Discord, Slack, or webhooks.

Topics 可使用：`hermes-agent`、`hermes-skill`、`diary`、`journaling`、`markdown`、`telegram`、`discord`、`slack`、`webhook`。

## English publishing checklist

- Rename the repository to `MINTER7/hermes-diary` before using the documented install command.
- Upload the repository contents at its root, including dotfiles and the full native skill directory.
- Check CI, anonymous file access, native installation, local setup, and any desired live delivery separately.
- Keep personal diary data, live credentials, config backups, and development scratch files out of the repository.
- Do not claim that installation alone creates a schedule or sends messages. New users default to local journaling; optional credentials can be skipped.

## Maintainer notes

Maintain executable code only in `skills/diary-fragment/scripts`. Root scripts are compatibility wrappers. New support files must have explicit relative links from SKILL.md for Hermes reference-only download compatibility.

Run `python3 -m unittest discover -s tests -v` after changes. CI is configured for Linux Python 3.9/3.12. Offline tests mock network calls and cron; the release archive does not assert real messaging-account delivery or a real Linux daemon test.

Runtime files stay outside the skill package so native updates do not overwrite journals or credentials. The English and Chinese READMEs should describe the same defaults and behavior.
