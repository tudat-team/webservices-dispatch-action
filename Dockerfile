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
  wget \
  git

# We are installing a dependency here directly into our app source dir
RUN pip install PyGithub \
  pygit2 \
  cffi \
  bumpversion

# Install conda
RUN wget \
  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
  && mkdir /root/.conda \
  && bash Miniconda3-latest-Linux-x86_64.sh -b \
  && rm -f Miniconda3-latest-Linux-x86_64.sh 
RUN conda --version

# Install conda-smithy environment
RUN conda install -n root -c conda-forge conda-smithy

#--target=/app requests PyGithub pygit2 cffi

# A distroless container image with Python and some basics like SSL certificates
# https://github.com/GoogleContainerTools/distroless
ENV PYTHONPATH /app
CMD ["python", "/app/main.py"]