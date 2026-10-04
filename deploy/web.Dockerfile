FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:stable-alpine@sha256:ed04ec1ff34502c339ee5c3ae3f855442398edc1d05591e2b98981dcbbd20b1e

COPY deploy/web.conf /etc/nginx/nginx.conf
COPY --from=frontend-build /app/frontend/dist/ /usr/share/nginx/html/

EXPOSE 8080

# The image supplies its non-root user. Skip startup scripts that modify config
# so the container can run with a read-only filesystem and a writable /tmp.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
