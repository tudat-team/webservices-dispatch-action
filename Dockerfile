FROM python:3-slim AS builder
ADD . /app
WORKDIR /app

# update basic python packages
RUN apt-get update && apt-get install -y \
  python3-pip  \
  python3-dev  \
  build-essential  \
  libssl-dev  \
  libffi-dev  \
  python3-setuptools \
  && rm -rf /var/lib/apt/lists/*

# We are installing a dependency here directly into our app source dir
RUN pip install --target=/app requests PyGithub pygit2 cffi

# A distroless container image with Python and some basics like SSL certificates
# https://github.com/GoogleContainerTools/distroless
FROM gcr.io/distroless/python3-debian10
COPY --from=builder /app /app
WORKDIR /app
ENV PYTHONPATH /app
CMD ["/app/main.py"]