FROM python:3.12-slim
RUN useradd -m -u 1000 user && mkdir -p /app /opt/models && chown user /app /opt/models
WORKDIR /app
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
USER user
ENV PYTHONUNBUFFERED=1 RADAR_MODELS=/opt/models HF_HUB_DISABLE_TELEMETRY=1
# The embedding model is fetched once, at build time, so the Space starts without a download (public model, no key).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/opt/models')"
COPY --chown=user . .
EXPOSE 7860
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
