# The Chromium build in this image is the one playwright==1.65.2 expects.
FROM mcr.microsoft.com/playwright/python:v1.65.2-noble

RUN apt-get update \
 && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify python3.12-venv \
 && rm -rf /var/lib/apt/lists/*

# App packages get their own venv: websockify runs on Debian's Python packages, which pip cannot replace.
RUN python3 -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /app
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
COPY . .

ENV PLAYGROUND_HOST=0.0.0.0 PLAYGROUND_PORT=8765 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER pwuser
EXPOSE 8765 6080
CMD ["python", "start.py"]
