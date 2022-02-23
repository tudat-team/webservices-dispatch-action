FROM python:3-slim
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
  git

# We are installing a dependency here directly into our app source dir
RUN pip install PyGithub \
  pygit2 \
  cffi \
  bumpversion

#--target=/app requests PyGithub pygit2 cffi

# A distroless container image with Python and some basics like SSL certificates
# https://github.com/GoogleContainerTools/distroless
ENV PYTHONPATH /app
CMD ["python", "/app/main.py"]