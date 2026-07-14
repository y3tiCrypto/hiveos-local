FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Create a non-privileged user and adjust ownership
RUN useradd -u 10001 -m miner && chown -R miner:miner /app
USER miner
EXPOSE 8080
VOLUME /app/data
CMD ["python", "app.py"]
