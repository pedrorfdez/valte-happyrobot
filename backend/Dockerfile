# Crisis kernel. Build context is the REPO ROOT (schemas/ and scenarios/
# live outside backend/): docker build -f backend/Dockerfile .
FROM python:3.12-slim

WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]" "psycopg[binary,pool]" \
    pydantic-settings jsonschema

COPY schemas/ /schemas/
COPY scenarios/ /scenarios/
COPY backend/kernel/ /app/kernel/
COPY backend/dashboard/ /app/dashboard/
COPY backend/migrations/ /app/migrations/
COPY backend/scripts/migrate.py /app/scripts/migrate.py

ENV PORT=8100
CMD python scripts/migrate.py && \
    uvicorn kernel.main:app --host 0.0.0.0 --port ${PORT}
