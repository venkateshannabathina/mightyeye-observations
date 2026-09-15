FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir --no-deps . && useradd --create-home mightyeye && mkdir -p /app/output && chown -R mightyeye:mightyeye /app
USER mightyeye
EXPOSE 8000
CMD ["mightyeye-observations", "serve", "--host", "0.0.0.0", "--port", "8000"]
