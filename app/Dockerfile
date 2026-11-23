FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY portfolj ./portfolj
RUN useradd --system --no-create-home app && mkdir /data && chown app /data
USER app
