FROM python:3.11-slim-bookworm@sha256:2333bd330d12de02514770b3585cad313644316047cdee24a7acfdece6de6efb

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHON_DOTENV_DISABLED=1 \
    HOME=/tmp
WORKDIR /app

COPY pyproject.toml README.md LICENSE app.py ./
COPY src/ ./src/
COPY data/corpus_version.json ./data/corpus_version.json
COPY data/knowledge_pages/ ./data/knowledge_pages/
COPY data/raw/local_corpus.json ./data/raw/local_corpus.json
COPY deploy/requirements-web.lock ./deploy/requirements-web.lock
RUN python -m pip install --no-cache-dir -r deploy/requirements-web.lock '.[web]'

USER 10001:10001
EXPOSE 8766
CMD ["python", "-m", "uvicorn", "evidence_assistant.web:create_app", "--factory", "--host", "0.0.0.0", "--port", "8766", "--workers", "1", "--no-access-log", "--log-level", "warning", "--no-proxy-headers"]
