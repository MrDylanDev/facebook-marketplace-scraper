# Portfolio demo image: the MercadoLibre API path works out of the box.
# The Facebook path serves the recorded fixture unless you override
# FB_FIXTURE=0 and mount your own auth_state.json (see README + DISCLAIMER).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    FB_FIXTURE=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ ./src/
# Fixture path is repo-root anchored (see FixtureLoader), so it must ship
# at tests/fixtures/ for FB_FIXTURE=1 to work inside the image.
COPY tests/fixtures/ ./tests/fixtures/

# Playwright system deps install as root; --with-deps pulls the packages
# Chromium needs (no manual apt list to drift out of date).
RUN pip install --no-cache-dir ".[facebook]" \
    && python -m playwright install --with-deps chromium

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/out \
    && chown -R appuser:appuser /app /ms-playwright

USER appuser

ENTRYPOINT ["python", "-m", "src.cli"]
CMD ["--help"]
