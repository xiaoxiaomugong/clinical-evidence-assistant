# 香港服务器部署

目标：Ubuntu 22.04、`YXS@47.76.105.0`、`clinicalevidenceassistant.xin`。
宿主机已有 Nginx 和其他网站；新增独立站点，将请求转发到本机 `127.0.0.1:8088`。

## 部署内容

- `compose.deploy.yaml`：独立 Compose 项目 `clinical-evidence`，两个服务。
- `api.Dockerfile`：Python 3.11、单 worker、内置公开语料、非 root 用户。
- `web.Dockerfile` / `web.conf`：生产前端、非 root Nginx、SPA 路由和 API 转发。
- `host-nginx.conf`：初始 HTTP 站点，ACME 验证目录与查询限流。
- `host-nginx.https.conf`：取得证书后替换同一站点文件，提供 HTTPS 和 HTTP 跳转。
- `requirements-web.lock`：本轮镜像实际安装的 Python 依赖版本。

基础镜像固定到已验证的 digest，前端使用 npm lockfile。后续升级依赖或基础镜像时重新验证。
后端只连接内部网络，未发布后端端口；Web 只发布服务器本机的 8088。
容器使用只读根文件系统、临时目录、资源限制、健康检查和自动重启。
API 固定使用五个知识主题与十条精选快照；在线检索、云端数据库和模型仍由该入口关闭。

## 1. 从 Mac 上传

保留 SSH 窗口，在 Mac 新开一个本地终端执行：

```sh
scp "/Users/yangxuesong/Clinical Evidence Assistant/dist/clinical-evidence-deploy-20261002.tar.gz" YXS@47.76.105.0:~/
```

输入 YXS 的服务器密码。上传包只包含应用源码、前端、内置公开语料和部署配置。

## 2. 在服务器构建和检查

回到 SSH 窗口执行：

```sh
mkdir -p ~/clinical-evidence-assistant
tar -xzf ~/clinical-evidence-deploy-20261002.tar.gz -C ~/clinical-evidence-assistant --strip-components=1
cd ~/clinical-evidence-assistant
sudo docker compose -f compose.deploy.yaml config --quiet
sudo docker compose -f compose.deploy.yaml up -d --build --wait --wait-timeout 120
sudo docker compose -f compose.deploy.yaml ps
curl --fail --silent --show-error http://127.0.0.1:8088/health/ready
python3 deploy/smoke_test.py
```

两项服务应显示 `healthy`，健康检查返回 `{"status":"ready"}`，HTTP 验收脚本打印 `PASS`。构建需要访问 Docker Hub、npm 和 PyPI。
若构建或健康检查失败，先查看此项目日志：

```sh
sudo docker compose -f compose.deploy.yaml logs --tail=80
```

## 3. 新增宿主机 HTTP 站点

先确认没有已存在的同名配置：

```sh
sudo ls -l /etc/nginx/sites-available/clinicalevidenceassistant.xin /etc/nginx/sites-enabled/clinicalevidenceassistant.xin
```

首次部署应提示这两个路径不存在。若存在，先确认是否为这个项目的旧配置，再决定更新。
创建备份及新配置：

```sh
sudo cp -a /etc/nginx /etc/nginx.backup-clinical-20261002
sudo mkdir -p /var/www/clinical-evidence-acme/.well-known/acme-challenge
sudo install -m 644 deploy/host-nginx.conf /etc/nginx/sites-available/clinicalevidenceassistant.xin
sudo ln -s /etc/nginx/sites-available/clinicalevidenceassistant.xin /etc/nginx/sites-enabled/clinicalevidenceassistant.xin
sudo nginx -t
```

只有配置测试成功后才 reload：

```sh
sudo systemctl reload nginx
curl --fail --silent --show-error -H 'Host: clinicalevidenceassistant.xin' http://127.0.0.1/health/ready
```

返回 `ready` 说明宿主 Nginx 已将这个域名接入新网站。
此阶段宿主机对查询提交实行每 IP 平均 12 次/分钟、突发 3 次、并发 2 次的限制，超限返回 429。
网站访问日志关闭；Docker 运行日志按文件大小轮换。Nginx 技术错误日志仍沿用服务器设置。

## 4. DNS 与 HTTPS

阿里云主域名 A 记录：`@ → 47.76.105.0`。先确认公共 DNS 返回这一 IP；如果仍是 NXDOMAIN，继续核对注册局委派与公共缓存。
证书申请需要域名已解析至本服务器，并且公网能访问 80 端口。

检查现有 Certbot：

```sh
certbot --version
```

服务器已有多个 Let's Encrypt 网站，优先使用现有 Certbot。然后按提示填写联系邮箱并确认服务条款：

```sh
sudo certbot certonly --webroot -w /var/www/clinical-evidence-acme -d clinicalevidenceassistant.xin --cert-name clinicalevidenceassistant.xin
```

证书签发成功后，替换同一站点文件：

```sh
sudo install -m 644 deploy/host-nginx.https.conf /etc/nginx/sites-available/clinicalevidenceassistant.xin
sudo nginx -t
```

只有测试成功后再 reload，然后验证证书、HTTP 跳转与 HTTPS 健康检查：

```sh
sudo systemctl reload nginx
curl --head http://clinicalevidenceassistant.xin/
curl --fail --silent --show-error https://clinicalevidenceassistant.xin/health/ready
python3 deploy/smoke_test.py --url https://clinicalevidenceassistant.xin
```

保存用于证书续期后加载新证书的独立 hook，并只对这个证书做续期演练：

```sh
sudo mkdir -p /etc/letsencrypt/renewal-hooks/deploy
sudo install -m 755 deploy/certbot-reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/clinical-evidence-reload-nginx
sudo certbot renew --cert-name clinicalevidenceassistant.xin --dry-run
systemctl list-timers --all | grep -i certbot
```

查看原有 Certbot 定时机制，确保自动续期已启用。该 hook 先执行 `nginx -t`，通过后才 reload。
最后在浏览器验收首页、`/ask`、`/professional`、`/topics`、引用详情和证据不足拒答。

## 更新与停止

更新源码后，在本项目目录重建并等待健康：

```sh
sudo docker compose -f compose.deploy.yaml up -d --build --wait --wait-timeout 120
```

仅停止这个项目：

```sh
sudo docker compose -f compose.deploy.yaml down
```

若需要撤回新增域名入口，移除本项目的启用链接后，先测试 Nginx，再 reload。
该包未包含服务器密码、`.env`、私有 PDF、索引、模型或用户缓存。

参考：[Docker Compose](https://docs.docker.com/reference/compose-file/services/)、[Nginx 域名站点](https://nginx.org/en/docs/http/request_processing.html)、[Certbot webroot](https://certbot.eff.org/instructions?os=ubuntufocal&tab=standard&ws=other)。
