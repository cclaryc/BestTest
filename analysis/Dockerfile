# Image for the BestTest analysis service.
#
#   docker build -t besttest-analysis analysis
#
# Two stages: the first installs everything into a virtual environment, the
# second copies only that environment. Build tools and pip's caches never reach
# the image that runs.

ARG PYTHON_IMAGE=python:3.12-slim

FROM ${PYTHON_IMAGE} AS build

# The timeout and retries are for slow connections: pip gives up on a package
# index page after 15 seconds by default, and then reports the package as
# missing rather than as a network problem.
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

WORKDIR /src
# Dependencies first, in their own layer. They change rarely, so editing source
# code does not make Docker download them again.
COPY requirements.lock ./
RUN pip install --requirement requirements.lock

COPY pyproject.toml README.md ./
COPY src ./src
# pip has done its job. Removing it leaves one tool fewer in the running image
# for anyone who gets a foothold there.
RUN pip install --no-deps . && pip uninstall --yes pip


FROM ${PYTHON_IMAGE} AS runtime

# A fixed numeric id, so a read-only mount can be checked against it and the
# container can be required to run as non-root by number.
RUN groupadd --system --gid 10001 analysis \
    && useradd --system --uid 10001 --gid analysis --no-create-home --shell /usr/sbin/nologin analysis

COPY --from=build /opt/venv /opt/venv

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BESTTEST_HOST=0.0.0.0 \
    BESTTEST_PORT=8000 \
    BESTTEST_SNAPSHOT_ROOT=/snapshots

USER 10001:10001
EXPOSE 8000

# The container is healthy when the service says it can do its job.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2).status != 200)"]

CMD ["python", "-m", "analysis.api"]
