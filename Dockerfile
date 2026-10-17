FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY babel ./babel
COPY server.py ./
COPY static ./static
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8080"]
