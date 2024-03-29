FROM python:3-slim
ADD . /app
WORKDIR /app

# Update basic python packages
RUN apt-get update && apt-get install -y \
  python3-pip  \
  python3-dev  \
  build-essential  \
  libssl-dev  \
  libffi-dev  \
  python3-setuptools \
  wget \
  git

# Install conda
ENV CONDA_DIR /opt/conda
RUN wget \
  https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -nv \
  && bash Miniconda3-latest-Linux-x86_64.sh -b -p /opt/conda \
  && rm -f Miniconda3-latest-Linux-x86_64.sh
ENV PATH=$CONDA_DIR/bin:$PATH
RUN conda --version

# Install conda-smithy environment
RUN conda install -n root -c conda-forge conda-smithy -y

# We are installing a dependency here directly into our conda environment
RUN python -m pip install \
  PyGithub \
  pygit2 \
  cffi \
  bumpversion

# List all packages installed for debugging log
RUN conda list

# Run main.py
ENV PYTHONPATH /app
CMD ["python", "/app/main.py"]