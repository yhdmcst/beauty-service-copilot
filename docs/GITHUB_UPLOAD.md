# GitHub上传

这是已解压的独立项目文件夹，不是原工作区全部内容。上传本文件夹内的项目文件即可，不要额外加入原 `.env`、数据库、官方附件或环境目录。

本次从已检查的源码ZIP新建，**不包含 `.git` 或旧Git历史**，尚未自动初始化、提交或推送。

## 建议步骤

1. 先创建Private仓库。公开数据授权和项目源码许可未确认，暂不改成Public。
2. 在GitHub Desktop中以本文件夹创建本地仓库；本次副本还没有Git元数据，不要选外层同时放着ZIP的目录。
3. 查看变更清单，确认没有 `.env`、`.venv`、`node_modules`、数据库、日志或原始账号字段。
4. 已有仓库就查看并提交本次变更，不重新初始化或替换历史；新仓库再创建首次提交。发布后检查README、运行指南和PPT链接。

GitHub网页上传不能自动保留压缩包内的目录结构。不要只上传ZIP就当作源码仓库，应解压并上传实际文件。文件较多时使用GitHub Desktop或Git客户端。

## 使用Git

本次文件夹尚未初始化Git。下面适用于新建空远端仓库，由你确认后执行：

```bash
git init -b main
git add .
git status --short
git commit -m "feat: add beauty customer-service copilot"
git remote add origin YOUR_REPOSITORY_URL
git push -u origin main
```

`YOUR_REPOSITORY_URL`换成你自己刚创建的仓库地址。新建远端空仓库时无需另外生成README，以免第一次推送产生分支冲突。本次整理没有执行commit、push或远端发布。

若后续你已把它接到现有仓库，先查看 `git status --short` 与 `git remote -v`，保留自己的历史，不重复初始化或覆盖远端。

## 发布前确认

- 先读 `DATA_POLICY.md`，核对赛题数据、截图和PPT的再发布权限。
- 仓库只有 `.env.example`，没有真实密钥。
- 源码许可未代选；需要开源许可时由项目权利人决定。
- 原30条人工记录不在上传包中，网页评估中心初始显示待标注属于正常情况。
- 模型和Python依赖由运行者安装；应用不需要Node，只有重建PPT或运行特定可选工具时才安装Node依赖。

GitHub官方参考：

- `https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository`
- `https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github`
- `https://docs.github.com/en/code-security/concepts/secret-security/secret-scanning`
