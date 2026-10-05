FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# DEBUG must stay off here: only then does Django use the hashed, compressed manifest storage.
RUN DJANGO_SECRET_KEY=collectstatic-build-only python manage.py collectstatic --noinput
# A home directory is needed by gunicorn >= 26 (control socket in ~/.gunicorn).
RUN useradd --system --create-home --uid 1001 app && chown -R app /app
USER app
EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-"]
