FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    COURSESCOPE_DB=/data/coursescope.sqlite \
    COURSESCOPE_SEARCH_DB=/data/coursescope-search.sqlite \
    COURSESCOPE_CATALOG_DB=/data/ucdavis-catalog.sqlite

WORKDIR /app
RUN pip install --no-cache-dir gunicorn==23.0.0
COPY src/ucd_rmp/ /app/src/ucd_rmp/
COPY work/ui-mockup/index-v3.html /app/work/ui-mockup/index-v3.html
COPY docs/openapi.json /app/docs/openapi.json
COPY docs/agent-prompt-en.txt docs/agent-prompt-zh.txt docs/llms.txt /app/docs/

EXPOSE 8000
CMD ["gunicorn", "ucd_rmp.web:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "30", "--access-logfile", "-", "--error-logfile", "-"]
