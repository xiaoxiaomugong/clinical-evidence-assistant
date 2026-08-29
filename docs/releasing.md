# 发布安装包

项目通过 `.github/workflows/release.yml` 同时构建 Python 包和四个桌面产物：Windows x64、
macOS arm64、macOS x86_64 与 Debian/Ubuntu amd64。构建必须在对应操作系统的 GitHub runner
上原生完成，不能用一个平台的二进制替代另一个平台。

## 发布前检查

1. 更新 `pyproject.toml` 和 `src/evidence_assistant/__init__.py` 中的版本号。
2. 运行 `pytest -q`、`python scripts/smoke_test.py` 和 `make package-check`。
3. 确认知识页与 `data/raw/local_corpus.json` 可以再分发。
4. 确认 `.env`、PDF、SQLite 索引、模型和生成缓存没有进入 Git。
5. 创建与项目版本一致的标签，例如版本 `0.1.0` 对应 `v0.1.0`。

推送标签后自动发布：

```bash
git tag -s v0.1.0 -m "Clinical Evidence Assistant v0.1.0"
git push origin v0.1.0
```

也可以从 Actions 手动运行 `Build release packages`。手动运行只生成供检查的 Actions artifacts，
不会创建正式 GitHub Release；只有 `v*` 标签会发布 Release。

## 产物内容

桌面构建使用 PyInstaller onedir 模式，随后包装成平台安装格式。安装包包含：

- Python 运行时、Streamlit 和程序代码；
- `app.py`、五个知识页、精选文献快照及语料版本；
- MIT License。

安装包明确排除：

- `500-collection/` 中的论文 PDF；
- `data/raw/pdf_collection.sqlite3` 和稠密索引；
- sentence-transformers、Torch、交叉编码器模型；
- `.env`、API key、Supabase secret 和用户缓存。

应用运行时把缓存和可选 `.env` 放在用户目录：

| 系统 | 缓存 | 可选配置文件 |
|---|---|---|
| macOS | `~/Library/Caches/Clinical Evidence Assistant` | `~/Library/Application Support/Clinical Evidence Assistant/.env` |
| Windows | `%LOCALAPPDATA%\Clinical Evidence Assistant\Cache` | `%APPDATA%\Clinical Evidence Assistant\.env` |
| Linux | `${XDG_CACHE_HOME:-~/.cache}/clinical-evidence-assistant` | `${XDG_CONFIG_HOME:-~/.config}/clinical-evidence-assistant/.env` |

不要在 GitHub Actions、安装目录或构建产物中写入真实密钥。

## 签名与 notarization

没有签名 secrets 时，工作流仍会产出可测试安装包：macOS 使用 ad-hoc 签名，Windows 不签名。
公开发布建议在 GitHub Actions repository secrets 中配置：

| Secret | 用途 |
|---|---|
| `WINDOWS_CERTIFICATE` | Base64 编码的代码签名 PFX |
| `WINDOWS_CERTIFICATE_PASSWORD` | PFX 密码 |
| `MACOS_CERTIFICATE` | Base64 编码的 Developer ID Application `.p12` |
| `MACOS_CERTIFICATE_PASSWORD` | `.p12` 密码 |
| `MACOS_KEYCHAIN_PASSWORD` | 临时构建 keychain 密码 |
| `APPLE_ID` | Apple notarization 账号 |
| `APPLE_TEAM_ID` | Apple Developer Team ID |
| `APPLE_APP_PASSWORD` | Apple app-specific password |

工作流会先签名应用，再生成安装包；macOS 凭据齐全时还会提交 notarization 并 staple DMG。
Release 中的 `SHA256SUMS.txt` 用于校验下载完整性。

## 本地构建

在当前操作系统上安装构建依赖并运行：

```bash
python3 -m pip install '.[ui]' 'pyinstaller>=6.10,<7'
pyinstaller --clean --noconfirm packaging/clinical_evidence_assistant.spec
```

检查冻结后的程序：

```bash
dist/ClinicalEvidenceAssistant/ClinicalEvidenceAssistant --server-check
```

macOS 的可执行文件位于：

```text
dist/Clinical Evidence Assistant.app/Contents/MacOS/ClinicalEvidenceAssistant
```

Linux 可以继续运行 `bash packaging/build-deb.sh VERSION` 生成 `.deb`；Windows 安装器由
`packaging/windows-installer.iss` 和 Inno Setup 6 生成。
