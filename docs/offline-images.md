# Offline Docker image releases / 离线镜像发布

Docker images are separate GitHub assets, not embedded in the Windows installer or committed to Git. The initial target is **Linux amd64**, for Docker Engine inside the desktop's selected WSL2 distribution. Packaging and importing require Python 3.10+ (standard library only), Docker Engine, and the Compose plugin. Publishing also requires an authenticated GitHub CLI (`gh auth login`). No Provider credentials or paid model calls are needed.

镜像作为独立 GitHub 附件发布，不塞进 Windows 安装包，也不提交到 Git。首版仅支持 **Linux amd64**。所有 Docker 操作应在桌面选定的同一个 WSL2 发行版执行；需要 Python 3.10+、Docker Engine 和 Compose。发布还需要已登录的 GitHub CLI。整个流程不需要模型密钥，也不会调用 Provider。

## GitHub Actions

- **Manual snapshot:** Actions → **Offline Docker images** → Run workflow; leave `release_tag` blank. Builds the selected ref and uploads `ctxbench-offline-images-linux-amd64` as an Actions artifact retained for 14 days. This does not create or modify a Release.
- **Release:** publishing a GitHub Release triggers a build from that exact tag and attaches the image files to the same Release, separately from any installer. Both stable and prerelease publication are supported.
- **Existing/draft Release:** manually run the workflow with its `release_tag`; the workflow checks out the tag, not the selected branch. It only uploads to an existing Release and never creates tags, changes release notes, or overwrites conflicting assets. For immutable releases, attach the assets while the Release is still a draft, then publish it; attaching after it becomes immutable is not supported.

手动运行不填 `release_tag` 时，只生成 Actions 下载产物，保留 14 天。发布 Release 时，会基于该标签自动构建，并将镜像附件放在同一个 Release 下，与安装包独立下载。也可以手动填写已有 Release（包括草稿）的标签进行补传；标签和镜像源码提交必须一致。若仓库启用不可变 Release，应先在草稿阶段上传附件，再发布。

The workflow runs packaging tests, a tiny real Docker save/load regression, and offline entrypoint/runtime smoke tests. It does **not** certify full benchmark quality or perform a real Provider acceptance run. Build failures, missing images, wrong architecture, failed tests or export failures prevent publication. Rerunning publication of the **same local bundle** skips already uploaded assets only when GitHub's SHA-256 and size match. Rebuilding may change upstream package layers; a new conflicting build is deliberately not allowed to replace existing assets. Use a new release or resume uploading the original Actions artifact.

## Local build and upload / 本地构建与上传

From a clean, committed checkout in WSL/Linux:

```bash
python3 scripts/images-release.py pack --version v0.1.0 --output artifacts/images-v0.1.0
python3 scripts/images-release.py verify artifacts/images-v0.1.0
python3 scripts/images-release.py publish artifacts/images-v0.1.0 --repo mikyan/CTXBenchDesktop --tag v0.1.0
```

Replace the example version with an **existing Release tag pointing to this source commit**. Build uses the four Compose services with isolated `bundle-*` tags, so it does not replace local desktop image tags or restart any running services. Output must be a new directory. Failed exports retain `.incomplete` and partial files for diagnosis; retry into a new output directory. The script does not prune Docker images, cache or user data.

请将示例版本替换成实际 Release 标签。正式发布要求源码已提交且工作区干净。构建使用独立镜像标签，不覆盖本机桌面使用的镜像标签、不重启 Worker。输出目录必须尚不存在；失败后保留部分文件和 `.incomplete` 标记，请换新目录重试。脚本不自动清理镜像、缓存或实验数据。

For local testing only, `--allow-dirty` permits an uncommitted checkout and `--skip-build` exports the four existing Compose image tags. Such bundles are explicitly marked and **cannot be published by this script**; the source commit is not claimed as provenance for existing local images. An already-built image can contain arbitrary contents: only export images you trust, and never bake credentials into image layers, build arguments or Dockerfiles.

## Contents and size / 内容与大小

- One or more `ctxbench-images-<version>-linux-amd64.tar.gz.partNNNN` files: a streaming gzip-compressed `docker save` archive containing exactly Worker, Pi Agent, egress proxy and official harness.
- `ctxbench-images-manifest.json`: source commit/dirty flag, build mode, architecture, image references and IDs, ordered parts, sizes and SHA-256 hashes. It deliberately excludes `docker inspect` environment variables, history, host paths and runtime data.
- `ctxbench-images-SHA256SUMS`: portable, relative-filename checksums covering every payload and the manifest.
- `ctxbench-images.py`: self-contained verifier/importer/publisher; no pip installation required.
- `ctxbench-images-compose.json`: an offline-only Compose configuration, without build recipes, using `pull_policy: never`; environment variables remain unexpanded placeholders.
- `ctxbench-images-README.txt`: quick-start instructions in Chinese and English.

[GitHub requires each Release asset to be smaller than 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). The default compressed part size is 1900 MiB; use `--part-size-mib` to reduce it. Export/import stream data without holding the archive in RAM or creating a second combined tar file. Image layers and build cache still consume Docker/WSL disk space, independently of the output directory.

默认每片最多 1900 MiB，避免超过 GitHub 单附件上限。清单只保留明确允许的镜像元数据，不导出环境变量、历史、宿主路径或实验数据。镜像分片可以放在 D 盘，但构建层和缓存仍占用 WSL 所在磁盘空间。

## Offline import / 内网导入

Download **all** the image assets from the same Release into one folder (or extract the Actions artifact). Use trusted downloads: SHA-256 detects corruption, not the publisher's identity. Review/verify the importer before executing it. In the selected WSL distribution, change to that folder:

```bash
sha256sum --check ctxbench-images-SHA256SUMS
python3 ctxbench-images.py verify .
python3 ctxbench-images.py import .
docker compose -f ctxbench-images-compose.json up -d --no-build --pull never ctxbench-worker
```

The importer validates every file before changing Docker state, loads ordered compressed parts directly, preserves existing runtime aliases under `ctxbench/backup:sha256-...`, and applies the runtime aliases expected by this app version. It does not pull images, build anything, delete images, or restart containers. Stop active experiments before switching runtime images. After an interrupted import, fix the cause and rerun it. Backup tags are retained for manual rollback and are never silently pruned.

下载同一版本的全部镜像附件到同一目录。导入前会校验全部文件；缺片、损坏、清单不匹配或平台不符会报错。已有同名运行镜像先保留备份标签，导入不会自动启动/重启服务，也不会拉取或构建镜像。导入后再显式启动离线 Compose；这一步可能更新已有 Worker，因此应先停止实验。旧实验仍保留其冻结镜像身份，不能在一组配对中途切换镜像。

**Not included:** dataset instance images, prepared evaluator dependency images, datasets, repositories/base commits, experiment databases, generated knowledge packages or credentials. Four application images alone do not make an entire benchmark air-gapped. Internal Provider domains, package registries, CA trust and allowlisted runtime credentials still require site-specific configuration. Use the desktop release corresponding to the bundle; an older installed desktop's Build button uses its own bundled source and must not be used to rebuild these new images offline.

**不包含**用例实例/准备好的评分环境镜像、数据集、代码仓、实验库、知识库或凭据。完整离线评测仍需另行迁移这些资源，并配置内网 Provider、包源、证书和运行时环境变量。桌面安装包应与镜像版本配套；不要在离线环境点击旧安装版的“构建镜像”。原有 `images-export.sh` / `images-import.sh` 单 tar 脚本保持兼容；新的分片包请使用随包提供的 Python 导入器。
