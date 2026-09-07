# Uses an already-installed local application image. No pulls or package installs.
FROM ctxbench/worker:0.1.0 AS base
USER root
FROM base AS success
RUN printf 'progress-test: first output\n' && sleep 3 && printf 'progress-test: completed\n'
FROM base AS failure
RUN printf 'progress-test: failure started\n' && sleep 2 && printf 'progress-test: expected failure\n' >&2 && exit 7
