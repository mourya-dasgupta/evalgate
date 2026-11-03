# Slim image for running EvalGate in any CI system:
#   docker build -t evalgate .
#   docker run --rm -u "$(id -u):$(id -g)" -v "$PWD:/work" evalgate gate
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip wheel --no-cache-dir --no-deps --wheel-dir /wheels .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels
WORKDIR /work
ENTRYPOINT ["evalgate"]
CMD ["--help"]
