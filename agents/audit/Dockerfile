FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV REDIS_URL=redis://redis:6379/0
ENV OLLAMA_URL=http://ollama:11434
VOLUME ["/data/audit_logs"]

CMD ["python", "audit_agent.py"]
